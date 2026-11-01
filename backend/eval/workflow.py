"""Score frozen workflow expectations without consulting production matching rules."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from app.models.offers import RawOffer, offer_key


def load_cases(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = set()
    actions = {"recommend", "confirm", "clarify", "abstain", "unavailable"}
    for row in rows:
        if row["id"] in ids:
            raise ValueError("duplicate case ID")
        ids.add(row["id"])
        keys = [offer_key(RawOffer.model_validate(o)) for o in row["offers"]]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate composite candidate ID")
        for expected in [row["expected"], *[s["expected"] for s in row["steps"]]]:
            if expected["action"] not in actions:
                raise ValueError("unknown expected action")
            if not set(expected["acceptable_keys"]) <= set(keys):
                raise ValueError("acceptable candidate outside fixture")
            if expected["action"] in {"recommend", "confirm"} and not expected["acceptable_keys"]:
                raise ValueError("selectable case needs acceptable candidates")
    return rows


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score_phase(expected: dict, result: dict, collection_calls: int) -> dict:
    top = result.get("top_pick")
    selected = offer_key(RawOffer.model_validate(top)) if top else None
    actual_questions = sorted(q["field"] for q in result.get("clarification_questions", []))
    errors = []
    budget = expected["budget"]
    if result.get("intent", {}).get("budget") != budget:
        errors.append("intent_budget")
    if collection_calls != 1:
        errors.append("recollected")
    if actual_questions != sorted(expected["questions"]):
        errors.append("clarification_fields")
    action = expected["action"]
    if action == "clarify":
        if result.get("status") != "awaiting_clarification" or selected is not None:
            errors.append("clarification_action")
    else:
        if result.get("status") != "complete":
            errors.append("unexpected_wait")
        if action in {"recommend", "confirm"}:
            if selected not in expected["acceptable_keys"]:
                errors.append("top1")
            if action == "confirm" and result.get("decision", {}).get("worth") != "wait":
                errors.append("unverified_buy")
        elif selected is not None:
            errors.append("should_not_select")
        if action == "unavailable" and not result.get("errors"):
            errors.append("missing_source_failure")
    over_budget = bool(top and budget is not None and top["price"] > budget)
    if over_budget:
        errors.append("over_budget")
    return {
        "passed": not errors,
        "failures": errors,
        "expected_action": action,
        "selected": selected,
        "acceptable_keys": expected["acceptable_keys"],
        "intent_budget_correct": "intent_budget" not in errors,
        "expected_questions": expected["questions"],
        "actual_questions": actual_questions,
        "over_budget": over_budget,
        "collection_calls": collection_calls,
        "engine": result.get("decision", {}).get("engine"),
        "source_unavailable": bool(result.get("errors") and not result.get("offers")),
    }


def summarize(rows: list[dict]) -> dict:
    phases = [p for r in rows for p in r.get("phases", [])]
    selectable = [p for p in phases if p["expected_action"] in {"recommend", "confirm"}]
    selected = [p for p in selectable if p["selected"] is not None]
    abstain = [p for p in phases if p["expected_action"] == "abstain"]
    clarify = [p for p in phases if p["expected_action"] == "clarify"]
    raw = [p for p in phases if p.get("raw_available")]
    return {
        "case_runs": len(rows),
        "completed_case_runs": sum("error" not in r for r in rows),
        "passed_case_runs": sum(r.get("passed", False) for r in rows),
        "phases": len(phases),
        "passed_phases": sum(p["passed"] for p in phases),
        "intent_budget_correct": sum(p["intent_budget_correct"] for p in phases),
        "selection_opportunities": len(selectable),
        "selected": len(selected),
        "correct_selections": sum(p["selected"] in p["acceptable_keys"] for p in selected),
        "selection_coverage": len(selected) / len(selectable) if selectable else None,
        "over_budget_selections": sum(p["over_budget"] for p in phases),
        "must_abstain_phases": len(abstain),
        "correct_abstentions": sum(p["selected"] is None for p in abstain),
        "must_clarify_phases": len(clarify),
        "correct_clarification_fields": sum(
            sorted(p["actual_questions"]) == sorted(p["expected_questions"]) for p in clarify
        ),
        "unnecessary_clarifications": sum(
            bool(p["actual_questions"]) and not p["expected_questions"] for p in phases
        ),
        "source_unavailable_phases": sum(p["source_unavailable"] for p in phases),
        "decision_engines": dict(Counter(p["engine"] for p in phases)),
        "failures": dict(Counter(f for p in phases for f in p["failures"])),
        "raw_output_comparison": {
            "available_phases": len(raw),
            "unacceptable_raw_selections": sum(p["raw_unacceptable"] for p in raw),
            "over_budget_raw_selections": sum(p["raw_over_budget"] for p in raw),
            "corrected_by_pipeline": sum(
                p["raw_unacceptable"] and p["selected"] in p["acceptable_keys"] for p in raw
            ),
            "blocked_without_replacement": sum(
                p["raw_unacceptable"] and p["selected"] is None for p in raw
            ),
        },
    }
