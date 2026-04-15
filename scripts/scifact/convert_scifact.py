#!/usr/bin/env python3
"""
SciFact 数据集转换为 RagEvalCase 格式。

用法：
    python -m scripts.scifact.convert_scifact --split dev --max 50 --output tests/eval/cases/scifact_dev.jsonl

数据来源：
    SciFact (EMNLP 2020) — https://allenai.org/data/scifact
    官方 HuggingFace: allenai/scifact

映射关系：
    RagEvalCase.query      ← SciFact.claim
    RagEvalCase.gold_papers ← SciFact.cited_doc_ids（仅取 evidence 中有的 doc）
    RagEvalCase.gold_evidence ← SciFact.evidence[doc_id].sentences → 转为文本片段
    RagEvalCase.gold_claims  ← SciFact.evidence[doc_id].label → SUPPORT/CONTRADICT
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# SciFact 支持的 claim label → 我们的 support_type 映射
LABEL_TO_SUPPORT_TYPE = {
    "SUPPORT": "claim_support",
    "CONTRADICT": "limitation",  # CONTRADICT 视为 limitation
}

# 每个 evidence doc 中最多取几个句子作为 gold evidence
MAX_SENTENCES_PER_DOC = 3


def load_scifact_data(split: str = "dev") -> tuple[list[dict], dict]:
    """
    从 SciFact 官方 S3 加载数据。

    数据源：https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz
    数据集：SciFact (EMNLP 2020) — https://allenai.org/data/scifact

    Args:
        split: "train" / "dev" / "test"

    Returns:
        (claims, corpus_dict)
        - claims: claims 数据列表
        - corpus_dict: doc_id → corpus entry 的字典
    """
    import urllib.request
    import tarfile
    import io
    import tempfile
    import os

    split_file_map = {
        "train": "claims_train.jsonl",
        "dev": "claims_dev.jsonl",
        "test": "claims_test.jsonl",
        "validation": "claims_dev.jsonl",  # HuggingFace 用 validation 作为 dev 别名
    }
    claims_file = split_file_map.get(split, f"claims_{split}.jsonl")
    corpus_file = "corpus.jsonl"

    # 提取路径：data/corpus.jsonl / data/claims_*.jsonl
    cache_dir = Path(tempfile.gettempdir()) / "scifact_data"
    data_dir = cache_dir / "data"
    corpus_cache = data_dir / corpus_file
    claims_cache = data_dir / claims_file

    # 优先从缓存加载
    if corpus_cache.exists() and claims_cache.exists():
        logger.info(f"从缓存加载：{cache_dir}")
    else:
        logger.info("正在下载 SciFact 数据集...")
        url = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                tar_data = r.read()
        except Exception as e:
            logger.error(f"下载失败：{e}")
            raise RuntimeError(
                f"无法下载 SciFact 数据：{e}。"
                f"请手动下载：{url}"
            ) from e

        cache_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(tar_data)) as tar:
            members = tar.getnames()
            logger.info(f"解压文件：{members}")
            for member in members:
                if member.endswith(corpus_file):
                    tar.extract(member, cache_dir)
                    logger.info(f"已提取：corpus.jsonl")
                elif member.endswith(claims_file):
                    tar.extract(member, cache_dir)
                    logger.info(f"已提取：{claims_file}")

    # 读取 corpus
    corpus_dict = {}
    with open(corpus_cache, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            corpus_dict[str(doc["doc_id"])] = doc

    # 读取 claims
    claims = []
    with open(claims_cache, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            claims.append(json.loads(line))

    logger.info(f"加载完成：{len(claims)} claims, {len(corpus_dict)} corpus docs")
    return claims, corpus_dict


def extract_sentence_text(corpus_entry: dict, sentence_indices: list[int]) -> str:
    """
    从 corpus entry 中提取指定 sentence indices 的文本。

    Args:
        corpus_entry: corpus 中的单个文档
        sentence_indices: 句子索引列表

    Returns:
        拼接后的文本
    """
    abstract = corpus_entry.get("abstract", [])
    if not abstract:
        return ""

    sentences = []
    for idx in sentence_indices:
        if 0 <= idx < len(abstract):
            sentences.append(abstract[idx])
    return " ".join(sentences)


def scifact_claim_to_rag_case(
    claim_entry: dict,
    corpus_dict: dict,
    case_id_prefix: str = "scifact",
) -> dict | None:
    """
    将单条 SciFact claim 转换为 RagEvalCase dict。

    Args:
        claim_entry: SciFact claim 条目
        corpus_dict: doc_id → corpus entry
        case_id_prefix: case_id 前缀

    Returns:
        符合 RagEvalCase schema 的 dict，失败时返回 None
    """
    claim_id = claim_entry.get("id")
    claim_text = claim_entry.get("claim", "")
    evidence = claim_entry.get("evidence", {})
    cited_doc_ids = claim_entry.get("cited_doc_ids", [])

    if not claim_text:
        return None

    # 构建 gold_papers
    gold_papers = []
    for doc_id in cited_doc_ids:
        doc_id_str = str(doc_id)
        corpus_entry = corpus_dict.get(doc_id_str)
        if corpus_entry:
            gold_papers.append({
                "title": corpus_entry.get("title", ""),
                "canonical_id": doc_id_str,
                "arxiv_id": "",  # SciFact 用 S2ORC ID，不是 arXiv ID
                "expected_rank": 0,
            })

    # 构建 gold_evidence
    gold_evidence = []
    for doc_id_str, label_info_list in evidence.items():
        corpus_entry = corpus_dict.get(doc_id_str)
        if not corpus_entry:
            continue

        title = corpus_entry.get("title", "")

        for info in label_info_list:
            sentences = info.get("sentences", [])
            label = info.get("label", "")

            if not sentences:
                continue

            # 限制每个 doc 的 evidence 数量
            sentences = sentences[:MAX_SENTENCES_PER_DOC]

            # 提取文本片段作为 text_hint
            text_hint = extract_sentence_text(corpus_entry, sentences)

            # 推断 section（基于句子在 abstract 中的位置）
            abstract = corpus_entry.get("abstract", [])
            if abstract:
                first_sent_idx = sentences[0] if sentences else 0
                if first_sent_idx == 0:
                    section = "Abstract"
                elif first_sent_idx <= 2:
                    section = "Introduction"
                elif first_sent_idx <= len(abstract) * 0.5:
                    section = "Method"
                elif first_sent_idx <= len(abstract) * 0.8:
                    section = "Results"
                else:
                    section = "Discussion"
            else:
                section = "Abstract"

            # 推断 support_type
            support_type = LABEL_TO_SUPPORT_TYPE.get(label, "claim_support")

            gold_evidence.append({
                "paper_title": title,
                "expected_section": section,
                "text_hint": text_hint[:200] if text_hint else "",  # 截断避免过大
                "sub_question_id": f"sq-label-{label.lower()}",
                "expected_support_type": support_type,
            })

    # 构建 gold_claims
    gold_claims = []
    for doc_id_str, label_info_list in evidence.items():
        for info in label_info_list:
            label = info.get("label", "")
            sentences = info.get("sentences", [])
            if sentences and label:
                gold_claims.append({
                    "claim_text": claim_text[:100],
                    "supported_by_paper": doc_id_str,
                    "supported_by_evidence_section": LABEL_TO_SUPPORT_TYPE.get(label, "claim_support"),
                })

    if not gold_evidence:
        logger.debug(f"Claim {claim_id} 无 evidence 标注，跳过")
        return None

    return {
        "case_id": f"{case_id_prefix}-{claim_id}",
        "query": claim_text,
        "sub_questions": [],
        "gold_papers": gold_papers,
        "gold_evidence": gold_evidence,
        "gold_claims": gold_claims,
        "recall_top_k": 100,
        "rerank_top_m": 50,
        "evidence_top_k": 50,
        "source": "scifact",
        "notes": f"SciFact claim ID={claim_id}，label={list(evidence.values())}",
    }


def convert_scifact(
    split: str = "dev",
    max_cases: int | None = None,
    seed: int = 42,
    output: Path | None = None,
) -> list[dict]:
    """
    转换 SciFact 数据集。

    Args:
        split: 数据集划分（train/dev/test）
        max_cases: 最大转换数量（None=全部）
        seed: 随机种子（用于 shuffle）
        output: 输出文件路径（JSONL）

    Returns:
        转换后的 RagEvalCase dict 列表
    """
    claims, corpus_dict = load_scifact_data(split)

    # Shuffle
    random.seed(seed)
    random.shuffle(claims)

    if max_cases is not None:
        claims = claims[:max_cases]

    logger.info(f"正在转换 {len(claims)} 条 claims...")

    cases = []
    skipped = 0
    for claim in claims:
        case = scifact_claim_to_rag_case(claim, corpus_dict)
        if case:
            cases.append(case)
        else:
            skipped += 1

    logger.info(f"转换完成：{len(cases)} cases，{skipped} 条跳过")

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            for case in cases:
                f.write(json.dumps(case, ensure_ascii=False) + "\n")
        logger.info(f"已保存至：{output}")

    return cases


def main():
    parser = argparse.ArgumentParser(description="SciFact → RagEvalCase 转换工具")
    parser.add_argument(
        "--split", "-s",
        choices=["train", "dev", "test"],
        default="dev",
        help="数据集划分",
    )
    parser.add_argument(
        "--max", "-m",
        type=int,
        default=None,
        help="最大转换数量",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="输出 JSONL 路径",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子",
    )
    args = parser.parse_args()

    if args.output is None:
        default_dir = Path("tests/eval/cases")
        default_dir.mkdir(parents=True, exist_ok=True)
        args.output = default_dir / f"scifact_{args.split}.jsonl"

    convert_scifact(
        split=args.split,
        max_cases=args.max,
        seed=args.seed,
        output=args.output,
    )


if __name__ == "__main__":
    main()
