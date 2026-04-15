# Phase 2 实现规划：RAG 基础设施（Module 1 + Module 2）

> **版本**：v1（2026-04-09）
> **目标**：把"来源异构的原始文档"变成"结构统一、身份稳定、可分层检索"的内部 corpus，完整支撑 hierarchical retrieval（先 paper-level → 再 evidence-level）。

---

## 一、背景与现状

### 1.1 当前系统的 RAG 能力

| 能力 | 现状 | 说明 |
|------|------|------|
| arXiv 元数据获取 | ✅ 已就绪 | `ingest_source.py` + arXiv API，支持 PDF 下载 |
| PDF 文本提取 | ✅ 基础就绪 | `ingest/ingestor.py` 用 pypdf，固定字符窗口切块 |
| chunk 持久化 | ✅ 已就绪 | PostgreSQL `chunks` 表（无向量） |
| BM25 检索 | ✅ 已就绪 | `HybridSearcher.search_bm25()` |
| 向量检索 | ⚠️ 降级运行 | FAISS index 未构建，向量检索不可用 |
| 本地 PDF 上传 ingest | ❌ 缺失 | 只能通过 ingest/ingestor.py 手动运行 |
| 多来源统一 ingest | ❌ 缺失 | arXiv / 本地 PDF / 在线来源未统一入口 |
| 元数据标准化 | ❌ 缺失 | title / authors / year 无规范化 |
| 论文身份归并（Canonicalization） | ❌ 缺失 | 同论文多来源未合并 |
| 层级切块（Coarse + Fine） | ❌ 缺失 | 只有固定字符窗口单层 chunk |
| 论文级检索（paper-level retrieval） | ❌ 缺失 | 目前只在 chunk 粒度检索 |
| 证据级检索（evidence retrieval） | ❌ 缺失 | evidence chunk 抽取未实现 |

### 1.2 Phase 2 在整体架构中的位置

```
Phase 1（已实现）
  SearchPlanAgent → PaperCardExtractor → Workspace
        ↓
Phase 2（本文档）
  Ingest/Normalize/Canonicalize (Module 1)
        ↓
  Coarse/Fine Chunking (Module 2)
        ↓
Phase 3（后续）
  Index & Store
        ↓
Phase 4（后续）
  Paper-level Retrieval + Evidence Retrieval
        ↓
Phase 5（后续）
  Draft Report → Review → Citation Verify
```

Phase 2 的产出直接服务于 Phase 3/4 的检索需求。

---

## 二、Module 1：Ingest / Normalize / Canonicalize

### 2.1 模块目标

把三类来源（arXiv ID / 本地上传 PDF / 在线 URL）统一转换为**标准化文档对象**，并解决"同一论文多个来源"的归并问题。

### 2.2 子步骤拆分

#### Step 1.1：统一 Ingest 入口

**职责**：接收来源，返回 `SourceRef` + 原始文本 + 原始元数据。

**三类 Loader**：

| Loader | 输入 | 输出 |
|--------|------|------|
| `ArxivLoader` | arXiv ID（如 `2301.12345`） | PDF bytes + metadata dict |
| `LocalPdfLoader` | 文件路径 / multipart upload | PDF bytes + filename |
| `OnlineUrlLoader` | URL | HTML/PDF bytes + content-type |

**复用机会**：
- `src/graph/nodes/ingest_source.py` 中的 arXiv API 调用逻辑 → 提取为 `ArxivLoader`
- `src/ingest/ingestor.py` 中的 PDF 下载 + pypdf 解析逻辑 → 整合进 `LocalPdfLoader`

**新增文件**：

```
src/corpus/ingest/
  pipeline.py          # 统一调度
  loaders/
    base.py            # Loader 抽象基类
    arxiv_loader.py    # arXiv API + PDF 下载
    local_pdf_loader.py  # 本地 PDF 读取
    online_url_loader.py  # URL 获取（requests）
```

**接口**：

