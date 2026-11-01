from unittest.mock import patch

from app.agents.ranker import _offers_text, rank_offers
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


def test_invalid_ranking_returns_model_error() -> None:
    import pytest

    from app.agents import ranker as mod
    from app.agents.llm_utils import ModelResponseError

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
            with pytest.raises(ModelResponseError):
                rank_offers("小米手环9", _offers())


def test_rank_offers_invalid_indexes_rejected() -> None:
    import pytest

    from app.agents import ranker as mod
    from app.agents.llm_utils import ModelResponseError

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
            with pytest.raises(ModelResponseError):
                rank_offers("小米手环9", _offers())
