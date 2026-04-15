#!/usr/bin/env python3
"""Ingest SciFact benchmark corpus entries into PostgreSQL for RAG eval."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass

from src.eval.rag.scifact_corpus import ingest_scifact_corpus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 SciFact benchmark corpus 到 PostgreSQL")
    parser.add_argument(
        "--cases",
        default="regression",
        help="评测用例来源：smoke / regression / full / JSONL 路径",
    )
    parser.add_argument(
        "--data-split",
        default="train",
        choices=["train", "dev", "test", "validation"],
        help="SciFact 数据源 split（只用于下载/读取 corpus）",
    )
    parser.add_argument(
        "--allow-reindex",
        action="store_true",
        help="允许覆盖已存在 doc_id（默认跳过已存在文档）",
    )
    args = parser.parse_args()

    case_source: str | Path = args.cases
    case_path = Path(args.cases)
    if case_path.exists():
        case_source = case_path

    stats = ingest_scifact_corpus(
        case_source=case_source,
        data_split=args.data_split,
        skip_existing=not args.allow_reindex,
    )

    print(
        json.dumps(
            {
                "requested_docs": stats.requested_docs,
                "ingested_docs": stats.ingested_docs,
                "skipped_existing": stats.skipped_existing,
                "missing_docs": stats.missing_docs,
                "coarse_chunks": stats.coarse_chunks,
                "fine_chunks": stats.fine_chunks,
                "missing_doc_ids": stats.missing_doc_ids,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