```python
class BaseLoader(ABC):
    @abstractmethod
    def load(self, source: SourceInput) -> ParsedDocument: ...

class ArxivLoader(BaseLoader):
    def load(self, source: ArxivSourceInput) -> ParsedDocument: ...

class LocalPdfLoader(BaseLoader):
    def load(self, source: LocalPdfSourceInput) -> ParsedDocument: ...

class OnlineUrlLoader(BaseLoader):
    def load(self, source: OnlineSourceInput) -> ParsedDocument: ...

# 统一入口
def ingest(sources: list[SourceInput]) -> list[ParsedDocument]:
    # dispatch 到对应 loader
    # 返回 list[ParsedDocument]
```

---

#### Step 1.2：Parser 层

**职责**：从原始内容中提取文本 + 元数据 + 解析质量分。

**新增文件**：

```
src/corpus/ingest/
  parsers/
    pdf_parser.py      # PDF → 文本 + 页边界
    html_parser.py     # HTML → 文本（用于在线来源）
    metadata_extractor.py  # 提取 title/authors/abstract/year/venue
    parse_quality.py   # 质量评分
```

**Parser 输出**：

```python
@dataclass
class ParsedDocument:
    source_ref: SourceRef          # 来源记录
    extracted_text: str            # 原始文本
    extracted_metadata: dict       # title/authors/year/venue/abstract/DOI/arxiv_id
    parse_quality_score: float     # 0.0~1.0 质量分
    warnings: list[str]             # 解析异常警告
    page_texts: list[str]           # 按页分段的文本（保留结构）
```

**复用机会**：
- `src/ingest/ingestor.py` 中的 pypdf 解析逻辑 → 整合进 `pdf_parser.py`
- arXiv API 元数据提取逻辑 → 整合进 `metadata_extractor.py`

**Parser 质量评分策略**：
- 有完整 title + authors + abstract → 高分（0.9+）
- 仅有 title → 中等（0.6~0.8）
- title 提取失败或文本过短 → 低分（< 0.5）

---

#### Step 1.3：Normalizer 层

**职责**：文本清洗 + 元数据标准化。

**新增文件**：

```
src/corpus/ingest/
  normalizers/
    text_normalizer.py   # whitespace/header-footer/断句修复
    metadata_normalizer.py  # title/authors/year/venue 标准化
```

**文本标准化**：
- 合并连续空格、异常换行
- 修复 PDF 强行切断的句子（句号后无空格的情况）
- 去除常见 header/footer 噪声（如页码、"arXiv:..."）
- 保留 section 边界标记

**元数据标准化**：
- title：去除多余空白、统一大小写策略、去掉版本后缀（如 `v1`, `[v2]`）
- authors：统一分隔符、去除脚注标记/序号
- year：强制 int，异常值（如 `Submitted on`）→ None
- venue：别名映射（如 `NeurIPS` ↔ `NIPS` ↔ `Advances in Neural Information Processing Systems`）

**复用机会**：
- Phase 1 的 `ClarifyAgent` / `SearchPlanAgent` 中若有元数据处理 → 统一到此处

---

#### Step 1.4：Canonicalizer 层（核心）

**职责**：为每篇论文生成唯一身份 `canonical_id`，合并同一论文的多来源。

**新增文件**：

```
src/corpus/ingest/
  canonicalize.py       # 核心归并逻辑
  canonical_key.py      # canonical key 生成策略
```

**Canonical Key 策略**：

```
canonical_key = normalize_title(title) + lower(first_author_lastname) + year
加分信号（提高置信度）：
  - DOI 完全一致 → +0.5
  - arXiv ID 一致 → +0.5
  - venue 完全一致 → +0.1
```

**归并规则**：

| 条件 | 决策 |
|------|------|
| DOI 完全一致 | 高置信度同论文，自动合并 |
| arXiv ID 一致 | 高置信度同论文，自动合并 |
| normalized_title 相似度 > 0.9 + first_author 一致 + year 接近 | 候选同论文，需确认 |
| 同标题但 venue/year 差异明显 | 视为不同版本，保留但标记关系 |
| 标题差异大 | 不同论文，不合并 |

**Canonical ID 格式**：`canon_<sha256(normalized_title+first_author+year)[:16]>`

