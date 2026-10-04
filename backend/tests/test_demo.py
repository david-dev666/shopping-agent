from fastapi.testclient import TestClient

from app.demo_data import demo_chat_response, demo_query_response, demo_rank_response
from app.main import app


def test_demo_chat_response_labeled() -> None:
    d = demo_chat_response()
    assert d["demo"] is True
    assert d["offers"] and d["rank_items"] and d["trace"]


def test_demo_query_response_labeled() -> None:
    d = demo_query_response()
    assert d["demo"] is True
    assert d["cached"] is False
    assert d["offers"]


def test_demo_rank_response_labeled() -> None:
    d = demo_rank_response()
    assert d["demo"] is True
    assert d["items"]


def test_query_endpoint_short_circuits_in_demo(monkeypatch) -> None:
    class _S:
        demo_mode = True

    monkeypatch.setattr("app.api.routes.get_settings", lambda: _S())
    with TestClient(app) as client:
        r = client.post("/api/query", json={"query": "小米手环9"})
        assert r.status_code == 200
        assert r.json()["demo"] is True

        r2 = client.post("/api/chat", json={"query": "小米手环9"})
        assert r2.status_code == 200
        assert r2.json()["demo"] is True
