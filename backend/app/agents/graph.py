"""LangGraph 编排：intent → research → match → decide → recommend。

trace 记录贯穿全流程：每个节点的输入输出、工具调用、耗时都落库，
前端时间线可完整回放 agent 的决策过程（可解释性）。
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.adapters.registry import get_adapters, search_all
from app.agents.llm_utils import invoke_json
from app.config import get_settings
from app.matching.filter import apply_tag_guard, filter_offers
from app.models.offers import RawOffer
from app.storage.db import record_search, save_trace

# ---------------------------------------------------------------------------
# State：图节点间流转的全部状态
# ---------------------------------------------------------------------------


class AgentState(BaseModel):
    query: str = ""
    intent: dict[str, Any] = Field(default_factory=dict)
    offers: list[RawOffer] = Field(default_factory=list)
    filter_stats: dict[str, Any] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    decision: dict[str, Any] = Field(default_factory=dict)
    recommendation: str = ""
    rank_items: list[dict[str, Any]] = Field(default_factory=list)
    top_pick: dict[str, Any] | None = None
    trace_id: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Trace 记录：内存累积 + 落库
# ---------------------------------------------------------------------------


class TraceRecorder:
    """记录每个节点的执行轨迹。"""

    def __init__(self, trace_id: str, query: str) -> None:
        self.trace_id = trace_id
        self.query = query
        self.steps: list[dict[str, Any]] = []

    def step(self, node: str, input_summary: Any, output_summary: Any, detail: str = "") -> None:
        self.steps.append(
            {
                "node": node,
                "input": _short(input_summary),
                "output": _short(output_summary),
                "detail": detail[:2000],
                "ts": datetime.now(UTC).isoformat(),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "query": self.query,
            "steps": self.steps,
            "ts": datetime.now(UTC).isoformat(),
        }

def _short(v: Any, limit: int = 200) -> str:
    s = str(v)
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


def _llm() -> ChatOpenAI:
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("LLM 未配置：请在 .env 中设置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL")
    return ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or None,
        model=settings.llm_model or "gpt-4o-mini",
        temperature=0,
    )


# ---------------------------------------------------------------------------
# 节点实现
# ---------------------------------------------------------------------------


INTENT_PROMPT = """从用户的购物需求中提取结构化信息，输出 JSON：
{{"product": "商品搜索词（品牌+型号+品类，去掉口语）", "budget": null或数字,
"preference": "一句话偏好或空串"}}

规则：
- product 是可直接用于电商搜索的词，如「小米手环9」
- budget 仅为用户明确说了预算才有值（如"300 以内"→ 300）
- 只输出 JSON

用户需求：{query}"""


def node_intent(state: AgentState) -> dict:
    trace = _pop_trace(state)
    # LLM 失败降级：直接把原句当搜索词
    intent = invoke_json(
        _llm(),
        INTENT_PROMPT.format(query=state.query),
        retries=1,
        fallback={"product": state.query, "budget": None, "preference": ""},
    )
    trace.step("intent", state.query, intent)
    return {"intent": intent, "steps": trace.steps, "trace_id": trace.trace_id}


def _pop_trace(state: AgentState) -> TraceRecorder:
    """从 state 里恢复 recorder（graph 节点间只传可序列化数据）。"""
    r = TraceRecorder(state.trace_id or uuid.uuid4().hex[:12], state.query)
    r.steps = list(state.steps)
    return r


def node_research(state: AgentState) -> dict:
    trace = _pop_trace(state)
    keyword = state.intent.get("product") or state.query
    adapters = get_adapters(get_settings())
    offers, errors = asyncio_run(search_all(keyword, adapters))
    record_search(keyword, offers, errors)
    counts = ", ".join(
        f"{p}:{len([o for o in offers if o.platform == p])}" for p in ("jd", "taobao", "pdd")
    )
    trace.step(
        "research", keyword, f"{len(offers)} 条原始报价（{counts}）", detail=f"errors: {errors}"
    )
    return {"offers": offers, "errors": errors, "steps": trace.steps}


def node_match(state: AgentState) -> dict:
    trace = _pop_trace(state)
    keyword = state.intent.get("product") or state.query
    kept, stats, _ = filter_offers(state.offers, keyword)
    tagged = ", ".join(
        f"{k}:{v}" for k, v in stats.items() if k not in ("total", "kept") and v
    )
    trace.step(
        "match",
        f"{len(state.offers)} 条候选",
        f"{len(kept)} 条全部保留（软标签）",
        detail=f"打标: {tagged or '无'} | stats: {stats}",
    )
    return {"offers": kept, "filter_stats": stats, "steps": trace.steps}


DECIDE_PROMPT = """你是购物决策助手。一次完成两件事：
①是否值得买的判断 ②全部报价的综合排序。输出 JSON：
{{"worth": "buy"/"wait"/"skip", "confidence": 0-100, "reason": "一句话核心理由",
"summary": "整体选购建议一句话",
"items": [{{"index": 下标, "score": 0-100综合分, "reason": "一句话理由"}}]}}