**复用机会**：
- `src/graph/nodes/ingest_source.py` 中的 `source_manifest` 尚无 `canonical_id` → 接入时补充
- Phase 1 的 `SearchPlanAgent` 若有去重逻辑 → 接入此处统一管理

---

#### Step 1.5：Persistence Preparation

**职责**：将标准化文档交给后续 chunking 模块，同时写入元数据库。

**复用机会**：
- `src/ingest/db.py` 的 `MetaDB` 类 → 扩展支持新字段
- `src/db/models.py` 的 `Document` 模型 → 添加 `canonical_id` / `source_type` 等字段

**新增/修改文件**：

```
src/corpus/ingest/
  pipeline.py           # 串联 Step 1.1~1.5

src/corpus/models.py    # 新增 DocumentMeta 增强字段
src/db/models.py         # Document 表扩展
src/ingest/db.py         # MetaDB 扩展
```

---

### 2.3 Module 1 数据流图

```
Raw Sources
  ├─ arXiv ID
  ├─ Local PDF (uploaded / folder)
  └─ Online URL
        ↓
Source Loader（统一入口 dispatch）
  ├─ ArxivLoader
  ├─ LocalPdfLoader
  └─ OnlineUrlLoader
        ↓
Parser
  ├─ PDF Parser / HTML Parser
  ├─ Metadata Extractor
  ├─ Parse Quality Scorer
  └─ Page-level text segmentation
        ↓
Normalizer
  ├─ Text cleanup (whitespace, headers/footers)
  └─ Metadata standardization (title, authors, year, venue)
        ↓
Canonicalizer
  ├─ Build canonical key
  ├─ Query existing canonical IDs
  ├─ Merge same-paper sources
  └─ Preserve version relations
        ↓
Standardized Document
  ├─ canonical_id
  ├─ source_ref[]
  ├─ normalized metadata
  ├─ parse_quality_score
  └─ ingest_status
        ↓
ready for Module 2 (Chunking)
```

---

### 2.4 Module 1 交付物清单

| # | 交付物 | 文件路径 | 说明 |
|---|--------|----------|------|
| 1 | 统一 `ingest()` 入口 | `src/corpus/ingest/pipeline.py` | 接收 list[SourceInput]，返回 list[Document] |
| 2 | 三个 Loader | `src/corpus/ingest/loaders/` | ArxivLoader + LocalPdfLoader + OnlineUrlLoader |
| 3 | Parser 层 | `src/corpus/ingest/parsers/` | PDF/HTML parser + metadata extractor + quality scorer |
| 4 | Normalizer 层 | `src/corpus/ingest/normalizers/` | Text + Metadata normalizer |
| 5 | Canonicalizer | `src/corpus/ingest/canonicalize.py` | 论文身份归并 |
| 6 | 扩展 Document ORM | `src/db/models.py` | 添加 canonical_id / source_type 等 |
| 7 | 扩展 MetaDB | `src/ingest/db.py` | 支持新字段 |
| 8 | 单元测试 | `tests/corpus/ingest/` | Loader / Normalizer / Canonicalizer 测试 |

---

## 三、Module 2：Coarse / Fine 双层 Chunking

### 3.1 模块目标

在 Module 1 产出的标准化文档上，构建**层级切块树**：coarse chunk 服务于 paper-level retrieval，fine chunk 服务于 evidence retrieval。

### 3.2 子步骤拆分

#### Step 2.1：Structure Detector

**职责**：识别论文的层级结构（title / abstract / sections / paragraphs / page boundaries）。

**新增文件**：

```
src/corpus/ingest/chunkers/
  structure_detector.py  # 论文结构识别
```

**识别策略**：
- **arXiv / ACL Anthology**：有标准 XML/HTML，可直接解析 section 结构
- **通用 PDF**：用规则 + 小模型识别标题行（字号大、两端对齐、无句号结尾等特征）
- **段落边界**：空行 + 缩进 + 行长度综合判断

**输出**：

