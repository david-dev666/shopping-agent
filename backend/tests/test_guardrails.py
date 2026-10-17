"""推荐约束与服务故障回归；外部服务使用可控替身。"""

import json
from unittest.mock import patch

import httpx
import pytest

from app.agents.graph import AgentState, explicit_budget, node_decide, node_recommend, run_agent
from app.agents.llm_utils import invoke_json
from app.agents.ranker import RankResult
from app.matching.filter import apply_filters
from app.models.filters import FilterSpec
from app.models.offers import RawOffer
from eval.rules import load_cases, predict


class ReplyLLM:
    def __init__(self, data):
        self.data = data
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return type("Message", (), {"content": json.dumps(self.data)})()


def offer(price=199, **kw):
    return RawOffer(
        platform="jd",
        platform_id=kw.pop("platform_id", "1"),
        title=kw.pop("title", "小米手环9 标准版"),
        price=price,
        **kw,
    )


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: f"{c['query']}:{c['title']}")
def test_labeled_rule_regressions(case):
    assert predict(case) == set(case["expect"])


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("预算300元买手环", 300),
        ("预算 199.99 买手环", 199.99),
        ("300元以内的手环", 300),
        ("200 以下 手环", 200),
        ("预算0元", 0),
        ("小米手环9", None),
        ("RTX5060", None),
        ("拯救者Y7000X", None),
    ],
)
def test_explicit_budget_does_not_confuse_model_numbers(query, expected):
    assert explicit_budget(query) == expected


@pytest.mark.parametrize("worth", ["buy", "wait", "skip"])
def test_budget_guard_overrides_model_and_removes_top_pick(worth):
    state = AgentState(query="预算300元", offers=[offer(399)], intent={"budget": 300})
    llm = ReplyLLM(
        {
            "worth": worth,
            "confidence": 99,
            "reason": "买它",
            "items": [{"index": 0, "score": 99, "reason": "首选"}],
        }
    )
    with patch("app.agents.graph._llm", return_value=llm):
        result = node_decide(state)
    assert result["decision"]["worth"] == "skip"
    with patch("app.agents.graph.save_trace"):
        rec = node_recommend(state.model_copy(update=result))
    assert rec["top_pick"] is None
    assert "首选：" not in rec["recommendation"]


def test_budget_guard_moves_affordable_offer_before_expensive_model_pick():
    state = AgentState(
        query="q", offers=[offer(399), offer(299, platform_id="2")], intent={"budget": 300}
    )
    llm = ReplyLLM(
        {
            "worth": "buy",
            "confidence": 99,
            "reason": "399最合适",
            "items": [
                {"index": 0, "score": 99, "reason": "首选"},
                {"index": 1, "score": 80, "reason": "备选"},
            ],
        }
    )
    with patch("app.agents.graph._llm", return_value=llm):
        result = node_decide(state)
    assert result["rank_items"][0]["index"] == 1
    assert result["decision"]["worth"] == "wait"
    assert "399最合适" not in result["decision"]["reason"]


def test_model_sees_candidates_beyond_twentieth():
    offers = [offer(100 + i, platform_id=str(i)) for i in range(30)]
    offers[-1].title = "小米手环9 标准版 最后一个候选"
    llm = ReplyLLM(
        {
            "worth": "wait",
            "confidence": 50,
            "reason": "需确认",
            "items": [{"index": 29, "score": 90, "reason": "匹配"}],
        }
    )
    with patch("app.agents.graph._llm", return_value=llm):
        result = node_decide(AgentState(query="手环9", offers=offers))
    assert "最后一个候选" in llm.prompts[0]
    assert len(result["rank_items"]) == 30
    assert result["rank_items"][0]["index"] == 29


@pytest.mark.parametrize(
    "data",
    [
        {"worth": "invalid", "confidence": 500, "items": []},
        {"worth": "buy", "confidence": 90, "reason": "x", "items": [None]},
        {"worth": "buy", "confidence": 90, "reason": "x", "items": [{"index": 0, "score": "bad"}]},
    ],
)
def test_malformed_decision_schema_degrades(data):
    with patch("app.agents.graph._llm", return_value=ReplyLLM(data)):
        result = node_decide(AgentState(offers=[offer()]))
    assert result["decision"]["worth"] == "wait"
    assert result["rank_items"][0]["index"] == 0


