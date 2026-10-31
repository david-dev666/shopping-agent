from eval.decisions import summarize


def test_abstaining_everywhere_does_not_claim_perfect_recommendations():
    report = summarize([{"acceptable_ids": ["good"], "selected": None},
                        {"acceptable_ids": [], "selected": None}])
    assert report["selected_suitable_rate"] is None
    assert report["available_case_success_rate"] == 0
    assert report["correct_abstentions"] == 1


def test_wrong_and_over_budget_choices_are_reported():
    report = summarize([{"acceptable_ids": ["good"], "selected": "bad", "over_budget": True}])
    assert report["wrong_selections"] == report["over_budget_selections"] == 1
    assert report["available_case_success_rate"] == 0


def test_execution_failure_is_not_a_correct_abstention():
    report = summarize([{"acceptable_ids": [], "selected": None, "error": "timeout"}])
    assert report["correct_abstentions"] == report["completed_cases"] == 0
    assert report["errors"] == 1


def test_rules_runner_persists_real_pipeline_results(tmp_path, monkeypatch):
    import json
    import sys
    from pathlib import Path

    from app.agents import graph
    from scripts import eval_decisions

    dataset = Path(__file__).resolve().parents[1] / "eval/decision_cases.jsonl"
    output = tmp_path / "report.json"
    monkeypatch.setattr(graph, "_llm", graph._llm)
    monkeypatch.setattr(sys, "argv", ["eval_decisions", "--engine", "rules",
                                    "--dataset", str(dataset), "--output", str(output)])
    eval_decisions.main()
    report = json.loads(output.read_text())
    assert report["summary"]["cases"] == 18
    assert report["summary"]["wrong_selections"] == 0
    assert report["summary"]["available_case_success_rate"] == 1
    assert report["summary"]["correct_abstentions"] == 3
