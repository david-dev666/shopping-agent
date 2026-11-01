import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.adapters.webbridge import WebBridgeClient
from app.config import Settings
from app.main import app


@pytest.fixture
def offline_settings(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.get_settings",
        lambda: Settings(
            demo_mode=False,
            llm_api_key="",
            webbridge_enabled=False,
        ),
    )


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/chat", {"query": "   "}),
        ("/api/query", {"query": ""}),
        ("/api/chat", {"query": "x" * 501}),
        (
            "/api/refine",
            {"snapshot_id": "a" * 32, "filters": {"price_min": 300, "price_max": 100}},
        ),
        ("/api/refine", {"snapshot_id": "a" * 32, "filters": {"price_min": -1}}),
        ("/api/refine", {"query": "x", "offers": [], "intent": {"budget": "garbage"}}),
        (
            "/api/rank",
            {
                "query": "x",
                "offers": [
                    {"platform": "jd", "platform_id": "1", "title": "x", "price": -2},
                ],
            },
        ),
    ],
)
async def test_invalid_inputs_are_422(path, body, offline_settings):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(path, json=body)
    assert response.status_code == 422


async def test_chat_does_not_block_health_requests(monkeypatch, offline_settings):
    entered, release = threading.Event(), threading.Event()

    def slow_agent(query):
        entered.set()
        release.wait(2)
        return {"offers": []}

    monkeypatch.setattr("app.api.routes.run_agent", slow_agent)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        chat = asyncio.create_task(c.post("/api/chat", json={"query": "test"}))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            response = await asyncio.wait_for(c.get("/health"), timeout=0.5)
            assert response.status_code == 200
            assert not chat.done()
        finally:
            release.set()
            await chat


def test_browser_lock_serializes_separate_event_loops():
    client = WebBridgeClient("http://unused", "test")
    entered = threading.Barrier(2)
    counts = {"active": 0, "peak": 0}

    async def use_tab():
        async with client._get_lock():
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
            await asyncio.sleep(0.08)
            counts["active"] -= 1

    def worker():
        entered.wait(timeout=2)
        asyncio.run(use_tab())

    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(worker) for _ in range(2)]
        for job in jobs:
            job.result(timeout=3)
    assert counts["peak"] == 1


async def test_status_does_not_expose_credentials(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.get_settings", lambda: Settings(llm_api_key="private-value")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        result = await c.get("/api/status")
    assert result.json()["llm_configured"] is True
    assert "private-value" not in result.text


@pytest.mark.parametrize("path", ["/api/chat", "/api/refine"])
async def test_intelligent_requests_require_model_without_rule_substitution(monkeypatch, path):
    from app.storage.db import snapshot_response

    monkeypatch.setattr("app.agents.graph._llm", lambda: None)

    async def forbidden(*args):
        pytest.fail("collection must not run without a model")

    monkeypatch.setattr("app.agents.graph.search_all", forbidden)
    body = {"query": "小米手环9", "data_mode": "live"}
    if path == "/api/refine":
        saved = snapshot_response({"query": "小米手环9", "offers": [
            {"platform": "jd", "platform_id": "model-required", "title": "小米手环9", "price": 199},
        ]})
        body = {"snapshot_id": saved["snapshot_id"]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json=body)
    assert response.status_code == 503
    assert "需要配置模型" in response.json()["detail"]
