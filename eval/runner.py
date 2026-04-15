from __future__ import annotations

import json
import os
import time
from pathlib import Path

from eval.layers.hard_rules import run_layer1


def load_cases(path: str = "eval/cases.jsonl") -> list[dict]:
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def run_eval(
    cases_path: str = "eval/cases.jsonl",
    layer: int = 1,
    out_dir: str = "eval/runs",
) -> dict:
    """Run evaluation. Layer 1 = hard rules only (no LLM needed)."""
    cases = load_cases(cases_path)
    results = []

    for case in cases:
        case_id = case["id"]
        print(f"  [{case_id}] ", end="", flush=True)

        start = time.time()
        try:
            from src.agent.report import generate_literature_report

            if case["type"] == "pdf":
                report_md = generate_literature_report(
                    raw_text_content=case.get("pdf_text", "")
                )
            elif case["type"] == "sequential":
                parts = []
                for inp in case.get("inputs", []):
                    part = generate_literature_report(arxiv_url_or_id=inp)
                    parts.append(part)
                report_md = "\n\n---\n\n".join(parts)
            else:
                report_md = generate_literature_report(
                    arxiv_url_or_id=case.get("input", "")
                )

            duration = time.time() - start

            if layer >= 1:
                # TODO: pass tokens_used into run_layer1 cost_guard when generate_literature_report
                # returns full graph state (currently only markdown; token tracking unavailable here).
                l1 = run_layer1(report_md, case)
                result = {
                    "id": case_id,
                    "type": case["type"],
                    "layer1": l1,
                    "duration": round(duration, 2),
                    "report_snippet": report_md[:300],
                }

            passed = l1["pass"]
            print(f"{'PASS' if passed else 'FAIL'} ({duration:.1f}s)")
            results.append(result)

        except Exception as e:
            duration = time.time() - start
            print(f"ERROR ({duration:.1f}s): {e}")
            results.append(
                {
                    "id": case_id,
                    "type": case["type"],
                    "error": str(e),
                    "duration": round(duration, 2),
                }
            )

    total = len(results)
    passed = sum(1 for r in results if r.get("layer1", {}).get("pass", False))
    summary = {"total": total, "passed": passed, "failed": total - passed}

    output = {"summary": summary, "results": results}

    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(out_dir, f"run-{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nResults: {passed}/{total} passed → {out_path}")
    return output


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="eval/cases.jsonl")
    parser.add_argument("--layer", type=int, default=1)
    parser.add_argument("--out-dir", default="eval/runs")
    args = parser.parse_args()
    run_eval(args.cases, args.layer, args.out_dir)
