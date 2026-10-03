import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.adapters.registry import get_adapters, search_all
from app.agents.graph import run_agent
from app.agents.ranker import rank_offers
from app.config import get_settings
from app.matching.filter import REASON_LABELS, filter_offers
from app.models.offers import RawOffer
from app.storage.db import get_feedback_ids, load_trace, record_feedback, record_search

router = APIRouter(prefix="/api")

# 查询缓存：避免重复搜索反复触发真实采集（浏览器采集尤其容易被平台风控）
CACHE_TTL_SECONDS = 300
_query_cache: dict[str, tuple[float, "QueryResponse"]] = {}


class QueryRequest(BaseModel):
    query: str


class FilterStats(BaseModel):
    total: int = 0
    kept: int = 0
    second_hand: int = 0
    rival: int = 0
    accessory: int = 0
    off_brand: int = 0
    price_outlier: int = 0
    low_sales: int = 0


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
    cached: bool = False


@router.post("/query", response_model=QueryResponse)
async def query_products(req: QueryRequest) -> QueryResponse:
    q = req.query.strip()

    # 缓存命中：直接返回，不触发采集
    hit = _query_cache.get(q)
    if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
        resp = hit[1].model_copy(update={"cached": True})
        return resp

    adapters = get_adapters(get_settings())
    offers, errors = await search_all(q, adapters)

    # 相关性过滤：剔除二手/竞品/纯配件，过滤前全量落库（保留原始数据可查）
    record_search(q, offers, errors)

    # 用户人工标记过的商品直接排除（低置信走人工确认）
    feedback_ids = get_feedback_ids()
    offers = [o for o in offers if (o.platform, o.platform_id) not in feedback_ids]

    kept, stats, removed = filter_offers(offers, q)

    resp = QueryResponse(
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
    # 滑块验证导致的失败不缓存：用户完成验证后立即重搜应触发真实采集
    needs_verify = any("NEED_MANUAL_VERIFY" in e for e in errors.values())
    if not needs_verify:
        # 即使本次结果为空也缓存：风控/临时故障期间避免高频重试加重风控
        _query_cache[q] = (time.time(), resp)
    return resp


class RankRequest(BaseModel):
    query: str
    offers: list[RawOffer]


class FeedbackRequest(BaseModel):
    platform: str
    platform_id: str
    reason: str = "user_marked"


@router.post("/feedback")
async def feedback(req: FeedbackRequest) -> dict:
    """用户标记某条报价不相关（二手/杂牌等），后续查询排除。"""
    record_feedback(req.platform, req.platform_id, req.reason)
    return {"ok": True}


class ChatRequest(BaseModel):
    query: str


@router.post("/chat")
async def chat(req: ChatRequest) -> dict:
    """对话式 agent 入口：intent → research → match → decide → recommend，全程 trace。"""
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 为空")
    try:
        return run_agent(q)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/trace/{trace_id}")
async def get_trace(trace_id: str) -> dict:
    """回放某次 agent 运行的完整轨迹。"""
    t = load_trace(trace_id)
    if not t:
        raise HTTPException(status_code=404, detail="trace 不存在")
    return t


@router.post("/rank")
async def rank_products(req: RankRequest) -> dict:
    """LLM 综合排序：输入已过滤的 offers，返回排序与推荐理由。"""
    if not req.offers:
        raise HTTPException(status_code=400, detail="offers 为空，无需排序")
    try:
        return rank_offers(req.query, req.offers)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
