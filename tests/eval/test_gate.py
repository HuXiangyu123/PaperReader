from eval.gate import check_gate


def test_gate_all_pass():
    run = {
        "results": [
            {"id": "a", "layer1": {"pass": True}},
            {"id": "b", "layer1": {"pass": True}},
        ]
    }
    result = check_gate(run)
    assert result["pass"] is True


def test_gate_l1_fail():
    run = {
        "results": [
            {"id": "a", "layer1": {"pass": True}},
            {"id": "b", "layer1": {"pass": False}},
        ]
    }
    result = check_gate(run, thresholds={"l1_pass_rate": 0.9})
    assert result["pass"] is False


def test_gate_regression_fail():
    run = {"results": [{"id": "a", "layer1": {"pass": True}}]}
    diff = {"regression_count": 1}
    result = check_gate(run, diff=diff)
    assert result["pass"] is False


def test_gate_empty_results():
    result = check_gate({"results": []})
    assert result["pass"] is False


def test_gate_with_l2():
    run = {
        "results": [
            {"id": "a", "layer1": {"pass": True}, "layer2": {"pass": True}},
            {"id": "b", "layer1": {"pass": True}, "layer2": {"pass": False}},
        ]
    }
    result = check_gate(run, thresholds={"l1_pass_rate": 0.9, "l2_pass_rate": 0.9})
    assert result["pass"] is False
    assert result["checks"]["l2_pass_rate"]["rate"] == 0.5
