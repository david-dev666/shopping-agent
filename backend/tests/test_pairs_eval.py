"""Tool regressions use synthetic labels; dataset checks do not claim shopping accuracy."""

import json

import pytest
from pydantic import ValidationError

from eval.pairs import evaluate_pairs, validate_pairs
from scripts.eval_pairs import DATASET, predict


def rows():
    return [
        {
            "id": str(index),
            "query_id": "q1",
            "query": "预算300元买小米手环12 NFC版",
            "reference": {
                "platform": "jd",
                "platform_id": "ref",
                "title": "小米手环12 NFC版",
                "price": 199,
            },
            "candidate": {
                "platform": "taobao",
                "platform_id": str(index),
                "title": title,
                "price": 100,
            },
            "title_match": label,
            "suitable": label,
            "reviewer": "codex",
            "evidence": "合成工具测试",
        }
        for index, (title, label) in enumerate(
            [
                ("Xiaomi Band 12 NFC版", True),
                ("小米手环12 标准版", False),
                ("小米手环12", None),
            ]
        )
    ]


def test_ai_agreement_excludes_pending_labels_and_names_the_limit():
    report = evaluate_pairs(rows())
    assert report["independent_ground_truth"] is False
    assert report["title_labelled"] == 2 and report["title_pending"] == 1
    assert report["label_coverage"] == 2 / 3
    assert report["matching"] == {
        "tp": 1,
        "fp": 0,
        "fn": 0,
        "agreement": 1,
        "precision": 1,
        "recall": 1,
    }
    assert report["ranking"] is None


@pytest.mark.parametrize(
    "pick,rate,unknown,abstained",
    [
        ("0", 1, 0, 0),
        ("1", 0, 0, 0),
        ("2", None, 1, 0),
        (None, None, 0, 1),
    ],
)
def test_ranking_distinguishes_unknown_from_rejected_and_abstained(pick, rate, unknown, abstained):
    report = evaluate_pairs(rows(), {"q1": pick})["ranking"]
    assert report["top1_suitable_rate"] == rate
    assert report["unjudged_selected"] == unknown
    assert report["abstained"] == abstained


@pytest.mark.parametrize(
    "field,value",
    [
        ("title_match", "true"),
        ("reviewer", "human"),
        ("evidence", " "),
    ],
)
def test_unsupported_or_untraceable_labels_are_rejected(field, value):
    cases = rows()
    cases[0][field] = value
    with pytest.raises(ValidationError):
        validate_pairs(cases)


def test_duplicate_candidates_and_inconsistent_query_are_rejected():
    cases = rows()
    with pytest.raises(ValueError, match="重复"):
        validate_pairs(cases + cases[:1])
    cases[1]["candidate"]["platform_id"] = "0"
    with pytest.raises(ValueError, match="重复候选"):
        validate_pairs(cases)
    cases = rows()
    cases[1]["query"] = "改需求"
    with pytest.raises(ValueError, match="多个需求"):
        validate_pairs(cases)
    with pytest.raises(ValueError, match="不属于"):
        evaluate_pairs(rows(), {"q1": "unknown"})


def test_empty_titles_are_pending_and_all_pending_has_no_fake_rate():
    cases = rows()[:1]
    cases[0]["candidate"]["title"] = ""
    with pytest.raises(ValueError, match="待确认"):
        validate_pairs(cases)
    cases[0].update(title_match=None, suitable=None)
    report = evaluate_pairs(cases)
    assert report["matching"]["agreement"] is None
    assert report["matching"]["precision"] is None


def test_actual_pipeline_applies_tags_and_never_receives_ai_labels(monkeypatch):
    monkeypatch.setattr("app.agents.graph._llm", lambda: None)
    cases = rows()[:2]
    cases[1]["candidate"].update(title="小米手环12 NFC版 保护膜", price=50)
    picks, engines = predict(cases)
    assert picks == {"q1": "0"} and engines == {"rules": 1}
    cases[0]["suitable"] = False
    cases[0]["evidence"] = "修改评阅结论，不应改变系统输入"
    assert predict(cases)[0] == picks


def test_checked_in_ai_cases_have_explicit_evidence_and_pending_cases():
    cases = [json.loads(line) for line in DATASET.read_text().splitlines()]
    pairs = validate_pairs(cases)
    assert len(pairs) == 20
    assert all(p.reviewer == "codex" and p.evidence for p in pairs)
    assert any(p.title_match is None for p in pairs)
    assert all(p.candidate.url and p.reference.url for p in pairs)