评估维度：到手价 vs 整体分布（是否低价）、店铺可信度（自营/旗舰优先）、销量、规格匹配度、标签警示。
- 「标签」列是系统警示（配件/其他品牌/其他型号/品牌不明/疑似二手/价格异常/销量偏低）
- 带上述标签的报价必须显著降权：配件、其他品牌、其他型号、品牌不明者
  原则上不得作为首选；疑似二手、价格异常者按严重程度降分
- 销量是可穿戴/3C 类目的核心可信度指标：带「销量偏低」标签的报价
  （尤其与多数同款差一个量级，如百件 vs 万件）不得作为首选
- items 必须覆盖全部输入商品、按综合分从高到低排列，score 与顺序必须一致
- budget 仅为用户明确提了才有值；超预算必须 skip
- 只输出 JSON

用户需求：{query}
预算：{budget}
报价（下标 | 平台 | 到手价 | 店铺 | 销量 | 标签 | 标题）：
{offers_text}"""


def _cheapest_fallback(offers: list[RawOffer]) -> dict:
    """decide 节点 LLM 失败时的确定性降级：选价格最低、销量最高可信款。"""
    best = max(
        range(len(offers)),
        key=lambda i: (offers[i].sales or 0, -offers[i].price),
    )
    prices = [o.price for o in offers]
    cheapest = offers[best]
    worth = "buy" if cheapest.price <= min(prices) * 1.1 else "wait"
    return {
        "worth": worth,
        "confidence": 50,
        "reason": "AI 决策暂不可用，已按低价高销量兜底推荐",
        "top_pick": best,
    }


def node_decide(state: AgentState) -> dict:
    """一次 LLM 推理同时产出决策与全量排序，保证二者自洽。"""
    trace = _pop_trace(state)
    offers = state.offers
    if not offers:
        decision = {"worth": "skip", "confidence": 0, "reason": "无有效报价", "top_pick": None}
        trace.step("decide", "0 条报价", decision)
        return {"decision": decision, "steps": trace.steps}

    lines = []
    for i, o in enumerate(offers[:20]):
        sales = o.sales if o.sales is not None else "-"
        tags = "、".join(o.tags) if o.tags else "-"
        lines.append(
            f"{i} | {o.platform} | ¥{o.price:.2f} | {o.shop or '-'} | {sales}"
            f" | {tags} | {o.title[:50]}"
        )
    budget = state.intent.get("budget")
    data = invoke_json(
        _llm(),
        DECIDE_PROMPT.format(
            query=state.query, budget=budget or "未说明", offers_text="\n".join(lines)
        ),
        retries=2,
        fallback=_cheapest_fallback(offers),
    )

    decision = {
        "worth": data.get("worth"),
        "confidence": data.get("confidence"),
        "reason": data.get("reason"),
    }
    # 排序 items：确定性校验下标，越界丢弃；排序依据 LLM 顺序（与其 score 自洽）
    valid = set(range(len(offers)))
    seen: set[int] = set()
    rank_items: list[dict] = []
    for it in data.get("items") or []:
        try:
            idx = int(it.get("index"))
        except (TypeError, ValueError):
            continue
        if idx in valid and idx not in seen:
            seen.add(idx)
            rank_items.append(
                {"index": idx, "score": int(it.get("score") or 0), "reason": it.get("reason", "")}
            )
    # 缺失的按价格升序补在尾部
    missing = sorted((i for i in valid if i not in seen), key=lambda i: offers[i].price)
    for i in missing:
        rank_items.append({"index": i, "score": 0, "reason": ""})

    # 确定性兜底：带警示标签的报价不得排在未打标报价之前
    rank_items = apply_tag_guard(rank_items, offers)

    top_summary = rank_items[0] if rank_items else None
    trace.step(
        "decide",
        f"{len(offers)} 条报价" + (f"，预算 {budget}" if budget else ""),
        {"decision": decision, "rank_count": len(rank_items), "top": top_summary},
    )
    return {"decision": decision, "rank_items": rank_items, "steps": trace.steps}


def node_recommend(state: AgentState) -> dict:
    trace = _pop_trace(state)
    d = state.decision
    offers = state.offers
    budget = state.intent.get("budget")
    parts = []

    # 首选 = 综合排序第一名（与 decide 同一次推理产出，天然自洽）
    top_idx = state.rank_items[0]["index"] if state.rank_items else None

    worth = d.get("worth")
    if worth == "buy":
        parts.append("✅ 现在值得买")
    elif worth == "wait":
        parts.append("⏳ 建议再等等")
    else:
        parts.append("⛔ 建议放弃")
    if d.get("reason"):
        parts.append(f"—— {d['reason']}")

    if top_idx is not None and 0 <= int(top_idx) < len(offers):
        top = offers[int(top_idx)]
        parts.append(
            f"\n\n首选：{top.platform} ¥{top.price:.2f}（{top.shop or '未知店铺'}）"
            + (f" 原价 ¥{top.original_price:.0f}" if top.original_price else "")
            + (f" 已售 {top.sales} 件" if top.sales is not None else "")
            + (f"\n购买入口：{top.url}" if top.url else "")
        )
    if offers:
        prices = [o.price for o in offers]
        parts.append(
            f"\n\n全网 {len(offers)} 条同款，到手价 ¥{min(prices):.2f} ~ ¥{max(prices):.2f}，"
            f"中位 ¥{sorted(prices)[len(prices) // 2]:.2f}"
            + (f"（你的预算 ¥{budget}）" if budget else "")
        )
    recommendation = "".join(parts)

    trace.step("recommend", f"decision={worth}", recommendation[:300])
    # trace 定稿：落库
    save_trace(trace.to_dict())
    # top_pick 结构化返回，前端渲染高亮购买卡
    top_offer = offers[int(top_idx)].model_dump() if top_idx is not None else None
    return {
        "recommendation": recommendation,
        "steps": trace.steps,
        "top_pick": top_offer,
        "rank_items": state.rank_items,
    }


def asyncio_run(coro):
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Graph 组装
# ---------------------------------------------------------------------------

_build_lock = __import__("threading").Lock()
_graph = None


def get_graph():
    global _graph
    with _build_lock:
        if _graph is not None:
            return _graph
        g = StateGraph(AgentState)
        g.add_node("intent", node_intent)
        g.add_node("research", node_research)
        g.add_node("match", node_match)
        g.add_node("decide", node_decide)
        g.add_node("recommend", node_recommend)
        g.set_entry_point("intent")
        g.add_edge("intent", "research")
        g.add_edge("research", "match")
        g.add_edge("match", "decide")
        g.add_edge("decide", "recommend")
        g.add_edge("recommend", END)
        _graph = g.compile()
        return _graph


def run_agent(query: str) -> dict[str, Any]:
    """执行完整 agent 链路，返回 recommendation + offers + trace。"""
    trace_id = uuid.uuid4().hex[:12]
    state = AgentState(query=query.strip(), trace_id=trace_id)
    graph = get_graph()
    final = graph.invoke(state, config={"recursion_limit": 20})
    return {
        "trace_id": trace_id,
        "query": query,
        "intent": final.get("intent", {}),
        "offers": final.get("offers", []),
        "filter_stats": final.get("filter_stats", {}),
        "errors": final.get("errors", {}),
        "decision": final.get("decision", {}),
        "recommendation": final.get("recommendation", ""),
        "rank_items": final.get("rank_items", []),
        "top_pick": final.get("top_pick"),
        "trace": final.get("steps", []),
    }
