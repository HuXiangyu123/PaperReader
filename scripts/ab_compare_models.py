from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Ensure "src" imports work when running as `python scripts/...`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.agent.report import generate_literature_report


@dataclass
class RunMetrics:
    model: str
    elapsed_s: float
    report_chars: int
    report_lines: int
    heading_count: int
    citation_url_count: int
    error_like: bool


def _collect_metrics(model: str, report: str, elapsed_s: float) -> RunMetrics:
    lines = report.splitlines()
    heading_count = sum(1 for line in lines if line.strip().startswith("## "))
    citation_url_count = len(re.findall(r"https?://", report))
    error_like = report.startswith("Error")
    return RunMetrics(
        model=model,
        elapsed_s=elapsed_s,
        report_chars=len(report),
        report_lines=len(lines),
        heading_count=heading_count,
        citation_url_count=citation_url_count,
        error_like=error_like,
    )


def _run_once(model: str, paper_input: str) -> tuple[RunMetrics, str]:
    old_model = os.getenv("DEEPSEEK_MODEL")
    os.environ["DEEPSEEK_MODEL"] = model
    try:
        started = time.perf_counter()
        report = generate_literature_report(arxiv_url_or_id=paper_input)
        elapsed = time.perf_counter() - started
        return _collect_metrics(model, report, elapsed), report
    finally:
        if old_model is None:
            os.environ.pop("DEEPSEEK_MODEL", None)
        else:
            os.environ["DEEPSEEK_MODEL"] = old_model


def main() -> None:
    parser = argparse.ArgumentParser(description="A/B compare DeepSeek model outputs for report pipeline.")
    parser.add_argument(
        "--input",
        default="1706.03762",
        help="arXiv ID/URL or raw text input passed to generate_literature_report",
    )
    parser.add_argument("--model-a", default="deepseek-chat", help="Model name A")
    parser.add_argument("--model-b", default="deepseek-reasoner", help="Model name B")
    parser.add_argument(
        "--save-dir",
        default="output/ab_compare",
        help="Directory to save raw markdown outputs",
    )
    args = parser.parse_args()

    load_dotenv()
    os.makedirs(args.save_dir, exist_ok=True)

    m_a, report_a = _run_once(args.model_a, args.input)
    m_b, report_b = _run_once(args.model_b, args.input)

    path_a = os.path.join(args.save_dir, f"{args.model_a.replace('/', '_')}.md")
    path_b = os.path.join(args.save_dir, f"{args.model_b.replace('/', '_')}.md")
    with open(path_a, "w", encoding="utf-8") as f:
        f.write(report_a)
    with open(path_b, "w", encoding="utf-8") as f:
        f.write(report_b)

    print("\nA/B Compare Summary")
    print("-" * 72)
    print(f"{'metric':<22} {'model-a':<24} {'model-b':<24}")
    print("-" * 72)
    print(f"{'model':<22} {m_a.model:<24} {m_b.model:<24}")
    print(f"{'elapsed_s':<22} {m_a.elapsed_s:<24.2f} {m_b.elapsed_s:<24.2f}")
    print(f"{'report_chars':<22} {m_a.report_chars:<24} {m_b.report_chars:<24}")
    print(f"{'report_lines':<22} {m_a.report_lines:<24} {m_b.report_lines:<24}")
    print(f"{'heading_count':<22} {m_a.heading_count:<24} {m_b.heading_count:<24}")
    print(f"{'citation_url_count':<22} {m_a.citation_url_count:<24} {m_b.citation_url_count:<24}")
    print(f"{'error_like':<22} {str(m_a.error_like):<24} {str(m_b.error_like):<24}")
    print("-" * 72)
    print(f"saved: {path_a}")
    print(f"saved: {path_b}")


if __name__ == "__main__":
    main()
