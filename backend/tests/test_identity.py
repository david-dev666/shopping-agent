"""Development regressions, not an independent accuracy benchmark."""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agents.graph import AgentState, node_decide, node_match, node_recommend, run_refine
from app.agents.ranker import rank_offers
from app.demo_data import demo_chat_response, demo_refine_response
from app.main import app
from app.matching.filter import apply_filters, filter_offers
from app.matching.identity import assess_match, extract_identity
from app.models.filters import FilterSpec
from app.models.offers import RawOffer


@pytest.mark.parametrize(
    ("query", "title", "status"),
    [
        ("小米手环9 NFC版", "Xiaomi Band 9 NFC版 黑色", "compatible"),
        ("小米手环9 标准版", "小米手环9 普通版", "compatible"),
        ("小米手环9 Pro", "小米手环9Pro长续航 NFC支付", "compatible"),
        ("小米手环9 Pro", "小米手环9Pro 支持NFC/蓝牙 黑色白色可选", "compatible"),
        ("小米手环9 不要NFC", "小米手环9Pro 支持NFC/蓝牙", "conflict"),
        ("小米手环9 陶瓷版", "小米手环9陶瓷特别版 支持NFC", "compatible"),
        ("小米手环9", "小米手环10", "conflict"),
        ("小米手环9 NFC版", "小米手环9 标准版", "conflict"),
        ("小米手环9 NFC版", "小米手环9 不支持NFC", "conflict"),
        ("小米手环9 不要Pro", "小米手环9 Pro", "conflict"),
        ("小米手环9 不要Pro", "小米手环9 标准版", "compatible"),
        ("小米手环9 不要二手", "小米手环9 二手", "conflict"),
        ("小米手环9 黑色", "小米手环9 蓝色", "conflict"),
        ("小米手环9 全新", "小米手环9 官翻", "conflict"),
        ("小米手环9", "华为手环9", "conflict"),
        ("小米手环9", "小米手表9", "conflict"),
        ("拯救者Y7000X", "拯救者 Y7000P", "conflict"),
        ("小米手环9", "小米手环9/10 NFC运动手环", "ambiguous"),
        ("小米手环9", "小米手环9智能运动健康10nfc血氧睡眠心率监测陶瓷特别版", "ambiguous"),
        ("小米手环9", "小米手环9/9NFC/Pro运动健康手环", "ambiguous"),
        ("小米手环9", "小米手环9/NFC 多款可选", "ambiguous"),
        ("小米手环9 标准版", "小米手环9 标准版、NFC版任选", "ambiguous"),
        ("小米手环9 黑色", "小米手环9 黑色/白色任选", "ambiguous"),
        ("小米手环9 NFC版", "小米手环9 黑色", "insufficient"),
        ("小米手环9", "智能手环 长续航", "insufficient"),
        ("选个运动手环", "小米手环9 标准版", "insufficient"),
        ("小米手环9/10", "小米手环9", "insufficient"),
        ("小米手环9或10都行", "小米手环9", "compatible"),
    ],
)
def test_title_evidence_states(query, title, status):
    report = assess_match(query, title)
    assert report.status == status
    assert not report.sku_verified and not report.price_verified
    assert report.blocks_recommendation == (status in {"conflict", "ambiguous"})
    for field in report.checks:
        assert all(snippet.lower() in title.lower() for snippet in field.title_evidence)


def test_missing_version_is_unknown_not_standard():
    report = assess_match("小米手环9 NFC版", "小米手环9 黑色")
    version = next(c for c in report.checks if c.field == "version")
    assert version.status == "unknown"
    assert not version.observed
    assert extract_identity("小米手环9 未拆封").condition == []


def test_compatibility_brand_does_not_become_product_brand():
    report = assess_match("小米手环9", "华为手环9 适配小米手机")
    assert next(c for c in report.checks if c.field == "brand").observed == ["华为"]
    assert report.status == "conflict"


def test_normalized_search_cannot_drop_original_variant_requirement():
    state = AgentState(query="小米手环9 NFC版", intent={"product": "小米手环9"},
                       offers=[offer("小米手环9标准版")])
    result = node_match(state)
    assert "其他型号" in result["offers"][0].tags
    assert result["offers"][0].match_report.status == "conflict"


class Reply:
    def __init__(self, worth="buy"):
        self.prompts = []
        self.worth = worth

    def invoke(self, prompt):
        self.prompts.append(prompt)
        data = {"worth": self.worth, "confidence": 99, "reason": "最低价就买它",
                "items": [{"index": 0, "score": 99, "reason": "最低价"},
                          {"index": 1, "score": 90, "reason": "备选"}]}
        return type("Message", (), {"content": json.dumps(data)})()


def offer(title, price=199, key="1"):
    return RawOffer(platform="jd", platform_id=key, title=title, price=price)


