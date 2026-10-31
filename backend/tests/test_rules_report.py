import pytest

from eval.rules import evaluate


def test_unjudged_label_is_excluded_without_hiding_other_label_errors():
    case = {"query": "小米手环9 NFC版", "title": "小米手环9Pro 表带",
            "expect": [], "unjudged": ["model_mismatch"]}
    report = evaluate([case])
    assert report["label_coverage"] == 0.8
    assert report["fully_judged_cases"] == 0
    assert report["exact_match_rate"] is None
    assert report["per_rule"]["accessory"]["fp"] == 1
    assert all("model_mismatch" not in error["got"] for error in report["errors"])


def test_duplicate_and_conflicting_annotations_are_rejected():
    case = {"query": "小米手环9", "title": "小米手环9", "expect": []}
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate([case, case])
    with pytest.raises(ValueError, match="overlapping"):
        evaluate([{**case, "expect": ["rival"], "unjudged": ["rival"]}])


def test_empty_evaluation_does_not_claim_perfect_coverage():
    report = evaluate([])
    assert report["label_coverage"] is None
    assert report["exact_match_rate"] is None


def test_frozen_real_title_labels_match_manifest_and_do_not_overlap_development_set():
    import hashlib
    import json
    from pathlib import Path

    from eval.rules import load_cases

    dataset = Path(__file__).resolve().parents[1] / "eval/live_titles_20261031.jsonl"
    manifest = json.loads(dataset.with_suffix(".manifest.json").read_text())
    assert hashlib.sha256(dataset.read_bytes()).hexdigest() == manifest["dataset_sha256"]
    cases = load_cases(dataset)
    assert len(cases) == manifest["n_cases"] == 141
    old = {(row["query"], row["title"]) for row in load_cases()}
    assert not old.intersection((row["query"], row["title"]) for row in cases)
