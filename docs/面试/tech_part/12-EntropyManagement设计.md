# PaperReader Agent — Entropy Management 熵管理系统设计

> 本文档基于 `docs/features_oncoming/entropy-management.md`，分析当前项目熵增问题并给出详细技术设计。

---

## 1. Entropy 定义与问题

### 1.1 什么是 Entropy（熵）

在 Harness Engineering 框架中，**Entropy** 是指 AI Agent 系统运行一段时间后，代码库和文档逐渐偏离原始设计意图的累积效应。与热力学的熵增类似：没有主动做功（清理），系统自发趋向混乱。

### 1.2 Agent 系统熵的四大来源

```
┌─────────────────────────────────────────────────────────┐
│                    Entropy 的四大来源                    │
├─────────────────┬───────────────────────────────────────┤
│  文档漂移        │  代码改了，文档没改；文档改了，代码没改     │
├─────────────────┼───────────────────────────────────────┤
│  模式不一致      │  Agent A 生成的代码风格 ≠ Agent B 的     │
├─────────────────┼───────────────────────────────────────┤
│  死代码积累      │  重命名节点后旧代码路径仍在，Agent 仍会撞   │
├─────────────────┼───────────────────────────────────────┤
│  约束侵蚀        │  新增 import 绕过 .cursorignore 规则     │
└─────────────────┴───────────────────────────────────────┘
```

### 1.3 当前项目的熵证据

| 熵类型 | 证据 | 影响 |
|--------|------|------|
| 文档漂移 | `docs/design_version/` 有多个版本（2026-02-15、2026-03-29），结构不一致 | Agent 无法判断哪个是真实架构 |
| 文档漂移 | `docs/active/` 和 `docs/design_version/` 混用，Phase 2/3/4 文档散落各处 | 新 Agent 困惑 |
| 模式不一致 | `analyst_agent.py` 有 `build_graph()`，但 `retriever_agent.py` 只有 import | 同为 V2 Agent，实现形态不一致 |
| 死代码 | `src/research/graph/nodes/` 下部分节点未被 `LEGACY_NODE_TARGETS` 引用但文件存在 | Agent 可能误调 |
| 约束侵蚀 | `.cursorignore` 被修改（git status 显示 `M .cursorignore`）| 规则被绕过 |

---

## 2. 系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      Entropy Management System                    │
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐   │
│  │ EntropyScanner│→  │ EntropyReport │→  │ Scheduled Cleanup Agents │   │
│  │  (检测层)    │    │  (报告层)     │    │  (清理层)                │   │
│  └──────┬──────┘    └──────┬──────┘    └───────────┬─────────┘   │
│         │                  │                       │              │
│         ▼                  ▼                       ▼              │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │               Hooks / CI Integration (预防层)              │  │
│  │         Pre-commit + CI Pipeline + Agent System Hooks       │  │
│  └────────────────────────────────────────────────────────────┘  │
│                           │                                     │
│                           ▼                                     │
│                 ┌─────────────────┐                            │
│                 │ Entropy Dashboard │ (前端展示)                  │
│                 └─────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
src/entropy/
├── __init__.py
├── scanner.py          # 检测器核心
├── detectors/
│   ├── __init__.py
│   ├── doc_drift.py     # 文档漂移检测
│   ├── style_drift.py   # 代码风格不一致检测
│   ├── dead_code.py     # 死代码检测
│   ├── constraint.py    # 约束违反检测
│   └── artifact.py       # Agent 产物质量检测
├── cleaners/
│   ├── __init__.py
│   ├── doc_cleaner.py   # 文档修复
│   ├── style_cleaner.py # 代码格式化
│   └── dead_code_cleaner.py
├── scheduler.py         # 调度器
├── report.py            # 报告生成
└── hooks.py             # CI / pre-commit 集成
```

---

## 3. 检测器设计（Detect）

### 3.1 DocDriftDetector — 文档漂移检测

```python
class DocDriftDetector:
    """检测代码与文档之间的不一致"""

    def __init__(self):
        self.rules = [
            # 规则 1：src/ 下的模块必须在 docs/ 有对应说明
            DriftRule(
                pattern="src/research/agents/*.py",
                expected_doc="docs/active/phase/{agent_name}.md",
                drift_type="missing_doc",
            ),
            # 规则 2：CANONICAL_NODE_ORDER 中列出的节点必须存在
            DriftRule(
                pattern="src/research/agents/supervisor.py",
                check_list="CANONICAL_NODE_ORDER",
                check_exists="src/research/graph/nodes/{node}.py",
                drift_type="missing_node_file",
            ),
        ]

    def scan(self) -> list[DriftReport]:
        """扫描所有漂移问题"""
        reports = []
        for rule in self.rules:
            if rule.drift_type == "missing_doc":
                reports.extend(self._check_missing_docs(rule))
            elif rule.drift_type == "missing_node_file":
                reports.extend(self._check_missing_nodes(rule))
        return reports