```python
@dataclass
class PaperStructure:
    title: str
    abstract: str | None
    sections: list[Section]
    page_boundaries: list[int]  # char offsets

@dataclass
class Section:
    heading: str | None
    level: int           # 1=一级, 2=二级...
    paragraphs: list[Paragraph]
    page_start: int
    page_end: int
    char_start: int
    char_end: int

@dataclass
class Paragraph:
    text: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
```

**复用机会**：
- `src/corpus/ingest/ingestor.py` 中的固定字符窗口切块 → 由本模块替代

---

#### Step 2.2：Coarse Chunk Builder

**职责**：在结构边界内生成服务于 paper-level retrieval 的粗粒度块。

**新增文件**：

```
src/corpus/ingest/chunkers/
  coarse_chunker.py  # 生成 CoarseChunk
```

**Coarse Chunk 设计目标**：
- 能完整表达一个局部主题
- 长度适中（经验值：500~1500 tokens）
- 保留 section 归属信息

**切法策略**：
- **按 section 分块**：abstract / intro / method sections / experiments / conclusion 各自成块
- **长 section 二次切分**：若 section 超过 2000 tokens，在子段落边界再切
- **不跨 section 切**：避免混合无关内容

**CoarseChunk 输出**：

```python
@dataclass
class CoarseChunk:
    chunk_id: str
    doc_id: str
    canonical_id: str
    section: str           # e.g. "introduction", "methods"
    page_start: int
    page_end: int
    text: str
    token_count: int
    order: int             # 在文档中的顺序
    metadata: dict         # title, authors, source_ref...
```

---

#### Step 2.3：Fine Chunk Builder

**职责**：在 coarse chunk 内再细切，服务于 evidence retrieval。

**新增文件**：

```
src/corpus/ingest/chunkers/
  fine_chunker.py    # 生成 FineChunk
```

**Fine Chunk 设计目标**：
- 精确命中 supporting evidence
- 适当带轻量 overlap（避免证据断裂）

**切法策略**：
- **方案 A（优先）**：按段落切，最稳定
- **方案 B（辅助）**：句群 + 滑动窗口（2~5 句为一组，带 1~2 句 overlap）
- **不重 overlap**：coarse chunk 不带 overlap；fine chunk 轻量 overlap（10~15%）

**FineChunk 输出**：

```python
@dataclass
class FineChunk:
    chunk_id: str
    doc_id: str
    canonical_id: str
    parent_coarse_chunk_id: str
    section: str
    page_start: int
    page_end: int
    text: str
    token_count: int
    order: int
    metadata: dict
```

---

#### Step 2.4：Chunk Linker

**职责**：建立父子关系 + section/page/order 元数据，并持久化。

**新增文件**：

```
src/corpus/ingest/chunkers/
  chunk_linker.py   # 建立 parent-child 关系 + 持久化
```

**持久化目标**：
- `coarse_chunks` → PostgreSQL 表（新增）
- `fine_chunks` → PostgreSQL 表（新增）
- `chunk_relations` → PostgreSQL 表（coarse_id ↔ fine_ids）

---

### 3.3 Module 2 数据流图

```
Standardized Document (from Module 1)
        ↓
Structure Detector
  ├─ title / abstract
  ├─ section headings + levels
  ├─ paragraph boundaries
  └─ page boundaries (char offsets)
        ↓
Coarse Chunk Builder
  ├─ abstract chunk (单独)
  ├─ intro chunks (2~4 paragraph groups)
  ├─ method chunks (per subsection)
  ├─ experiment chunks (per subsection)
  └─ conclusion chunk (单独)
        ↓
Fine Chunk Builder (within each coarse chunk)
  ├─ paragraph chunks (primary)
  ├─ sentence-group chunks (for long paragraphs)
  └─ lightweight overlap (10~15% for fine only)
        ↓
Chunk Linker
  ├─ parent-child relations (fine → coarse)
  ├─ section/page/order metadata
  └─ persist to PostgreSQL
        ↓
CoarseChunk[] + FineChunk[] + ChunkTree
        ↓
ready for Module 3 (Index & Store)
```

