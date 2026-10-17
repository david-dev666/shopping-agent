import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool

from app.adapters.registry import get_adapters, search_all
from app.agents.graph import IntentResult, run_agent, run_refine
from app.agents.ranker import rank_offers
from app.api.streaming import agent_events, encode_event
from app.config import get_settings
from app.demo_data import (
    demo_chat_response,
    demo_query_response,
    demo_rank_response,
    demo_refine_response,
)
from app.matching.filter import REASON_LABELS, filter_offers
from app.matching.specs import group_specs
from app.models.filters import FilterSpec, PurchaseConstraints
from app.models.offers import RawOffer, offer_key
from app.storage.db import get_feedback_ids, load_trace, record_feedback, record_search

router = APIRouter(prefix="/api")

# 查询缓存：避免重复搜索反复触发真实采集（浏览器采集尤其容易被平台风控）
CACHE_TTL_SECONDS = 300
_query_cache: dict[str, tuple[float, "QueryResponse"]] = {}


class DataModeRequest(BaseModel):
    data_mode: Literal["live", "sample"] | None = None


def use_sample(mode: str | None) -> bool:
    return mode == "sample" or (mode is None and get_settings().demo_mode)


class QueryRequest(DataModeRequest):
    query: str = Field(min_length=1, max_length=500, pattern=r"\S")
    refresh: bool = False


class FilterStats(BaseModel):
    total: int = 0
    kept: int = 0
    second_hand: int = 0
    rival: int = 0
    accessory: int = 0
    off_brand: int = 0
    price_outlier: int = 0
    low_sales: int = 0
    model_mismatch: int = 0


class RemovedOffer(BaseModel):
    offer: RawOffer
    reason: str
    reason_label: str


class QueryResponse(BaseModel):
    query: str = Field(min_length=1, max_length=500, pattern=r"\S")
    offers: list[RawOffer]
    errors: dict[str, str]
    filter_stats: FilterStats = FilterStats()
    removed_offers: list[RemovedOffer] = []
    cached: bool = False
    origin: Literal["live", "cache", "sample", "refine"] = "live"
    cache_age_seconds: int = 0
    completed_at: datetime | None = None
    # DEMO_MODE 标记：前端据此显示「演示数据」横幅
    demo: bool = False
    # 规格分组：{规格名: [platform:platform_id, ...]}，前端做规格筛选
    specs: dict[str, list[str]] = {}


@router.post("/query", response_model=QueryResponse)
async def query_products(req: QueryRequest) -> QueryResponse:
    q = req.query.strip()

    # DEMO_MODE：返回内置样例，不触发任何采集
    if use_sample(req.data_mode):
        return QueryResponse(**demo_query_response())

    # 缓存命中：直接返回，不触发采集
    hit = _query_cache.get(q)
    if not req.refresh and hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
        resp = hit[1].model_copy(
            deep=True,
            update={
                "cached": True,
                "origin": "cache",
                "cache_age_seconds": max(0, int(time.time() - hit[0])),
            },
        )
        return resp

    adapters = get_adapters(get_settings())
    offers, errors = await search_all(q, adapters)

    # 相关性打标：命中规则写入 offer.tags（不再剔除），打标前全量落库（保留原始数据可查）
    record_search(q, offers, errors)

    # 用户人工标记过的商品直接排除（低置信走人工确认）
    feedback_ids = get_feedback_ids()
    offers = [o for o in offers if (o.platform, o.platform_id) not in feedback_ids]

    kept, stats, removed = filter_offers(offers, q)

    spec_groups = group_specs(kept)
    resp = QueryResponse(
        query=q,
        completed_at=datetime.now(UTC),
        offers=kept,
        errors=errors,
        filter_stats=FilterStats(**stats),
        removed_offers=[
            RemovedOffer(
                offer=r["offer"], reason=r["reason"], reason_label=REASON_LABELS[r["reason"]]
            )
            for r in removed
        ],
        specs={name: [offer_key(o) for o in group] for name, group in spec_groups.items()},
    )
    # 滑块验证导致的失败不缓存：用户完成验证后立即重搜应触发真实采集
    needs_verify = any("NEED_MANUAL_VERIFY" in e for e in errors.values())
    if not needs_verify:
        # 即使本次结果为空也缓存：风控/临时故障期间避免高频重试加重风控
        now = time.time()
        for key in list(_query_cache):
            if now - _query_cache[key][0] >= CACHE_TTL_SECONDS:
                del _query_cache[key]
        if len(_query_cache) >= 128 and q not in _query_cache:
            del _query_cache[min(_query_cache, key=lambda key: _query_cache[key][0])]
        _query_cache[q] = (now, resp)
    return resp