@dataclass
class DriftReport:
    drift_type: str          # missing_doc | unenforced_constraint | missing_node_file
    source_file: str         # 违规的文件
    expected_state: str      # 期望状态
    actual_state: str        # 实际状态
    severity: Literal["critical", "warning", "info"]
    fix_suggestion: str      # 修复建议
```

### 3.2 DeadCodeDetector — 死代码检测

```python
class DeadCodeDetector:
    """检测无法到达的代码路径"""

    def scan_unreachable_nodes(self) -> list[DeadCodeReport]:
        """检测 LEGACY_NODE_TARGETS / V2_AGENT_TARGETS 中引用的节点是否都存在"""
        reports = []

        supervisor = Path("src/research/agents/supervisor.py").read_text()

        # 检查 LEGACY_NODE_TARGETS
        legacy_nodes = self._extract_dict_values(supervisor, "LEGACY_NODE_TARGETS")
        for node in legacy_nodes:
            module_path = f"src/research/graph/nodes/{node}.py"
            if not Path(module_path).exists():
                reports.append(DeadCodeReport(
                    node_name=node,
                    referenced_by="LEGACY_NODE_TARGETS",
                    actual_path=None,
                    severity="critical",
                    suggestion=f"移除 LEGACY_NODE_TARGETS 中对 {node} 的引用",
                ))

        # 检查 V2_AGENT_TARGETS
        v2_nodes = self._extract_dict_values(supervisor, "V2_AGENT_TARGETS")
        for node in v2_nodes:
            module_path = f"src/research/agents/{node}_agent.py"
            if not Path(module_path).exists():
                reports.append(DeadCodeReport(
                    node_name=node,
                    referenced_by="V2_AGENT_TARGETS",
                    actual_path=None,
                    severity="critical",
                    suggestion=f"移除 V2_AGENT_TARGETS 中对 {node} 的引用",
                ))

        return reports

    def scan_orphaned_files(self) -> list[DeadCodeReport]:
        """检测没有被任何地方引用的文件"""
        all_imports = self._extract_all_imports()
        orphaned = []

        for py_file in Path("src").rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            imports_this = self._extract_imports(py_file)
            if not any(imp in all_imports or self._file_name_in_imports(py_file, all_imports)
                       for imp in imports_this):
                if not self._is_entry_point(py_file):
                    orphaned.append(...)
        return orphaned
```

### 3.3 ConstraintViolationDetector — 约束违反检测

```python
class ConstraintViolationDetector:
    """检测对项目硬约束的违反"""

    HARD_CONSTRAINTS = [
        # 约束 1：不能有 SQLite
        Constraint(
            id="no_sqlite",
            description="禁止引入 SQLite 数据库或 sqlite:/// URL",
            check=lambda f: "sqlite:///" not in f.read_text()
                          and ".sqlite" not in f.name,
            severity="critical",
        ),
        # 约束 2：所有持久化必须走 PostgreSQL
        Constraint(
            id="postgres_persistence",
            description="所有长期持久化必须使用 DATABASE_URL",
            check=self._check_persistence_layer,
            severity="critical",
        ),
        # 约束 3：.env 必须在脚本中显式加载
        Constraint(
            id="explicit_dotenv",
            description="脚本和测试必须显式 load_dotenv('.env')",
            check=self._check_dotenv_loading,
            severity="warning",
        ),
        # 约束 4：V2 Agent 必须实现 build_graph()
        Constraint(
            id="agent_has_graph",
            description="V2_AGENT_TARGETS 中的 Agent 必须有 build_graph() 方法",
            check=self._check_agent_graph,
            severity="warning",
        ),
    ]
```

---

## 4. 清理器设计（Clean）

### 4.1 DocCleaner

```python
class DocCleaner:
    """文档清理：补全、删除过时文件、同步版本"""

    def generate_missing_docs(self, drift_reports: list[DriftReport]) -> list[FileChange]:
        """为缺失的文档生成占位符"""
        changes = []
        for report in drift_reports:
            if report.drift_type == "missing_doc":
                template = self._get_doc_template(report.source_file)
                changes.append(FileChange(
                    path=report.expected_doc,
                    action="create",
                    content=template,
                    reason=f"文档缺失：{report.source_file}",
                ))
        return changes

    def prune_obsolete_docs(self) -> list[FileChange]:
        """删除过时文档（删除 6 个月前的 design_version 文档）"""
        cutoff = datetime.now() - timedelta(days=180)
        changes = []
        for doc in Path("docs/design_version/").rglob("*.md"):
            mtime = datetime.fromtimestamp(doc.stat().st_mtime)
            if mtime < cutoff:
                changes.append(FileChange(
                    path=str(doc),
                    action="delete",
                    content=None,
                    reason=f"文档过期（{mtime.date()}）",
                ))
        return changes
