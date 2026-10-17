"""Small AI-assisted evaluation. Labels are authored by Codex, not by the matching rules."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from eval.pairs import evaluate_pairs, validate_pairs

DATASET = Path(__file__).resolve().parents[1] / "eval" / "ai_pairs.jsonl"


def predict(rows: list[dict]) -> tuple[dict, dict]:
    """Use the existing pipeline; labels and review notes are never sent to it."""
    from app.agents.graph import run_refine
    from app.matching.filter import filter_offers
    from app.models.offers import RawOffer, offer_key

    groups = defaultdict(list)
    for pair in validate_pairs(rows):
        groups[pair.query_id].append(pair)
    picks, engines = {}, defaultdict(int)
    for query_id, pairs in groups.items():
        candidates = [p.candidate.model_copy(deep=True, update={"tags": []}) for p in pairs]
        candidates, _, _ = filter_offers(candidates, pairs[0].query)
        result = run_refine(pairs[0].query, candidates)
        top = RawOffer.model_validate(result["top_pick"]) if result.get("top_pick") else None
        picks[query_id] = next(
            (p.id for p in pairs if top and offer_key(p.candidate) == offer_key(top)), None
        )
        engines[result["decision"].get("engine", "unknown")] += 1
    return picks, dict(engines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument(
        "--run", action="store_true", help="另外执行现有重排链路，可能调用配置的模型"
    )
    args = parser.parse_args()
    try:
        rows = [
            json.loads(line)
            for line in args.dataset.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        validate_pairs(rows)
        picks, engines = None, None
        if args.run:
            from app.storage.db import init_db

            init_db()
            picks, engines = predict(rows)
        report = evaluate_pairs(rows, picks)
        if engines is not None:
            report["decision_engines"] = engines
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, OSError) as error:
        parser.exit(1, f"评测未完成: {error}\n")


if __name__ == "__main__":
    main()
