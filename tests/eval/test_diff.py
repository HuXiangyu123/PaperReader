import json
import os
import tempfile

from eval.diff import diff_runs, diff_to_markdown


def _write_run(results, path):
    with open(path, "w") as f:
        json.dump({"summary": {}, "results": results}, f)


def test_diff_no_regressions():
    with tempfile.TemporaryDirectory() as td:
        b_path = os.path.join(td, "baseline.json")
        c_path = os.path.join(td, "current.json")
        _write_run(
            [{"id": "a", "layer1": {"pass": True}}, {"id": "b", "layer1": {"pass": True}}],
            b_path,
        )
        _write_run(
            [{"id": "a", "layer1": {"pass": True}}, {"id": "b", "layer1": {"pass": True}}],
            c_path,
        )
        diff = diff_runs(b_path, c_path)
    assert diff["regression_count"] == 0


def test_diff_regression():
    with tempfile.TemporaryDirectory() as td:
        b_path = os.path.join(td, "baseline.json")
        c_path = os.path.join(td, "current.json")
        _write_run([{"id": "a", "layer1": {"pass": True}}], b_path)
        _write_run([{"id": "a", "layer1": {"pass": False}}], c_path)
        diff = diff_runs(b_path, c_path)
    assert diff["regression_count"] == 1


def test_diff_improvement():
    with tempfile.TemporaryDirectory() as td:
        b_path = os.path.join(td, "baseline.json")
        c_path = os.path.join(td, "current.json")
        _write_run([{"id": "a", "layer1": {"pass": False}}], b_path)
        _write_run([{"id": "a", "layer1": {"pass": True}}], c_path)
        diff = diff_runs(b_path, c_path)
    assert len(diff["improvements"]) == 1
    assert diff["regression_count"] == 0


def test_diff_to_markdown():
    diff = {
        "baseline": "a.json",
        "current": "b.json",
        "regressions": [],
        "improvements": ["x"],
        "unchanged": ["y"],
        "new_cases": [],
        "regression_count": 0,
    }
    md = diff_to_markdown(diff)
    assert "No Regressions" in md
    assert "Improvements" in md