### 3.4 切法参数推荐

| 参数 | Coarse Chunk | Fine Chunk |
|------|-------------|------------|
| 目标 token 数 | 500~1500 | 100~300 |
| 重叠率 | 0% | 10~15% |
| 切分策略 | section-aware，主题完整优先 | paragraph-first，可带句群窗口 |
| 跨 section 切分 | ❌ 禁止 | ❌ 禁止 |
| 保留结构 | section / page / order | section / page / order / parent |

---

### 3.5 Module 2 与后续模块的衔接

```
CoarseChunk[]
   ↓
Module 3: Index & Store
  ├─ coarse_chunks → paper-level vector index (title + abstract + coarse text)
  └─ fine_chunks → evidence-level vector index
        ↓
Module 4: Paper-level Retrieval
  ├─ hybrid retrieval on coarse_chunks
  └─ → Top-K PaperCandidate
        ↓
Module 4: Evidence Retrieval
  ├─ within selected papers, search fine_chunks
  └─ → EvidenceChunk[] + RagResult
```

---

### 3.6 Module 2 交付物清单

| # | 交付物 | 文件路径 | 说明 |
|---|--------|----------|------|
| 1 | Structure Detector | `src/corpus/ingest/chunkers/structure_detector.py` | 识别论文结构 |
| 2 | Coarse Chunker | `src/corpus/ingest/chunkers/coarse_chunker.py` | 生成 CoarseChunk |
| 3 | Fine Chunker | `src/corpus/ingest/chunkers/fine_chunker.py` | 生成 FineChunk |
| 4 | Chunk Linker | `src/corpus/ingest/chunkers/chunk_linker.py` | 父子关系 + 持久化 |
| 5 | 完整 Chunking Pipeline | `src/corpus/ingest/chunkers/pipeline.py` | 串联 2.1~2.4 |
| 6 | CoarseChunk 数据类 | `src/corpus/models.py` | 新增 |
| 7 | FineChunk 数据类 | `src/corpus/models.py` | 新增 |
| 8 | PostgreSQL 表扩展 | `src/db/models.py` | coarse_chunks / fine_chunks / chunk_relations |
| 9 | 单元测试 | `tests/corpus/chunkers/` | 各 chunker + pipeline 测试 |

---

## 四、Module 1 + Module 2 联合 Pipeline

```
Raw Sources
  │
  ├─ arXiv ID ──────────┐
  ├─ Local PDF ────────┤
  └─ Online URL ───────┤
                        ↓
              Module 1: Ingest Pipeline
  ┌──────────────────────────────────────┐
  │  Loader → Parser → Normalizer       │
  │           → Canonicalizer           │
  │           → StandardizedDocument    │
  └──────────────────────────────────────┘
                        ↓
              Module 2: Chunking Pipeline
  ┌──────────────────────────────────────┐
  │  StructureDetector                   │
  │  → CoarseChunkBuilder                │
  │  → FineChunkBuilder                  │
  │  → ChunkLinker (persist)             │
  └──────────────────────────────────────┘
                        ↓
          CoarseChunk[] + FineChunk[]
                        ↓
          Module 3: Index & Store（后续）
          ├─ coarse_chunks → paper-level index
          └─ fine_chunks → evidence-level index
```

---

## 五、数据库变更方案

### 5.1 新增表

#### `canonical_papers`

| 列名 | 类型 | 说明 |
|------|------|------|
| canonical_id | VARCHAR(64) PK | 论文唯一身份 |
| canonical_key | VARCHAR(512) UNIQUE | 归并 key（normalized title + author + year） |
| primary_title | VARCHAR(512) | 主标题 |
| primary_authors | TEXT | 主作者列表 |
| primary_year | INT | 出版年 |
| doi | VARCHAR(256) | DOI（可选） |
| arxiv_id | VARCHAR(64) | arXiv ID（可选） |
| version_group | VARCHAR(64) | 版本组 ID（同论文不同版本） |
| source_count | INT | 来源数量 |
| created_at | FLOAT | 创建时间 |

#### `coarse_chunks`

