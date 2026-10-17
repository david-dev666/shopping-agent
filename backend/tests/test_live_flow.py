"""真实查询、样例、缓存和可编辑需求的行为边界。"""

import asyncio
import json
import threading

import httpx
import pytest

from app.agents.graph import AGENT_NODES, run_refine, stream_agent
from app.config import Settings
from app.main import app
from app.models.offers import RawOffer
from app.storage.db import load_trace


def offer(price=199, identifier="flow", shop="普通店"):
    return RawOffer(
        platform="jd",
        platform_id=identifier,
        title="小米手环9 标准版",
        price=price,
        shop=shop,
        sales=1000,
    )


@pytest.fixture
def research(monkeypatch):
    calls = []

    async def search(query, adapters):
        calls.append(query)
        return [offer(), offer(299, "flow-2", "小米旗舰店")], {}

    monkeypatch.setattr("app.agents.graph._llm", lambda: None)
    monkeypatch.setattr("app.agents.graph.get_adapters", lambda _: [])
    monkeypatch.setattr("app.agents.graph.search_all", search)
    return calls


def test_real_stream_reports_actual_graph_updates(research):
    events = list(stream_agent("预算300元买小米手环9"))
    completed = [e["node"] for e in events if e.get("status") == "complete"]
    assert completed == list(AGENT_NODES)
    result = events[-1]["result"]
    assert result["origin"] == "live" and result["cached"] is False
    assert result["decision"]["engine"] == "rules"
    assert result["top_pick"]["price"] == 199
    assert len(research) == 1
    assert len(load_trace(result["trace_id"])["steps"]) == 6


def test_cancellation_prevents_starting_research(research):
    stop = threading.Event()
    iterator = stream_agent("小米手环9", stop)
    started = next(iterator)
    assert next(iterator)["node"] == "intent"
    stop.set()
    assert not list(iterator)
    assert research == []
    assert load_trace(started["trace_id"])["steps"][-1]["node"] == "cancelled"


def test_failed_stream_saves_a_partial_trace(monkeypatch):
    def unavailable():
        raise RuntimeError("test configuration failure")

    monkeypatch.setattr("app.agents.graph._llm", unavailable)
    iterator = stream_agent("小米手环9")
    started = next(iterator)
    with pytest.raises(RuntimeError):
        list(iterator)
    assert load_trace(started["trace_id"])["steps"][-1]["node"] == "failed"


@pytest.mark.parametrize("budget", [100, None])
def test_explicit_requirement_edit_overrides_original_sentence(research, budget):
    result = run_refine(
        "预算300元买手环", [offer()], intent={"budget": 300}, constraints={"budget": budget}
    )
    assert result["intent"]["budget"] == budget
    assert (result["top_pick"] is None) == (budget == 100)
    assert result["origin"] == "refine"
    assert research == []


def test_shop_preference_is_used_in_rules_fallback(research):
    result = run_refine(
        "小米手环9",
        [offer(), offer(299, "flow-2", "小米旗舰店")],
        constraints={"preference": "优先自营/旗舰"},
    )
    assert result["top_pick"]["price"] == 299
    assert "店铺文本" in result["decision"]["reason"]


def frames(text):
    result = []
    for frame in text.strip().split("\n\n"):
        data = next((line[6:] for line in frame.splitlines() if line.startswith("data: ")), None)
        if data:
            result.append(json.loads(data))
    return result


async def test_explicit_live_bypasses_legacy_demo_default(monkeypatch):
    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(demo_mode=True))
    calls = []

    def live(query):
        calls.append(query)
        return {"offers": [], "origin": "live"}

    monkeypatch.setattr("app.api.routes.run_agent", live)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        result = await c.post("/api/chat", json={"query": "actual", "data_mode": "live"})
    assert result.json()["origin"] == "live"
    assert calls == ["actual"]


async def test_sample_stream_has_no_fake_progress(monkeypatch):
    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(demo_mode=False))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        result = await c.post(
            "/api/chat/stream", json={"query": "小米手环9", "data_mode": "sample"}
        )
    assert result.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" not in result.text
    assert frames(result.text)[0]["result"]["origin"] == "sample"


