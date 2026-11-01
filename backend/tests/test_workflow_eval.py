import json
from pathlib import Path

import pytest

from app.agents.graph import explicit_budget
from eval.workflow import load_cases, score_phase, summarize


@pytest.mark.parametrize(
    "query,expected",
    [
        ("最多200元买小米手环9", 200),
        ("预算不超过200元，买小米手环9", 200),
        ("最高预算为300元", 300),
        ("预算200到300元买手环", 300),
        ("预算3,000元", 3000),
        ("预算300元，但不超过250元", 250),
        ("200元以内买手环", 200),
        ("预算199.99元", 199.99),
        ("买小米手环9", None),
        ("买RTX4090", None),
    ],
)
def test_explicit_budget_expressions(query, expected):
    assert explicit_budget(query) == expected


def test_workflow_cases_have_frozen_labels_and_composite_keys():
    from eval.workflow import fingerprint

    path = Path(__file__).resolve().parents[1] / "eval/workflow_cases.jsonl"
    cases = load_cases(path)
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    assert manifest["sha256"] == fingerprint(path)
    assert len(cases) == manifest["cases"] == 25
    assert len({c["group"] for c in cases}) == 9
    assert manifest["independent_ground_truth"] is False


def test_always_abstaining_fails_selection_and_clarification():
    base = {"intent": {"budget": None}, "status": "complete"}
    selection = score_phase(
        {"action": "recommend", "acceptable_keys": ["jd:a"], "questions": [], "budget": None},
        base,
        1,
    )
    clarify = score_phase(
        {"action": "clarify", "acceptable_keys": [], "questions": ["version"], "budget": None},
        base,
        1,
    )
    assert not selection["passed"] and not clarify["passed"]
    assert summarize([{"phases": [selection, clarify]}])["selection_coverage"] == 0


def test_candidate_order_does_not_change_expected_keys_or_mutate_fixture():
    from fastapi.testclient import TestClient

    from app.main import app
    from scripts.eval_workflow import run_case

    path = Path(__file__).resolve().parents[1] / "eval/workflow_cases.jsonl"
    case = next(c for c in load_cases(path) if c["id"] == "cross-platform-id")
    original = json.dumps(case)
    with TestClient(app) as client:
        rows = [run_case(client, case, "adversarial", None, seed) for seed in range(3)]
    assert all(row["passed"] for row in rows)
    assert json.dumps(case) == original
    assert all(row["phases"][0]["selected"] == "taobao:1" for row in rows)


def test_raw_bad_choice_and_guarded_result_use_separate_denominators():
    from fastapi.testclient import TestClient

    from app.main import app
    from scripts.eval_workflow import run_case

    case = {
        "id": "bad-output",
        "group": "risk",
        "query": "预算200元买小米手环9 NFC版",
        "offers": [
            {"platform": "jd", "platform_id": "bad", "title": "小米手环8 NFC版", "price": 99},
            {"platform": "jd", "platform_id": "good", "title": "小米手环9 NFC版", "price": 199},
        ],
        "expected": {
            "action": "recommend",
            "acceptable_keys": ["jd:good"],
            "budget": 200,
            "questions": [],
        },
        "steps": [],
        "collection_errors": {},
    }
    with TestClient(app) as client:
        row = run_case(client, case, "adversarial", None, 0)
    comparison = summarize([row])["raw_output_comparison"]
    assert comparison["available_phases"] == comparison["unacceptable_raw_selections"] == 1
    assert comparison["corrected_by_pipeline"] == 1


def test_model_unconfigured_cannot_masquerade_as_llm_evaluation(monkeypatch):
    from app.agents import graph
    from scripts.eval_workflow import evaluate

    monkeypatch.setattr(graph, "_llm", lambda: None)
    path = Path(__file__).resolve().parents[1] / "eval/workflow_cases.jsonl"
    with pytest.raises(ValueError, match="configured model"):
        evaluate(path, "llm")


def test_all_workflow_contracts_with_controlled_model():
    from scripts.eval_workflow import evaluate

    path = Path(__file__).resolve().parents[1] / "eval/workflow_cases.jsonl"
    report = evaluate(path, "adversarial")
    assert report["summary"]["completed_case_runs"] == 25
    assert report["summary"]["passed_case_runs"] == 25
    assert report["summary"]["passed_phases"] == 33
    assert report["summary"]["over_budget_selections"] == 0