| 列名 | 类型 | 说明 |
|------|------|------|
| coarse_chunk_id | VARCHAR(64) PK | 粗块 ID |
| doc_id | VARCHAR(64) FK | 所属文档 |
| canonical_id | VARCHAR(64) FK | 所属论文 |
| section | VARCHAR(128) | 章节名 |
| page_start | INT | 起始页 |
| page_end | INT | 结束页 |
| char_start | INT | 起始字符 |
| char_end | INT | 结束字符 |
| text | TEXT | 块文本 |
| text_hash | VARCHAR(64) | 文本哈希 |
| token_count | INT | token 数 |
| order_idx | INT | 文档内顺序 |
| metadata | JSONB | 附加元数据 |

#### `fine_chunks`

| 列名 | 类型 | 说明 |
|------|------|------|
| fine_chunk_id | VARCHAR(64) PK | 细块 ID |
| doc_id | VARCHAR(64) FK | 所属文档 |
| canonical_id | VARCHAR(64) FK | 所属论文 |
| coarse_chunk_id | VARCHAR(64) FK | 父粗块 |
| section | VARCHAR(128) | 章节名 |
| page_start | INT | 起始页 |
| page_end | INT | 结束页 |
| char_start | INT | 起始字符 |
| char_end | INT | 结束字符 |
| text | TEXT | 块文本 |
| text_hash | VARCHAR(64) | 文本哈希 |
| token_count | INT | token 数 |
| order_idx | INT | 粗块内顺序 |
| metadata | JSONB | 附加元数据 |

#### `source_refs`

| 列名 | 类型 | 说明 |
|------|------|------|
| source_id | VARCHAR(64) PK | 来源 ID |
| canonical_id | VARCHAR(64) FK | 所属论文 |
| source_type | VARCHAR(32) | local_folder / uploaded_pdf / online / arxiv |
| uri_or_path | VARCHAR(1024) | 来源路径/URL |
| external_id | VARCHAR(256) | arXiv ID / DOI（可选） |
| version | VARCHAR(32) | 版本信息（可选） |
| parse_quality | FLOAT | 解析质量分 |
| ingest_status | VARCHAR(32) | pending / processed / failed |
| created_at | FLOAT | 创建时间 |

### 5.2 修改现有表

**`documents` 表扩展**：
- 添加 `canonical_id`（FK → canonical_papers）
- 添加 `source_id`（FK → source_refs）
- 添加 `source_type`（VARCHAR(32)）
- 添加 `parse_quality`（FLOAT）

**`chunks` 表**：
- 暂时保留（Phase 3/4 再决定是否迁移到 coarse/fine 双层）
- 建议 Phase 2 暂不修改现有 `chunks` 表，新增 coarse_chunks / fine_chunks 表

---

## 六、里程碑与优先级

### 里程碑 1（M1）：Module 1 核心闭环

| 任务 | 优先级 | 依赖 |
|------|--------|------|
| 统一 ingest pipeline + ArxivLoader | P0 | 无 |
| 扩展 Document ORM + DB | P0 | 无 |
| Text + Metadata Normalizer | P1 | ArxivLoader |
| Canonicalizer（arXiv ID 归并） | P1 | Normalizer |
| 本地 PDF Loader | P2 | ArxivLoader 参考 |
| 在线 URL Loader | P2 | ArxivLoader 参考 |
| 单元测试 | P1 | 各子步骤 |

**M1 完成标准**：给定一个 arXiv ID，能通过 `ingest()` 产出带 `canonical_id` 的 `Document` 对象，并写入 PostgreSQL。

### 里程碑 2（M2）：Module 2 核心闭环

| 任务 | 优先级 | 依赖 |
|------|--------|------|
| Structure Detector（通用 PDF 结构识别） | P0 | Module 1 |
| Coarse Chunk Builder | P0 | Structure Detector |
| Fine Chunk Builder | P1 | Coarse Chunk Builder |
| Chunk Linker + 持久化 | P0 | Coarse + Fine Builder |
| Coarse/Fine DB 表 + ORM | P0 | Chunk Linker |
| 单元测试 | P1 | 各子步骤 |

