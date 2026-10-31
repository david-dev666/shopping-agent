"""Evaluate decision/refinement using fixed candidates, without platform collection."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

from eval.decisions import summarize


class Adversarial:
    def invoke(self, prompt):
        from types import SimpleNamespace

        return SimpleNamespace(content=json.dumps({
            "worth": "buy", "confidence": 100, "reason": "优先低价候选",
            "items": [{"index": 0, "score": 100, "reason": "首选"},
                      {"index": 1, "score": 90, "reason": "备选"}],
        }))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("eval/decision_cases.jsonl"))
    parser.add_argument("--engine", choices=("rules", "llm", "adversarial"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    cases = [json.loads(line) for line in args.dataset.read_text().splitlines() if line]
    ids = set()
    for case in cases:
        candidates = [o["platform_id"] for o in case["offers"]]
        if (case["id"] in ids or len(set(candidates)) != len(candidates)
                or not set(case["acceptable_ids"]) <= set(candidates)):
            parser.error("invalid case IDs or acceptable candidates")
        ids.add(case["id"])
    from fastapi.encoders import jsonable_encoder

    from app.agents import graph
    from app.matching.filter import filter_offers
    from app.models.offers import RawOffer
    from app.storage.db import init_db

    init_db()
    if args.engine == "rules":
        graph._llm = lambda: None
    elif args.engine == "adversarial":
        graph._llm = lambda: Adversarial()
    rows = []
    for case in cases:
        row = {"id": case["id"], "group": case["group"],
               "acceptable_ids": case["acceptable_ids"], "selected": None}
        started = perf_counter()
        try:
            offers = [RawOffer.model_validate(o) for o in case["offers"]]
            offers, _, _ = filter_offers(offers, case["query"])
            result = jsonable_encoder(graph.run_refine(case["query"], offers))
            top = result.get("top_pick")
            row.update(
                selected=top["platform_id"] if top else None,
                actual_engine=("injected_output" if args.engine == "adversarial"
                               else result["decision"].get("engine", "unknown")),
                over_budget=bool(top and top["price"] > case["budget"]),
                result=result,
            )
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["elapsed_ms"] = round((perf_counter() - started) * 1000, 2)
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "result"}, ensure_ascii=False),
              flush=True)
    report = {
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "requested_engine": args.engine,
        "scope": "自建约束场景；验证候选到决策/推荐链路，不测采集、意图解析或实际SKU。",
        "summary": summarize(rows),
        "by_group": {g: summarize([r for r in rows if r["group"] == g])
                     for g in sorted({r["group"] for r in rows})},
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
