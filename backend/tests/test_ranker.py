from unittest.mock import patch

from app.agents.ranker import _offers_text, _price_fallback, rank_offers
from app.models.offers import RawOffer


def _offers() -> list[RawOffer]:
    return [
        RawOffer(platform="jd", platform_id="1", title="小米手环9 旗舰", price=199.0, sales=10000),
        RawOffer(platform="pdd", platform_id="2", title="小米手环9 低价", price=159.0, sales=81000),
        RawOffer(
            platform="taobao", platform_id="3", title="小米手环9 普通", price=189.0, sales=500
        ),
    ]


def test_offers_text_contains_all_fields() -> None:
    text = _offers_text(_offers())
    assert "pdd" in text and "¥159.00" in text and "81000" in text


def test_price_fallback_orders_by_price() -> None:
    fb = _price_fallback(_offers())
    idx = [it["index"] for it in fb["items"]]
    # 价格升序：pdd(159) -> taobao(189) -> jd(199)
    assert idx == [1, 2, 0]
    assert fb["items"][0]["score"] >= fb["items"][-1]["score"]


def test_rank_offers_degrades_to_price_when_llm_fails() -> None:
    """LLM 持续输出坏 JSON 时降级为价格排序，不再抛异常。"""
    from app.agents import ranker as mod

    class BadLLM:
        def invoke(self, _: str):
            return type("M", (), {"content": "不是 JSON"})()

    with (
        patch.object(mod, "get_settings") as gs,
    ):
        gs.return_value.llm_api_key = "k"
        gs.return_value.llm_base_url = ""
        gs.return_value.llm_model = "m"
        with patch.object(mod, "ChatOpenAI", return_value=BadLLM()):
            result = rank_offers("小米手环9", _offers())
    idx = [it["index"] for it in result["items"]]
    assert idx == [1, 2, 0]  # 价格升序兜底
    assert "不可用" in result["summary"]


def test_rank_offers_invalid_indexes_corrected() -> None:
    """LLM 返回越界/缺失下标时，确定性代码补齐。"""
    from app.agents import ranker as mod

    good_json = (
        '{"items": [{"index": 1, "score": 90, "reason": "ok"},'
        ' {"index": 99, "score": 80, "reason": "x"}], "summary": "s"}'
    )

    class GoodLLM:
        def invoke(self, _: str):
            return type("M", (), {"content": good_json})()

    with patch.object(mod, "get_settings") as gs:
        gs.return_value.llm_api_key = "k"
        gs.return_value.llm_base_url = ""
        gs.return_value.llm_model = "m"
        with patch.object(mod, "ChatOpenAI", return_value=GoodLLM()):
            result = rank_offers("小米手环9", _offers())
    idx = {it["index"] for it in result["items"]}
    assert idx == {0, 1, 2}  # 越界的 99 被丢，缺失的 0/2 被补齐