@pytest.mark.parametrize("tag", ["其他型号", "配件", "疑似二手", "价格异常", "销量偏低"])
def test_all_warned_candidates_do_not_get_top_pick(tag):
    state = AgentState(offers=[offer(tags=[tag])])
    with patch("app.agents.graph._llm", return_value=None):
        result = node_decide(state)
    with patch("app.agents.graph.save_trace"):
        rec = node_recommend(state.model_copy(update=result))
    assert rec["top_pick"] is None
    assert result["decision"]["worth"] == "wait"


@pytest.mark.parametrize(
    "failure", [TimeoutError(), ConnectionError(), httpx.ConnectError("offline")]
)
def test_network_failures_use_fallback(failure):
    class Offline:
        def invoke(self, prompt):
            raise failure

    assert invoke_json(Offline(), "p", fallback={"degraded": True}) == {"degraded": True}


def test_schema_validation_is_inside_retry_and_fallback():
    result = invoke_json(
        ReplyLLM({"items": [None]}),
        "p",
        retries=0,
        fallback={"items": [], "summary": "降级"},
        validate=lambda d: RankResult.model_validate(d).model_dump(),
    )
    assert result["summary"] == "降级"


def test_refine_spec_uses_platform_scoped_ids():
    offers = [
        offer(title="小米手环9 NFC版"),
        RawOffer(platform="taobao", platform_id="1", title="小米手环9 黑色", price=199),
    ]
    assert apply_filters(offers, FilterSpec(spec="NFC版")) == [offers[0]]


def test_full_graph_without_llm_keeps_explicit_budget_and_feedback(monkeypatch):
    async def search_all(query, adapters):
        return [offer(299), offer(399, platform_id="2"), offer(99, platform_id="hidden")], {}

    monkeypatch.setattr("app.agents.graph._llm", lambda: None)
    monkeypatch.setattr("app.agents.graph.get_adapters", lambda _: [])
    monkeypatch.setattr("app.agents.graph.search_all", search_all)
    monkeypatch.setattr("app.agents.graph.record_search", lambda *args: None)
    monkeypatch.setattr("app.agents.graph.get_feedback_ids", lambda: {("jd", "hidden")})
    monkeypatch.setattr("app.agents.graph.save_trace", lambda _: None)
    result = run_agent("预算300元买小米手环9")
    assert result["intent"]["budget"] == 300
    assert result["top_pick"]["price"] == 299
    assert len(result["offers"]) == 2
    assert [s["node"] for s in result["trace"]] == [
        "intent",
        "research",
        "match",
        "filters",
        "decide",
        "recommend",
    ]
    assert all(":" in key for keys in result["specs"].values() for key in keys)


def test_refine_explicit_budget_overrides_returned_intent(monkeypatch):
    from app.agents.graph import run_refine

    monkeypatch.setattr("app.agents.graph._llm", lambda: None)
    monkeypatch.setattr("app.agents.graph.save_trace", lambda _: None)
    result = run_refine("预算100元买手环", [offer(199)], intent={"budget": 999})
    assert result["intent"]["budget"] == 100
    assert result["top_pick"] is None


def test_fallback_ranking_agrees_with_actual_top_pick(monkeypatch):
    from app.agents.graph import run_refine

    monkeypatch.setattr("app.agents.graph._llm", lambda: None)
    monkeypatch.setattr("app.agents.graph.save_trace", lambda _: None)
    result = run_refine("小米手环9", [offer(50, tags=["配件"]), offer(200, platform_id="2")])
    top = result["offers"][result["rank_items"][0]["index"]]
    assert top.price == result["top_pick"]["price"] == 200


def test_skip_decision_does_not_show_a_purchase_pick():
    state = AgentState(
        offers=[offer()],
        decision={"worth": "skip", "reason": "不适合需求"},
        rank_items=[{"index": 0, "score": 90}],
    )
    with patch("app.agents.graph.save_trace"):
        result = node_recommend(state)
    assert result["top_pick"] is None
    assert "首选：" not in result["recommendation"]
