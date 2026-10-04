"""评测集守卫：规则层指标不得回退。"""

from eval.rules import evaluate


def test_rules_eval_meets_thresholds() -> None:
    m = evaluate()
    assert m["n_cases"] >= 30
    assert m["micro"]["f1"] >= 0.90
    for rule, s in m["per_rule"].items():
        assert s["precision"] >= 0.75, f"{rule} precision 回退"
        assert s["recall"] >= 0.75, f"{rule} recall 回退"