**M2 完成标准**：给定一个标准化 Document，能产出 `CoarseChunk[]` + `FineChunk[]`，并持久化到 PostgreSQL coarse_chunks / fine_chunks 表。

### 里程碑 3（M3）：端到端集成

| 任务 | 优先级 | 依赖 |
|------|--------|------|
| Module 1 + Module 2 串联测试 | P0 | M1 + M2 |
| 真实 PDF（多篇不同来源）归并测试 | P1 | Canonicalizer |
| 与 Phase 1 SearchPlanAgent 接入（search_local_corpus） | P2 | M2 |
| 与 Phase 3 Index & Store 接口对接 | P2 | M2 |

**M3 完成标准**：完整 pipeline 能处理 arXiv ID → canonicalize → coarse/fine chunk → 持久化，且后续 SearchPlanAgent 可调用检索。

---

## 七、工程结构总览

```
src/corpus/
  ingest/
    pipeline.py              # 统一入口
    loaders/
      __init__.py
      base.py                # BaseLoader 抽象
      arxiv_loader.py        # ArxivLoader
      local_pdf_loader.py    # LocalPdfLoader
      online_url_loader.py   # OnlineUrlLoader
    parsers/
      __init__.py
      pdf_parser.py          # PDF → ParsedDocument
      html_parser.py          # HTML → ParsedDocument
      metadata_extractor.py  # 提取元数据
      parse_quality.py       # 质量评分
    normalizers/
      __init__.py
      text_normalizer.py     # 文本清洗
      metadata_normalizer.py  # 元数据标准化
    canonicalize.py          # 论文身份归并
    chunkers/
      __init__.py
      pipeline.py            # chunking pipeline
      structure_detector.py  # 论文结构识别
      coarse_chunker.py      # CoarseChunk 生成
      fine_chunker.py        # FineChunk 生成
      chunk_linker.py        # 父子关系 + 持久化

  models.py                  # Document / CoarseChunk / FineChunk 数据类

src/db/
  models.py                   # SQLAlchemy ORM（含新表）

src/ingest/
  db.py                       # MetaDB 扩展

tests/corpus/
  ingest/
    test_loaders.py
    test_normalizers.py
    test_canonicalizer.py
    test_pipeline.py
  chunkers/
    test_structure_detector.py
    test_coarse_chunker.py
    test_fine_chunker.py
    test_chunk_linker.py
    test_pipeline.py
```

---

## 八、风险与依赖

### 风险

| 风险 | 概率 | 影响 | 缓解策略 |
|------|------|------|----------|
| PDF 结构识别不稳定（多模板） | 中 | 高 | MVP 用规则识别 + page-level 切块兜底；后续引入小模型 |
| 同论文多来源归并误判 | 中 | 中 | arXiv ID / DOI 优先；仅在无 external ID 时用 title similarity |
| 现有 ingest 逻辑被废弃 | 低 | 中 | 保持向后兼容，ingest_source.py 暂不删除 |
| PostgreSQL 迁移复杂 | 低 | 中 | 用 Alembic 管理 migration；先在测试库验证 |

### 依赖

| 依赖 | 当前状态 | 说明 |
|------|----------|------|
| PostgreSQL | ✅ 已就绪 | `documents` / `chunks` 表已建 |
| pypdf / pdfplumber | ✅ 已用 | 用于 PDF 解析 |
| SQLAlchemy 2.0 | ✅ 已用 | ORM 基础已就绪 |
| sentence-transformers | ⚠️ 未安装 | Phase 3/4 向量索引时才需要 |
| faiss | ✅ 已用 | Phase 3/4 向量检索时才需要 |

---

## 九、后续扩展方向（Phase 3~5）

- **Phase 3**：Index & Store — coarse/fine chunk 分别建索引（BM25 + FAISS）
- **Phase 4**：Paper-level + Evidence Retrieval — hierarchical retrieval 实现
- **Phase 5**：Draft Report → Review → Citation Verify — RAG 结果服务报告生成
