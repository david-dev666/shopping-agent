"""DEMO_MODE 的内置样例数据。

来源：一次真实采集的冻结快照（`app/demo/*.json`），仅用于「无数据源时开箱预览」。
所有响应显式带 `demo=True`，由前端标注，绝不混入真实采集 / 决策链路。
"""

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).with_name("demo")


@lru_cache
def _load(name: str) -> dict:
    return json.loads((_DIR / name).read_text(encoding="utf-8"))


def demo_query_response() -> dict:
    """直接比价模式的样例响应。"""
    return {**_load("query.json"), "cached": False, "demo": True}


def demo_chat_response() -> dict:
    """Agent 决策模式的样例响应（含 trace）。"""
    return {**_load("chat.json"), "demo": True}


def demo_rank_response() -> dict:
    """综合排序的样例响应。"""
    chat = _load("chat.json")
    return {
        "items": chat["rank_items"],
        "summary": (chat.get("decision") or {}).get("reason", ""),
        "demo": True,
    }


def demo_refine_response(filters: dict | None = None) -> dict:
    """DEMO 模式下的重排：对样例报价**确定性应用筛选**，不调用 LLM。

    保持与真实链路同样的语义（筛选 → 重排），只是用既有的排序作为打分，
    并在 decision / recommendation 里显式标注这是演示数据。
    """
    from datetime import UTC, datetime

    from app.matching.filter import apply_filters
    from app.matching.specs import group_specs
    from app.models.filters import FilterSpec
    from app.models.offers import RawOffer

    chat = _load("chat.json")
    offers = [RawOffer.model_validate(o) for o in chat["offers"]]
    kept = apply_filters(offers, FilterSpec.model_validate(filters or {}))
    keep_ids = {id(o) for o in kept}

    picked = [
        it
        for it in chat["rank_items"]
        if 0 <= it["index"] < len(offers) and id(offers[it["index"]]) in keep_ids
    ]
    kept_offers = [offers[it["index"]] for it in picked]
    rank_items = [
        {"index": i, "score": it["score"], "reason": it["reason"]}
        for i, it in enumerate(picked)
    ]
    spec_groups = group_specs(kept_offers) if kept_offers else {}

    if kept_offers:
        prices = [o.price for o in kept_offers]
        top = kept_offers[0]
        recommendation = (
            f"（演示数据）已按筛选保留 {len(kept_offers)} 条，综合首选 {top.platform} "
            f"¥{top.price:.2f}；到手价 ¥{min(prices):.2f} ~ ¥{max(prices):.2f}"
        )
    else:
        recommendation = "（演示数据）当前筛选条件下没有报价，请放宽筛选条件"

    return {
        "trace_id": chat.get("trace_id", ""),
        "query": chat.get("query", ""),
        "intent": chat.get("intent", {}),
        "offers": [o.model_dump(mode="json") for o in kept_offers],
        "filter_stats": chat.get("filter_stats", {}),
        "errors": {},
        "decision": {
            "worth": (chat.get("decision") or {}).get("worth"),
            "confidence": (chat.get("decision") or {}).get("confidence"),
            "reason": "演示数据：按筛选条件确定性缩小候选集，未调用 LLM 重新打分",
        },
        "recommendation": recommendation,
        "rank_items": rank_items,
        "top_pick": kept_offers[0].model_dump(mode="json") if kept_offers else None,
        "specs": {name: [o.platform_id for o in g] for name, g in spec_groups.items()},
        "demo": True,
        "trace": [
            {
                "node": "filters",
                "input": f"{len(offers)} 条候选",
                "output": f"保留 {len(kept_offers)} 条",
                "detail": "DEMO_MODE：确定性筛选（未调用 LLM）",
                "elapsed_ms": 0,
                "ts": datetime.now(UTC).isoformat(),
            }
        ],
    }