async def test_live_stream_endpoint_returns_serializable_offers(monkeypatch, research):
    monkeypatch.setattr("app.api.routes.get_settings", lambda: Settings(demo_mode=False))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        result = await c.post("/api/chat/stream", json={"query": "小米手环9", "data_mode": "live"})
    events = frames(result.text)
    assert len(events) == 13
    assert events[-1]["result"]["offers"][0]["price"] == 199
    assert events[-1]["result"]["demo"] is False


async def test_query_cache_reports_age_and_refresh_bypasses_it(monkeypatch):
    from app.api import routes

    calls = []

    async def search(query, adapters):
        calls.append(query)
        return [offer(100 + len(calls), identifier="cache-flow")], {}

    monkeypatch.setattr(
        routes, "get_settings", lambda: Settings(demo_mode=False, webbridge_enabled=False)
    )
    monkeypatch.setattr(routes, "search_all", search)
    routes._query_cache.clear()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            body = {"query": "cache flow", "data_mode": "live"}
            first = (await c.post("/api/query", json=body)).json()
            second = (await c.post("/api/query", json=body)).json()
            fresh = (await c.post("/api/query", json={**body, "refresh": True})).json()
        assert first["origin"] == fresh["origin"] == "live"
        assert second["origin"] == "cache" and second["cached"] is True
        assert second["cache_age_seconds"] >= 0
        assert len(calls) == 2
        assert fresh["offers"][0]["price"] > first["offers"][0]["price"]
    finally:
        routes._query_cache.clear()


async def test_sample_refine_obeys_edited_budget():
    from app.demo_data import demo_chat_response

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        result = await c.post(
            "/api/refine",
            json={
                "query": "小米手环9",
                "data_mode": "sample",
                "offers": demo_chat_response()["offers"],
                "constraints": {"budget": 1},
            },
        )
    assert result.json()["top_pick"] is None
    assert result.json()["intent"]["budget"] == 1
    assert result.json()["origin"] == "sample"


def test_stream_durations_survive_later_graph_state_updates(monkeypatch, research):
    clock = iter(range(20))
    monkeypatch.setattr("app.agents.graph.perf_counter", lambda: next(clock))
    result = list(stream_agent("小米手环9"))[-1]["result"]
    assert [step["elapsed_ms"] for step in result["trace"]] == [1000] * 6
    saved = load_trace(result["trace_id"])
    assert saved["steps"][0]["elapsed_ms"] == 1000


@pytest.mark.parametrize(
    "body",
    [
        {"query": "x", "data_mode": "unknown"},
        {"query": "x", "data_mode": "live", "offers": [], "constraints": {"budget": -1}},
    ],
)
async def test_invalid_source_and_constraints_are_rejected(body):
    endpoint = "/api/refine" if "offers" in body else "/api/chat/stream"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(endpoint, json=body)
    assert response.status_code == 422


def test_sample_preferences_affect_rule_sorting_without_calling_llm():
    from app.demo_data import demo_refine_response

    price_first = demo_refine_response(constraints={"preference": "价格优先"})
    clean = [o for o in price_first["offers"] if not o["tags"]]
    assert price_first["top_pick"]["price"] == min(o["price"] for o in clean)
    shop_first = demo_refine_response(constraints={"preference": "优先自营/旗舰"})
    assert any(word in shop_first["top_pick"]["shop"] for word in ("自营", "旗舰"))
    assert shop_first["decision"]["engine"] == "sample"


async def test_disconnect_propagates_cancellation_to_stream_worker(monkeypatch):
    from app.api.streaming import agent_events

    stopped = threading.Event()
    signals = []

    def controlled_stream(query, cancelled):
        signals.append(cancelled)
        yield {"event": "progress", "node": "intent", "status": "running"}
        cancelled.wait(1)
        if cancelled.is_set():
            stopped.set()

    class Connection:
        disconnected = False

        async def is_disconnected(self):
            return self.disconnected

    monkeypatch.setattr("app.api.streaming.stream_agent", controlled_stream)
    connection = Connection()
    events = agent_events("test", connection)
    assert "event: progress" in await anext(events)
    connection.disconnected = True
    assert [event async for event in events] == []
    assert signals[0].is_set()
    assert await asyncio.to_thread(stopped.wait, 1)