class RankRequest(DataModeRequest):
    query: str = Field(min_length=1, max_length=500, pattern=r"\S")
    offers: list[RawOffer] = Field(max_length=200)


class FeedbackRequest(BaseModel):
    platform: str
    platform_id: str
    reason: str = "user_marked"


@router.post("/feedback")
async def feedback(req: FeedbackRequest) -> dict:
    """用户标记某条报价不相关（二手/杂牌等），后续查询排除。"""
    record_feedback(req.platform, req.platform_id, req.reason)
    _query_cache.clear()
    return {"ok": True}


class ChatRequest(DataModeRequest):
    query: str = Field(min_length=1, max_length=500, pattern=r"\S")


@router.post("/chat")
async def chat(req: ChatRequest) -> dict:
    """对话式 agent 入口：intent → research → match → filters → decide → recommend，全程 trace。"""
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 为空")
    if use_sample(req.data_mode):
        return demo_chat_response()
    try:
        return await run_in_threadpool(run_agent, q)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


class RefineRequest(DataModeRequest):
    query: str = Field(min_length=1, max_length=500, pattern=r"\S")
    offers: list[RawOffer] = Field(max_length=200)
    filters: FilterSpec = FilterSpec()
    intent: dict = {}
    constraints: PurchaseConstraints | None = None

    @model_validator(mode="after")
    def validate_intent(self):
        self.intent = IntentResult.model_validate(
            {"product": self.query, **self.intent}
        ).model_dump()
        return self


@router.post("/refine")
async def refine(req: RefineRequest) -> dict:
    """按筛选条件重排：跳过采集与打标，复用 filters → decide → recommend。

    候选集由前端回传（上次运行的 offers），筛选条件确定性应用，
    再让 LLM 在缩小后的集合上重新决策与排序。
    """
    q = req.query.strip()
    if not req.offers:
        raise HTTPException(status_code=400, detail="offers 为空，无需重排")
    if use_sample(req.data_mode):
        return demo_refine_response(
            req.filters.model_dump(),
            {offer_key(o) for o in req.offers},
            req.constraints.model_dump() if req.constraints is not None else None,
        )
    try:
        return await run_in_threadpool(
            run_refine,
            q,
            req.offers,
            req.filters.model_dump(),
            req.intent,
            req.constraints.model_dump() if req.constraints is not None else None,
        )
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
    if use_sample(req.data_mode):
        return demo_rank_response()
    if not req.offers:
        raise HTTPException(status_code=400, detail="offers 为空，无需排序")
    try:
        return await run_in_threadpool(rank_offers, req.query, req.offers)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/status")
def status() -> dict:
    """仅返回能力状态，不返回密钥、地址或凭据。"""
    settings = get_settings()
    return {
        "demo": settings.demo_mode,
        "llm_configured": bool(settings.llm_api_key),
        "sources": [
            {
                "platform": a.platform,
                "source": "browser" if a.__class__.__name__ == "WebBridgeAdapter" else "api",
            }
            for a in get_adapters(settings)
        ],
    }


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    if use_sample(req.data_mode):

        async def sample():
            yield encode_event({"event": "result", "result": demo_chat_response()})

        body = sample()
    else:
        body = agent_events(req.query.strip(), request)
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
