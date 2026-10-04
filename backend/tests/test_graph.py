from unittest.mock import patch

from app.agents.graph import (
    AgentState,
    TraceRecorder,
    _cheapest_fallback,
    _pop_trace,
    get_graph,
    get_refine_graph,
    node_filters,
    node_intent,
    node_recommend,
)
from app.models.offers import RawOffer


def _offers() -> list[RawOffer]:
    return [
        RawOffer(
            platform="jd", platform_id="1", title="小米手环9 A", price=199.0,
            sales=10000, url="https://item.jd.com/1.html",
        ),
        RawOffer(
            platform="pdd", platform_id="2", title="小米手环9 B", price=159.0,
            sales=81000, url="https://mobile.yangkeduo.com/goods.html?goods_id=2",
        ),
        RawOffer(
            platform="taobao", platform_id="3", title="小米手环9 C", price=189.0,
            sales=500, url="https://item.taobao.com/item.htm?id=3",
        ),
    ]


class FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content

    def invoke(self, _: str):
        return type("M", (), {"content": self.content})()


# --- TraceRecorder ---

def test_trace_recorder_accumulates_steps() -> None:
    r = TraceRecorder("t1", "查询词")
    r.step("intent", "查询词", {"product": "小米手环9"})
    r.step("research", "小米手环9", "45 条")
    d = r.to_dict()
    assert d["trace_id"] == "t1"
    assert [s["node"] for s in d["steps"]] == ["intent", "research"]
    assert all("ts" in s for s in d["steps"])


def test_trace_shortens_long_values() -> None:
    r = TraceRecorder("t2", "q")
    r.step("n", "x" * 500, "y" * 500)
    assert len(r.steps[0]["input"]) <= 200
    assert len(r.steps[0]["output"]) <= 200


# --- node_intent ---

def test_node_intent_parses_llm_output() -> None:
    state = AgentState(query="预算300买小米手环9", trace_id="t3", steps=[])
    llm = FakeLLM('{"product": "小米手环9", "budget": 300}')
    with patch("app.agents.graph._llm", return_value=llm):
        out = node_intent(state)
    assert out["intent"]["product"] == "小米手环9"
    assert out["intent"]["budget"] == 300
    assert out["steps"][0]["node"] == "intent"


def test_node_intent_degrades_to_raw_query() -> None:
    """LLM 持续失败 → 原句当搜索词，不抛异常。"""
    state = AgentState(query="随便一句话", trace_id="t4", steps=[])
    with patch("app.agents.graph._llm", return_value=FakeLLM("乱输出")):
        out = node_intent(state)
    assert out["intent"]["product"] == "随便一句话"
    assert out["intent"]["budget"] is None


# --- _pop_trace 恢复 ---

def test_pop_trace_restores_steps() -> None:
    steps = [{"node": "intent", "input": "q", "output": "", "detail": "", "ts": ""}]
    state = AgentState(query="q", trace_id="t5", steps=steps)
    r = _pop_trace(state)
    assert r.trace_id == "t5"
    assert len(r.steps) == 1
    assert r.steps[0]["node"] == "intent"


# --- filters 节点 ---

def test_node_filters_applies_platform_tag_price() -> None:
    offers = [
        RawOffer(platform="jd", platform_id="a", title="小米手环9 A", price=100.0),
        RawOffer(platform="pdd", platform_id="b", title="小米手环9 B", price=200.0),
        RawOffer(
            platform="pdd", platform_id="c", title="小米手环9 C",
            price=300.0, tags=["疑似二手"],
        ),
    ]
    state = AgentState(
        query="小米手环9",
        trace_id="t9",
        steps=[],
        offers=offers,
        filters={"platforms": ["pdd"], "exclude_tags": ["疑似二手"], "price_min": 150},
    )
    out = node_filters(state)
    assert [o.platform_id for o in out["offers"]] == ["b"]
    assert out["steps"][-1]["node"] == "filters"


def test_node_filters_noop_without_filters() -> None:
    offers = [RawOffer(platform="jd", platform_id="a", title="小米手环9", price=100.0)]
    state = AgentState(query="q", trace_id="t10", steps=[], offers=offers)
    out = node_filters(state)
    assert len(out["offers"]) == 1
    assert out["steps"][-1]["node"] == "filters"


def test_both_graphs_compile() -> None:
    assert get_graph() is not None
    assert get_refine_graph() is not None


# --- decide 降级 ---

def test_cheapest_fallback_prefers_high_sales_low_price() -> None:
    offers = _offers()
    fb = _cheapest_fallback(offers)
    assert fb["top_pick"] == 1  # pdd：159 + 81000 销量
    assert fb["worth"] == "buy"
    assert fb["confidence"] == 50


# --- recommend 拼装 ---

def test_node_recommend_assembles_output() -> None:
    state = AgentState(
        query="小米手环9",
        trace_id="t6",
        steps=[],
        offers=_offers(),
        decision={"worth": "buy", "confidence": 88, "reason": "低价可信"},
        rank_items=[{"index": 1, "score": 92, "reason": "首选"}],
        intent={"budget": 300},
    )
    with patch("app.agents.graph.save_trace") as st:
        out = node_recommend(state)
    rec = out["recommendation"]
    assert "值得买" in rec
    assert "¥159.00" in rec
    assert "购买入口" in rec
    assert "预算 ¥300" in rec
    assert st.called  # trace 落库被调用
    assert out["steps"][-1]["node"] == "recommend"
    # top_pick 与 rank_items 第一名自洽
    assert out["top_pick"]["price"] == 159.0
    assert out["rank_items"][0]["index"] == 1
