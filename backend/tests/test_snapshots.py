"""The browser cannot replace saved candidates, query, intent or source on refinement."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.storage import db


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def sample(client, path="/api/chat"):
    response = client.post(path, json={"query": "小米手环9", "data_mode": "sample"})
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("path", ["/api/query", "/api/chat", "/api/chat/stream"])
def test_all_query_entries_persist_snapshots(client, path):
    import json

    response = client.post(path, json={"query": "小米手环9", "data_mode": "sample"})
    result = (
        response.json()
        if path != "/api/chat/stream"
        else json.loads(
            next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        )["result"]
    )
    saved = db.load_candidate_snapshot(result["snapshot_id"])
    assert saved["query"] == result["query"]
    assert saved["offers"] == result["offers"]
    assert saved["demo"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("offers", []),
        ("query", "改成其他型号"),
        ("intent", {"budget": 1}),
        ("data_mode", "live"),
    ],
)
def test_refine_rejects_client_replacement(client, field, value):
    initial = sample(client)
    response = client.post(
        "/api/refine",
        json={
            "snapshot_id": initial["snapshot_id"],
            field: value,
        },
    )
    assert response.status_code == 422


def test_sample_refine_uses_saved_candidates_and_restores_full_set(client, monkeypatch):
    initial = sample(client)
    identifier = initial["snapshot_id"]
    monkeypatch.setattr("app.demo_data.demo_chat_response", lambda: pytest.fail("fixture reloaded"))
    narrowed = client.post(
        "/api/refine",
        json={
            "snapshot_id": identifier,
            "filters": {"platforms": ["jd"]},
            "constraints": {"budget": 1},
        },
    ).json()
    assert narrowed["offers"] and all(o["platform"] == "jd" for o in narrowed["offers"])
    assert narrowed["top_pick"] is None
    assert narrowed["intent"]["budget"] == 1
    restored = client.post("/api/refine", json={"snapshot_id": identifier}).json()
    assert restored["snapshot_id"] == identifier
    assert restored["demo"] is True
    assert len(restored["offers"]) == len(initial["offers"])
    assert {o["platform_id"]: (o["title"], o["price"]) for o in restored["offers"]} == {
        o["platform_id"]: (o["title"], o["price"]) for o in initial["offers"]
    }


def test_snapshot_survives_connection_restart_and_returns_detached_data(client):
    initial = sample(client)
    identifier = initial["snapshot_id"]
    saved = db.load_candidate_snapshot(identifier)
    saved["offers"][0]["price"] = 0.01
    db.get_engine().dispose()
    assert db.load_candidate_snapshot(identifier)["offers"][0]["price"] != 0.01


@pytest.mark.parametrize("expired", [False, True])
def test_unknown_and_expired_snapshot_require_new_query(client, expired):
    identifier = "0" * 32
    if expired:
        identifier = sample(client)["snapshot_id"]
        with db._SessionLocal() as session:
            session.get(db.CandidateSnapshotORM, identifier).expires_at = datetime.now(
                UTC
            ) - timedelta(seconds=1)
            session.commit()
    response = client.post("/api/refine", json={"snapshot_id": identifier})
    assert response.status_code == 404
    assert "重新查询" in response.json()["detail"]


def test_empty_snapshot_is_not_refinable(client):
    saved = db.snapshot_response({"query": "无结果", "offers": []})
    assert client.post("/api/refine", json={"snapshot_id": saved["snapshot_id"]}).status_code == 400


def test_new_feedback_excludes_saved_offer_without_rewriting_snapshot(client):
    saved = db.snapshot_response(
        {
            "query": "小米手环9 NFC版",
            "demo": True,
            "offers": [
                {
                    "platform": platform,
                    "platform_id": "snapshot-feedback-case",
                    "title": "小米手环9 NFC版",
                    "price": 199,
                }
                for platform in ("jd", "taobao")
            ],
        }
    )
    client.post("/api/feedback", json={"platform": "jd", "platform_id": "snapshot-feedback-case"})
    result = client.post("/api/refine", json={"snapshot_id": saved["snapshot_id"]}).json()
    assert [o["platform"] for o in result["offers"]] == ["taobao"]
    assert len(db.load_candidate_snapshot(saved["snapshot_id"])["offers"]) == 2
