from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.adapters.registry import get_adapters, search_all
from app.agents.ranker import rank_offers
from app.config import get_settings
from app.matching.filter import REASON_LABELS, filter_offers
from app.models.offers import RawOffer
from app.storage.db import record_search

router = APIRouter(prefix="/api")


class QueryRequest(BaseModel):
    query: str


class FilterStats(BaseModel):
    total: int = 0
    kept: int = 0
    second_hand: int = 0
    rival: int = 0
    accessory: int = 0
    off_brand: int = 0


class RemovedOffer(BaseModel):
    offer: RawOffer
    reason: str
    reason_label: str


class QueryResponse(BaseModel):
    query: str
    offers: list[RawOffer]
    errors: dict[str, str]
    filter_stats: FilterStats = FilterStats()
    removed_offers: list[RemovedOffer] = []


@router.post("/query", response_model=QueryResponse)
async def query_products(req: QueryRequest) -> QueryResponse:
    q = req.query.strip()
    adapters = get_adapters(get_settings())
    offers, errors = await search_all(q, adapters)

    # 相关性过滤：剔除二手/竞品/纯配件，过滤前全量落库（保留原始数据可查）
    record_search(q, offers, errors)
    kept, stats, removed = filter_offers(offers, q)

    return QueryResponse(
        query=q,
        offers=kept,
        errors=errors,
        filter_stats=FilterStats(**stats),
        removed_offers=[
            RemovedOffer(
                offer=r["offer"], reason=r["reason"], reason_label=REASON_LABELS[r["reason"]]
            )
            for r in removed
        ],
    )


class RankRequest(BaseModel):
    query: str
    offers: list[RawOffer]


@router.post("/rank")
async def rank_products(req: RankRequest) -> dict:
    """LLM 综合排序：输入已过滤的 offers，返回排序与推荐理由。"""
    if not req.offers:
        raise HTTPException(status_code=400, detail="offers 为空，无需排序")
    try:
        return rank_offers(req.query, req.offers)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

