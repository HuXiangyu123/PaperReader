# SciFact 评测用例集

## 数据来源

[SciFact (EMNLP 2020)](https://allenai.org/data/scifact) — 1,809 条专家撰写的科学声明，
每条声明配有 S2ORC 论文中的证据段落，标注为 SUPPORT 或 CONTRADICT。

## 文件说明

| 文件 | 数量 | 说明 |
|------|------|------|
| `phase2_smoke.jsonl` | 5 | 冒烟测试，覆盖 RAG/LLM/MARL/VLM/LoRA 场景 |
| `scifact_regression.jsonl` | 30 | 真实 SciFact claims，用于回归测试 |
| `scifact_full.jsonl` | 待生成 | 完整 SciFact dev 集（188 条有标注） |

## SciFact → RagEvalCase 映射

| RagEvalCase 字段 | SciFact 字段 |
|-----------------|-------------|
| `query` | `claim` |
| `gold_papers[].canonical_id` | `cited_doc_ids` |
| `gold_evidence[].text_hint` | `evidence[doc_id].sentences` → 句子拼接 |
| `gold_evidence[].expected_support_type` | `SUPPORT → claim_support`, `CONTRADICT → limitation` |

## 生成新用例

```bash
# 从 SciFact train 集生成 30 条（已有真实数据）
python -m scripts.scifact.convert_scifact --split train --max 30 \
    --output tests/eval/cases/scifact_regression.jsonl

# 从 SciFact dev 集生成完整评测集
python -m scripts.scifact.convert_scifact --split dev \
    --output tests/eval/cases/scifact_full.jsonl
```

## 数据结构

每条用例为 JSONL 格式（每行一个 JSON）：
- `case_id`: 唯一标识（scifact-{id}）
- `query`: 科学声明
- `gold_papers`: 相关论文列表
- `gold_evidence`: 证据块（包含 section、text_hint、support_type）
- `gold_claims`: claim 验证信息

## 局限

- `canonical_id` 为 S2ORC doc_id（非 arXiv ID），需与 corpus 索引对齐
- Section 信息为推断值（基于句子在 abstract 中的位置）
- 无 claim 级别的 sub_questions（需要从 claim 文本中抽取）