```

### 4.2 DeadCodeCleaner

```python
class DeadCodeCleaner:
    """死代码清理：删除孤立文件、清理无效引用"""

    def remove_orphaned_files(self, reports: list[DeadCodeReport]) -> list[FileChange]:
        """删除孤立文件"""
        changes = []
        for report in reports:
            if report.drift_type == "orphaned_file":
                changes.append(FileChange(
                    path=report.source_file,
                    action="delete",
                    reason=f"孤立文件（未被任何地方引用）：{report.source_file}",
                ))
        return changes

    def fix_missing_node_references(self, reports: list[DeadCodeReport]) -> list[FileChange]:
        """清理对不存在节点的引用"""
        changes = []
        supervisor_path = Path("src/research/agents/supervisor.py")

        for report in reports:
            if "missing_node" in report.drift_type:
                changes.append(FileChange(
                    path=str(supervisor_path),
                    action="edit",
                    old_string=report.referenced_by,
                    new_string="# " + report.referenced_by + " (removed by entropy cleaner)",
                    reason=f"引用了不存在的节点：{report.node_name}",
                ))
        return changes
```

---

## 5. 调度器设计

### 5.1 调度策略

| 类型 | 触发条件 |
|------|---------|
| On-commit | 每次 git commit 后自动扫描 |
| Daily | 每天凌晨 2:00 运行全量扫描 |
| On-PR | PR 打开时运行 PR 范围内的 Entropy 扫描 |
| Manual | 开发者手动触发（API 或 CLI） |

### 5.2 调度器实现

```python
class EntropyScheduler:
    """熵管理调度器"""

    def __init__(self, scanner: EntropyScanner, cleaners: list[EntropyCleaner]):
        self.scanner = scanner
        self.cleaners = cleaners

    async def run_on_commit(self, changed_files: list[str]) -> EntropyReport:
        """git commit 钩子触发：只扫描变更文件"""
        reports = self.scanner.scan_files(changed_files)
        return self._build_report(reports, trigger="on_commit")

    async def run_daily(self) -> EntropyReport:
        """每日全量扫描"""
        reports = self.scanner.scan_all()
        changes = self._apply_auto_fixes(reports)
        return self._build_report(reports, changes, trigger="daily")

    async def run_on_pr(self, pr_diff: str, base_branch: str) -> EntropyReport:
        """PR 触发：扫描 PR 范围内的新增熵"""
        changed_files = self._extract_changed_files(pr_diff)
        new_violations = self.scanner.scan_files(changed_files)
        return self._build_report(new_violations, trigger="on_pr")

    def _apply_auto_fixes(self, reports: list[DriftReport]) -> list[FileChange]:
        """
        自动应用可安全修复的变更
        规则：只有 severity=info 或 confirmed_safe=True 的才自动修复
        """
        changes = []
        for report in reports:
            if report.severity == "info" and report.auto_fixable:
                for cleaner in self.cleaners:
                    if cleaner.can_handle(report):
                        changes.extend(cleaner.fix(report))
        return changes
```

---

## 6. API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/entropy/scan` | POST | 手动触发扫描 |
| `/api/v1/entropy/report` | GET | 获取最新报告 |
| `/api/v1/entropy/fix` | POST | 应用建议的修复 |
| `/api/v1/entropy/dashboard` | GET | 前端 Dashboard 数据 |

---

## 7. 实施优先级

### Phase 1：核心框架（P1）

| 任务 | 内容 | 文件 |
|------|------|------|
| `EntropyScanner` 核心 + `DriftReport` 数据模型 | 核心框架 | `src/entropy/scanner.py` |
| `DeadCodeDetector`：检测 `CANONICAL_NODE_ORDER` 引用 vs 文件存在性 | 立即可用 | `src/entropy/detectors/dead_code.py` |
| `ConstraintViolationDetector`：检测 SQLite 引入 | 立即可用 | `src/entropy/detectors/constraint.py` |
| Entropy CLI：`python -m src.entropy.cli scan` | CLI 工具 | `src/entropy/__main__.py` |

### Phase 2：文档管理 + 调度（P2）

| 任务 | 内容 | 文件 |
|------|------|------|
| `DocDriftDetector`：检测代码-文档不一致 | 文档管理 | `src/entropy/detectors/doc_drift.py` |
| `DocCleaner`：生成缺失文档、补全模板 | 文档管理 | `src/entropy/cleaners/doc_cleaner.py` |
| 每日扫描调度器 | 调度 | `src/entropy/scheduler.py` |
| Entropy Dashboard API + 前端组件 | 可视化 | `src/api/routes/entropy.py` + `frontend/` |

### Phase 3：风格管理 + 预防（P3）

| 任务 | 内容 | 文件 |
|------|------|------|
| `StyleDriftDetector`：检测 Agent 产物风格不一致 | 风格管理 | `src/entropy/detectors/style_drift.py` |
| Pre-commit Hook 集成 | 预防 | `src/entropy/hooks.py` + `.pre-commit-config.yaml` |
| GitHub Actions CI 集成 | 预防 | `.github/workflows/entropy.yml` |
