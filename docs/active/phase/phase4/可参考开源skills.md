### 1. ARIS：`research-lit`

`Auto-claude-code-research-in-sleep` 本身就是面向 autonomous ML research workflows 的 skills repo，而且它明确有 `research-lit` 这类技能页；该 skill 会按优先顺序检查多个数据源，适合做多源 literature scan。它的 `research-pipeline` skill 也把 `/research-lit → /idea-creator → /novelty-check → /research-review` 串成流水线。

我建议借它的不是整套命令，而是这个 skill 的结构：

- **Skill 名称**：`research_lit_scan`
- **默认 agent**：Retriever
- **后端**：`LOCAL_GRAPH` 或 `MCP_TOOLCHAIN`
- **输入**：topic / constraints / source priority
- **输出**：`RagResult + candidate papers`
- **调用情况**：

  - Auto：Planner 完成后自动调用
  - Explicit：前端按钮“文献初扫”
- **作用**：

  - 多源拉取候选论文
  - 形成第一版 candidate set
  - 为后续 select\_papers / extract\_cards 服务

### 2. ARIS：`paper-plan`

ARIS 里还有 `paper-plan` 这样的 skill 页面，适合把研究 brief、paper cards 和 reviewer 反馈收束成写作/实验计划。

建议纳入为：

- **Skill 名称**：`paper_plan_builder`
- **默认 agent**：Analyst
- **后端**：`LOCAL_GRAPH`
- **输入**：ResearchBrief / PaperCard[] / ComparisonMatrix / ReviewFeedback
- **输出**：`ReportOutline`
- **调用情况**：

  - Auto：Analyst 在 synthesize 后调用
  - Explicit：前端按钮“生成写作大纲”
- **作用**：

  - 从抽取结果走到真正可写的 section outline
  - 减少 report draft 直接自由生成的漂移

### 3. AI-Research-SKILLs：`creative-thinking-for-research`

`AI-Research-SKILLs` 明确定位为“从 literature survey、idea generation 到 experiment execution、paper writing”的研究技能库，而且当前 README/CLAUDE 文档都把它描述成大规模 skill library；其中 `creative-thinking-for-research` 是一个很具体的 skill，用认知科学里的创造性框架帮助研究问题重构。

我不建议把它放到默认主链里，而是作为 **Planner 的显式强化 skill**：

- **Skill 名称**：`creative_reframe`
- **默认 agent**：Planner
- **后端**：`MCP_PROMPT` 或本地 prompt bundle
- **输入**：ResearchBrief / failed retrieval context / novelty request
- **输出**：Refined brief / alternative sub-questions / query variants
- **调用情况**：

  - Auto：只在 re-plan 时触发
  - Explicit：前端按钮“问题重构 / 新意增强”
- **作用**：

  - 避免 planner 只会机械拆 query
  - 在 reviewer 指出 coverage gap 或 novelty 不足时生成更好的 re-plan

### 4. OpenHands：repository microagent pattern

OpenHands 提供了 repository microagent 的模式：在 `.openhands/microagents/repo.md` 放仓库级指令，系统工作时自动加载。这个模式特别适合你这里的 workspace-scoped skills。

我建议借用这个模式做：

- **Skill 名称**：`workspace_policy_skill`
- **默认 agent**：所有 agent 都可读，Supervisor 控制启用
- **后端**：`LOCAL_FUNCTION` + workspace artifact
- **输入**：workspace-scoped instruction file
- **输出**：无独立 artifact，作为上下文约束注入
- **调用情况**：

  - Auto：进入 workspace 时自动挂载
  - Explicit：前端 toggle “启用领域技能”
- **作用**：

  - 领域规则，如 citation style、paper inclusion policy、dataset naming conventions
  - 项目规则，如只优先读本地 PDF、先中文后英文、必须输出 comparison matrix

这比把所有项目规则写死在 system prompt 里稳得多。