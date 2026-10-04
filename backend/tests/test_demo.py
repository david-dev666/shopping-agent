from fastapi.testclient import TestClient

from app.demo_data import (
    demo_chat_response,
    demo_query_response,
    demo_rank_response,
    demo_refine_response,
)
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


def test_demo_refine_applies_filters_deterministically() -> None:
    full = demo_refine_response({})
    assert full["demo"] is True
    assert full["offers"]

    filtered = demo_refine_response({"platforms": ["jd"], "exclude_tags": ["疑似二手"]})
    assert len(filtered["offers"]) <= len(full["offers"])
    assert all(o["platform"] == "jd" for o in filtered["offers"])
    assert all("疑似二手" not in o.get("tags", []) for o in filtered["offers"])
    # rank_items 下标必须对齐返回的 offers（前端按此索引）
    for it in filtered["rank_items"]:
        assert 0 <= it["index"] < len(filtered["offers"])
    assert [s["node"] for s in filtered["trace"]] == ["filters"]


def test_demo_refine_empty_result_is_labeled() -> None:
    d = demo_refine_response({"price_max": 0.01})
    assert d["offers"] == []
    assert d["rank_items"] == []
    assert d["top_pick"] is None
    assert "没有报价" in d["recommendation"]


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

        r3 = client.post(
            "/api/refine",
            json={
                "query": "小米手环9",
                "offers": [{"platform": "jd", "platform_id": "1", "title": "x", "price": 1.0}],
                "filters": {},
            },
        )
        assert r3.status_code == 200
        assert r3.json()["demo"] is True