def test_model_cannot_make_mixed_listing_the_pick_and_tail_is_preserved():
    tail = "小米手环9 NFC版 " + "长续航健康监测" * 15 + "标准版/NFC版任选"
    mixed, clear = offer(tail, 99), offer("小米手环9 NFC版", 199, "2")
    state = AgentState(query="小米手环9 NFC版", offers=[mixed, clear])
    llm = Reply()
    with patch("app.agents.graph._llm", return_value=llm):
        result = node_decide(state)
    assert tail in llm.prompts[0]
    assert result["rank_items"][0]["index"] == 1
    assert result["decision"]["worth"] == "wait"
    with patch("app.agents.graph.save_trace"):
        response = node_recommend(state.model_copy(update=result))
    assert response["top_pick"]["platform_id"] == "2"


def test_missing_explicit_spec_cannot_support_buy_claim():
    state = AgentState(query="小米手环9 NFC版", offers=[offer("小米手环9")])
    with patch("app.agents.graph._llm", return_value=Reply()):
        result = node_decide(state)
    assert result["decision"]["worth"] == "wait"
    assert result["decision"]["confidence"] == 0
    # An evidence downgrade must not turn an existing skip into a conditional pick.
    with patch("app.agents.graph._llm", return_value=Reply("skip")):
        skipped = node_decide(state)
    assert skipped["decision"]["worth"] == "skip"
    with patch("app.agents.graph.save_trace"):
        response = node_recommend(state.model_copy(update=skipped))
    assert response["top_pick"] is None


def test_known_version_precedes_cheaper_unknown_version():
    state = AgentState(query="小米手环9 NFC版", offers=[
        offer("小米手环9", 99), offer("小米手环9 NFC版", 199, "2")])
    with patch("app.agents.graph._llm", return_value=Reply()):
        result = node_decide(state)
    assert result["rank_items"][0]["index"] == 1


def test_negative_version_and_feature_are_not_positive_requirements():
    report = assess_match("小米手环9 不需要NFC", "小米手环9 Pro支持NFC")
    assert report.status == "conflict"
    feature = next(c for c in report.checks if c.field == "feature")
    assert feature.requested == []
    assert feature.excluded == ["NFC"]


def test_all_mixed_or_conflicting_candidates_have_no_pick():
    state = AgentState(query="小米手环9 NFC版",
                       offers=[offer("小米手环9/10 NFC版"), offer("小米手环9标准版", key="2")])
    with patch("app.agents.graph._llm", return_value=None):
        result = node_decide(state)
    with patch("app.agents.graph.save_trace"):
        response = node_recommend(state.model_copy(update=result))
    assert response["top_pick"] is None
    assert "规格证据" in result["decision"]["reason"]


def test_refine_recomputes_forged_client_evidence_from_original_query():
    candidate = offer("小米手环9标准版")
    candidate.match_report = assess_match("小米手环9标准版", candidate.title)
    assert candidate.match_report.status == "compatible"
    with patch("app.agents.graph._llm", return_value=None):
        result = run_refine("小米手环9 NFC版", [candidate], intent={"product": "小米手环9"})
    assert result["top_pick"] is None
    assert result["offers"][0].match_report.status == "conflict"


def test_rank_endpoint_path_rechecks_and_demotes_mixed_listing():
    candidates = [offer("小米手环9/10 NFC版", 99), offer("小米手环9 NFC版", key="2")]
    with patch("app.agents.ranker.ChatOpenAI", return_value=Reply()), \
         patch("app.agents.ranker.get_settings") as settings:
        settings.return_value.llm_api_key = ""
        result = rank_offers("小米手环9 NFC版", candidates)
    assert result["items"][0]["index"] == 1


def test_sample_and_http_serialization_include_real_title_evidence():
    data = demo_chat_response()
    assert all(o["match_report"]["source"] == "title_rules_v1" for o in data["offers"])
    for candidate in data["offers"]:
        report = candidate["match_report"]
        assert report["checks"]
        assert not {"query", "requested", "observed"}.intersection(report)
    assert data["top_pick"]["match_report"]["status"] not in {"conflict", "ambiguous"}
    mixed = demo_refine_response({"match_status": "ambiguous"})
    assert mixed["offers"] and mixed["top_pick"] is None
    assert "混卖" in mixed["decision"]["reason"]
    with TestClient(app) as client:
        result = client.post("/api/query", json={"query": "小米手环9", "data_mode": "sample"})
    assert result.status_code == 200
    assert result.json()["offers"][0]["match_report"]["price_verified"] is False


def test_evidence_filter_matches_after_refine_recomputes_reports():
    candidates = [offer("小米手环9/10 NFC版", 99), offer("小米手环9 NFC版", 199, "2")]
    normalized, _, _ = filter_offers(candidates, "小米手环9 NFC版")
    spec = FilterSpec(match_status="compatible")
    assert not spec.is_empty()
    assert [o.platform_id for o in apply_filters(normalized, spec)] == ["2"]
    with patch("app.agents.graph._llm", return_value=None):
        result = run_refine("小米手环9 NFC版", candidates, spec.model_dump())
    assert [o.platform_id for o in result["offers"]] == ["2"]
    assert result["top_pick"]["platform_id"] == "2"
