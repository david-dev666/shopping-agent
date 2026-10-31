"""Score decisions against frozen, case-authored acceptable candidate IDs."""

from collections import Counter


def summarize(rows):
    selected = [r for r in rows if r.get("selected") is not None]
    available = [r for r in rows if r["acceptable_ids"]]
    unavailable = [r for r in rows if not r["acceptable_ids"]]
    correct = sum(r["selected"] in r["acceptable_ids"] for r in selected)
    return {
        "cases": len(rows), "selected": len(selected),
        "completed_cases": sum("error" not in r for r in rows),
        "selection_coverage": len(selected) / len(rows) if rows else None,
        "selected_suitable_rate": correct / len(selected) if selected else None,
        "wrong_selections": len(selected) - correct,
        "over_budget_selections": sum(bool(r.get("over_budget")) for r in selected),
        "available_cases": len(available),
        "available_case_success_rate": sum(
            r.get("selected") in r["acceptable_ids"] for r in available
        ) / len(available) if available else None,
        "must_abstain_cases": len(unavailable),
        "correct_abstentions": sum(
            r.get("selected") is None and "error" not in r for r in unavailable
        ),
        "engines": dict(Counter(r.get("actual_engine", "unknown") for r in rows)),
        "errors": sum("error" in r for r in rows),
    }
