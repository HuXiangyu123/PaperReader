# 模块 1：Ingest / Normalize / Canonicalize

## 1. 这个模块解决什么问题

这个模块的任务不是“把 PDF 存起来”，而是把不同来源的文档统一变成**后续检索可用的标准对象**。

因为你这个系统不是单纯聊天问答，而是 research workflow。后面要做：

- paper-level retrieval
- dedup
- rerank
- evidence chunk retrieval
- reviewer 检查 citation reachability

如果最开始入库就乱，比如：

- 同一篇论文有多个来源却没合并
- PDF 文本解析质量差
- 标题作者年份抽错
- 没有 source / version 信息

那后面所有模块都会跟着歪。RAG 综述里通常把这类工作放在 pre-retrieval / pre-processing 阶段，而且都强调它对后续检索质量有直接影响。Haystack 官方文档也明确把 preprocessing、splitting、writing to document store 视为 indexing pipeline 的核心组成部分。([arXiv](https://arxiv.org/abs/2404.10981?utm_source=chatgpt.com "A Survey on Retrieval-Augmented Text Generation for Large Language Models"))

所以这个模块的核心目标就一句话：

**把“来源异构的原始文档”变成“结构统一、身份稳定、可索引、可追踪”的内部文档对象”。**

---

## 2. 模块职责拆分

我建议这个模块内部再拆成 5 个子步骤：

### 2.1 Source Ingestion

接收三类输入：

- local folder
- uploaded PDF
- online source

### 2.2 Parsing

把原始来源解析成文本和基础元数据：

- title
- authors
- year
- venue
- abstract
- raw text
- source ref

### 2.3 Normalization

做文本和元数据标准化：

- whitespace / line break 清理
- header/footer 噪声去除
- 标题标准化
- 作者字段标准化
- 年份 / venue 统一格式

Haystack 官方 preprocessors 就是围绕这些动作设计的：清理空行、去除噪声、切分长文档等，明确用于 indexing pipeline 的数据准备。([Haystack Documentation](https://docs.haystack.deepset.ai/docs/preprocessors?utm_source=chatgpt.com "PreProcessors"))

### 2.4 Canonicalization

解决“同一论文多个来源 / 多个版本”的问题：

- arXiv
- conference
- journal
- 作者主页 PDF
- 用户本地 PDF

这里要生成一个 **canonical paper identity**。

### 2.5 Persistence Preparation

把处理后的文档交给后面的 chunking / index 模块，进入 corpus store。

---

## 3. 推荐的数据对象

这个模块建议至少产出两个对象：

### `SourceRef`

表示来源，不是论文本体。

```text
SourceRef
- source_type            # local_folder / uploaded_pdf / online
- uri_or_path
- file_id(optional)
- external_id(optional)  # arXiv id / DOI
- version(optional)      # arXiv v1/v2, conference, journal
```

### `Document`

表示标准化后的内部文档对象。

```text
Document
- doc_id
- workspace_id
- canonical_id(optional)
- source_ref
- title
- authors[]
- year
- venue
- doi(optional)
- arxiv_id(optional)
- abstract
- raw_text
- ingest_status
- created_at
- updated_at
```

这里最关键的是：

- `source_ref` 保留来源
- `canonical_id` 表示“它属于哪篇论文”

也就是一个 canonical paper 可以挂多个 source refs。

---

## 4. 实现方式建议

## 4.1 入口设计

建议统一入口，不要给三种来源各写独立检索逻辑。

```text
POST /corpus/ingest
  ├─ source_type = local_folder
  ├─ source_type = uploaded_pdf
  └─ source_type = online
```

内部 dispatch 到不同 loader：

```text
loaders/
  ├─ local_folder_loader.py
  ├─ uploaded_pdf_loader.py
  └─ online_source_loader.py
```

### 为什么一定要统一入口

因为后续的 normalize / canonicalize / chunk / index 完全应该复用。
如果这里分叉，后面 dedup 和 trace 会非常难看。

---

## 4.2 Parsing 设计

这里建议 parser 不要只返回纯文本，至少同时返回：

```text
ParsedDocument
- source_ref
- extracted_text
- extracted_metadata
- parse_quality_score
- warnings[]
```

### 为什么加 `parse_quality_score`

因为 PDF 解析质量很不稳定。
后面 reviewer 或 eval 如果发现某篇论文表现异常，你需要知道是 retrieval 问题，还是一开始 parse 就烂了。

---

## 4.3 Normalization 设计

标准化建议分两层：

### 文本标准化

- 去掉连续空格、异常换行
- 合并被 PDF 强行切断的句子
- 去掉常见 header/footer
- 保留 section 边界信息

### 元数据标准化

- title：去空白、统一大小写策略、去多余版本前后缀
- authors：统一分隔符、去脚注标记
- year：强制 int
- venue：做别名规范化

这里不要一上来做很重的 NLP 清洗。
先做“对后续检索有帮助、但不破坏原文结构”的轻量标准化。

---

## 4.4 Canonicalization 设计

这是模块 1 里最重要的一步，也是后面 dedup 的前置。

建议 canonical key 采用 **多字段联合**，不要只看标题：

```text
canonical_key =
  normalized_title
  + first_author
  + year
  + (doi / arxiv_id / venue as bonus signals)
```

### 合并规则建议

优先级大致可以这么设：

1. DOI 完全一致 → 高置信度同论文
2. arXiv id 一致 → 高置信度同论文
3. normalized title 高相似 + first author 一致 + year 接近 → 候选同论文
4. 同标题但 venue / year 差异明显 → 视为版本关系，不直接覆盖

### 为什么这一步不能后置

因为 paper-level retrieval 之后你就要做 dedup 和 rerank。
如果这里不先把“身份”梳理好，后面你拿到的 candidate papers 只是碎片化 document list，而不是论文集合。

---

## 5. 推荐工程结构

```text
src/corpus/ingest/
  pipeline.py
  loaders/
    local_folder_loader.py
    uploaded_pdf_loader.py
    online_source_loader.py
  parsers/
    pdf_parser.py
    metadata_extractor.py
  normalizers/
    text_normalizer.py
    metadata_normalizer.py
  canonicalize.py
```

### 每层职责

- `loaders/`：只负责拿原始输入
- `parsers/`：只负责文本解析和原始元数据提取
- `normalizers/`：只负责清洗和统一格式
- `canonicalize.py`：只负责论文身份归并
- `pipeline.py`：把上面几步串起来

这样后面调试时非常清楚：
到底是 loader 问题、parser 问题、normalizer 问题，还是 canonicalize 问题。

---

## 6. 模块 1 的流图

```text
Raw Sources
  ├─ local folder
  ├─ uploaded PDF
  └─ online source
        ↓
Source Loader
        ↓
Parser
  ├─ extract text
  ├─ extract metadata
  └─ parse quality
        ↓
Normalizer
  ├─ text cleanup
  ├─ metadata cleanup
  └─ source/version tagging
        ↓
Canonicalizer
  ├─ build canonical key
  ├─ merge same-paper sources
  └─ preserve version relations
        ↓
Standardized Document
        ↓
ready for chunk / index
```

---

## 7. 设计参考

### 论文参考

我建议这个模块的理论参考主要用两篇 survey：

1. **Gao et al.,**  ***Retrieval-Augmented Generation for Large Language Models: A Survey***
   这篇把 RAG 分成 Naive / Advanced / Modular，并系统讨论 retrieval pipeline 的前置环节和模块化演进，适合用来说明为什么 ingest 和 preprocessing 不能被当成小事。([arXiv](https://arxiv.org/abs/2312.10997?utm_source=chatgpt.com "Retrieval-Augmented Generation for Large Language Models: A Survey"))
2. **Fan et al.,**  ***A Survey on RAG Meeting LLMs***
   这篇更适合你现在这个 research workflow 语境，因为它强调 RAG 的外部知识可靠性和模块化结构，对“先把外部语料变成可靠 corpus”这个论点很合适。([arXiv](https://arxiv.org/abs/2405.06211?utm_source=chatgpt.com "A Survey on RAG Meeting LLMs: Towards Retrieval ..."))

### 博客 / 官方文档参考

1. **Haystack Docs – PreProcessors / DocumentPreprocessor / Pipelines**
   这些文档很适合做工程设计参考，因为它们把 indexing pipeline 明确拆成 preprocess、split、write to document store。([Haystack Documentation](https://docs.haystack.deepset.ai/docs/preprocessors?utm_source=chatgpt.com "PreProcessors"))
2. **Haystack blog / tutorial on indexing pipelines**
   它把 indexing pipeline 和 query pipeline 分开讲，这和你现在把 Phase 2 拆成 ingest、index、search 是一致的。([Haystack](https://haystack.deepset.ai/blog/deepset-studio-and-nvidia-nims?utm_source=chatgpt.com "Design Haystack AI Applications Visually in deepset Studio ..."))

---

## 8. 这个模块最容易踩的坑

### 坑 1：把 ingest 当成“文件上传”

错误。
真正的 ingest 是 **来源统一 + 元数据抽取 + 文本标准化 + canonicalization**。

### 坑 2：把 canonicalization 放到 retrieval 后再做

太晚了。
这样 candidate papers 还是文档视角，不是论文视角。

### 坑 3：只保存 raw text，不保存 source/version

后面 reviewer 做 citation reachability 时会很难受。

### 坑 4：过度清洗文本

把 section 边界、表格语义、作者信息清掉了，后面 chunking 和 evidence extraction 会受影响。

---

## 9. 这一模块做完后的交付物

模块 1 做完，至少要能稳定产出这些东西：

- `Document`
- `SourceRef`
- `canonical_id`
- `parse_quality_score`
- `warnings`
- `ingest_status`

以及一个统一入口：

- `POST /corpus/ingest`