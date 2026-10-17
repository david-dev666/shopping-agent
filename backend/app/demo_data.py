"""DEMO_MODE 的内置样例数据。

来源：一次真实采集的冻结快照（`app/demo/*.json`），仅用于「无数据源时开箱预览」。
所有响应显式带 `demo=True`，由前端标注，绝不混入真实采集 / 决策链路。
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).with_name("demo")


@lru_cache
def _load(name: str) -> dict:
    return json.loads((_DIR / name).read_text(encoding="utf-8"))


def _normalized(name: str) -> dict:
    """保留冻结报价，使用当前规则更新标签、分组和展示口径。"""
    from app.matching.filter import apply_tag_guard, filter_offers
    from app.matching.identity import evidence_allows_pick, evidence_priority
    from app.matching.specs import group_specs
    from app.models.offers import RawOffer, offer_key

    data = copy.deepcopy(_load(name))
    offers = [RawOffer.model_validate(o) for o in data["offers"]]
    for offer in offers:
        offer.tags = []
    offers, stats, _ = filter_offers(offers, data["query"])
    data.update(
        offers=[o.model_dump(mode="json") for o in offers],
        filter_stats=stats,
        demo=True,
        origin="sample",
        specs={spec: [offer_key(o) for o in group] for spec, group in group_specs(offers).items()},
    )
    if "rank_items" in data:
        data["rank_items"] = apply_tag_guard(data["rank_items"], offers)
        data["rank_items"].sort(
            key=lambda item: (
                not evidence_allows_pick(offers[item["index"]]),
                bool(offers[item["index"]].tags),
                evidence_priority(offers[item["index"]]),
            )
        )
        eligible = [
            item for item in data["rank_items"]
            if not offers[item["index"]].tags and evidence_allows_pick(offers[item["index"]])
        ]
        data["top_pick"] = (
            offers[eligible[0]["index"]].model_dump(mode="json") if eligible else None
        )
        data["decision"] = {
            "worth": "wait",
            "engine": "sample",
            "confidence": 0,
            "reason": "演示快照：展示跨平台候选与排序，规格和优惠条件仍需在平台确认",
        }
        data["recommendation"] = "演示数据：本次采集 30 条候选，不代表全网同款或实时成交价。"
        for item in data["rank_items"]:
            item["score"] = 0
            item["reason"] = "冻结样例中的排序；仅供体验界面，不代表实时购买建议"
    return data


def demo_query_response() -> dict:
    """直接比价模式的样例响应。"""
    return _normalized("query.json") | {"cached": False}


def demo_chat_response() -> dict:
    """Agent 决策模式的样例响应（含 trace）。"""
    return _normalized("chat.json")


def demo_rank_response() -> dict:
    """综合排序的样例响应。"""
    chat = demo_chat_response()
    return {
        "items": chat["rank_items"],
        "summary": (chat.get("decision") or {}).get("reason", ""),
        "demo": True,
    }


def demo_refine_response(
    filters: dict | None = None,
    candidate_keys: set[str] | None = None,
    constraints: dict | None = None,
) -> dict:
    """DEMO 模式下的重排：对样例报价**确定性应用筛选**，不调用 LLM。

    保持与真实链路同样的语义（筛选 → 重排），只是用既有的排序作为打分，
    并在 decision / recommendation 里显式标注这是演示数据。
    """
    from datetime import UTC, datetime

    from app.matching.filter import apply_filters
    from app.matching.identity import evidence_allows_pick, evidence_priority
    from app.matching.specs import group_specs
    from app.models.filters import FilterSpec, PurchaseConstraints
    from app.models.offers import RawOffer, offer_key

    chat = demo_chat_response()
    offers = [RawOffer.model_validate(o) for o in chat["offers"]]
    kept = apply_filters(offers, FilterSpec.model_validate(filters or {}))
    if candidate_keys is not None:
        kept = [o for o in kept if offer_key(o) in candidate_keys]
    keep_ids = {id(o) for o in kept}

    picked = [
        it
        for it in chat["rank_items"]
        if 0 <= it["index"] < len(offers) and id(offers[it["index"]]) in keep_ids
    ]
    intent = dict(chat.get("intent", {}))
    if constraints is not None:
        intent.update(PurchaseConstraints.model_validate(constraints).model_dump())
    budget = intent.get("budget")
    preference = intent.get("preference", "")
    shop_priority = any(word in preference for word in ("自营", "旗舰"))
    picked.sort(
        key=lambda it: (
            bool(offers[it["index"]].tags)
            or not evidence_allows_pick(offers[it["index"]])
            or (budget is not None and offers[it["index"]].price > budget),
            evidence_priority(offers[it["index"]]),
            not any(word in (offers[it["index"]].shop or "") for word in ("自营", "旗舰"))
            if shop_priority
            else False,
            offers[it["index"]].price if "价格优先" in preference else 0,
        )
    )
    kept_offers = [offers[it["index"]] for it in picked]
    rank_items = [
        {"index": i, "score": 0, "reason": "样例规则排序：按预算、警示及选购侧重整理"}
        for i, it in enumerate(picked)
    ]
    spec_groups = group_specs(kept_offers) if kept_offers else {}

    if kept_offers:
        prices = [o.price for o in kept_offers]
        top = next(
            (o for o in kept_offers if not o.tags and evidence_allows_pick(o)
             and (budget is None or o.price <= budget)), None
        )
        recommendation = (
            f"（演示数据）已按筛选保留 {len(kept_offers)} 条候选；"
            f"采集报价 ¥{min(prices):.2f} ~ ¥{max(prices):.2f}，请确认规格与价格条件"
        )
    else:
        top = None
        recommendation = "（演示数据）当前筛选条件下没有报价，请放宽筛选条件"

    no_pick_reason = "当前没有同时符合预算与警示条件的样例候选，请调整要求"
    if kept_offers and all(not evidence_allows_pick(o) for o in kept_offers):
        no_pick_reason = "当前样例候选存在规格冲突或混卖，无法确认对应 SKU，请选择规格明确的报价"

    return {
        "trace_id": chat.get("trace_id", ""),
        "query": chat.get("query", ""),
        "intent": intent,
        "offers": [o.model_dump(mode="json") for o in kept_offers],
        "filter_stats": chat.get("filter_stats", {}),
        "errors": {},
        "decision": {
            "worth": "wait",
            "engine": "sample",
            "confidence": (chat.get("decision") or {}).get("confidence"),
            "reason": "样例数据：已按预算、偏好与筛选更新，未调用模型"
            if top
            else no_pick_reason,
        },
        "recommendation": recommendation,
        "rank_items": rank_items,
        "top_pick": top.model_dump(mode="json") if top else None,
        "specs": {
            name: [f"{o.platform}:{o.platform_id}" for o in g] for name, g in spec_groups.items()
        },
        "demo": True,
        "origin": "sample",
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
