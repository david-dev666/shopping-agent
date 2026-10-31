import pytest

from app.matching.filter import filter_offers
from app.matching.specs import extract_version
from app.models.offers import RawOffer


@pytest.mark.parametrize("text,version", [
    ("小米手环9Pro运动手环", "Pro"),
    ("小米手环9NFC智能手环", "NFC版"),
    ("professional 手环", None),
    ("nfcable 智能手表", None),
])
def test_version_words_use_latin_boundaries(text, version):
    assert extract_version(text) == version


@pytest.mark.parametrize("title,accessory", [
    ("荣耀手环9标准版+贴膜*2", False),
    ("荣耀手环9标准版＋充电线", False),
    ("荣耀手环9智能运动时尚腕带轻薄双曲面", False),
    ("荣耀手环9专用腕带+贴膜*2", True),
    ("荣耀手环9时尚腕带替换表带", True),
])
def test_main_device_bundle_and_accessory_listing_remain_distinct(title, accessory):
    offer = RawOffer(platform="jd", platform_id="1", title=title, price=100)
    result, _, _ = filter_offers([offer], "荣耀手环9")
    assert ("配件" in result[0].tags) == accessory


@pytest.mark.parametrize("brand", ["鱼跃", "测立康"])
def test_observed_health_watch_brands_are_distinguished_from_missing_brands(brand):
    offer = RawOffer(platform="jd", platform_id="1", title=f"{brand}健康监测手表", price=100)
    result, _, _ = filter_offers([offer], "华为手环9")
    assert "其他品牌" in result[0].tags
    assert "品牌不明" not in result[0].tags


def test_frozen_real_title_regression_does_not_fall_below_target():
    from pathlib import Path

    from eval.rules import evaluate, load_cases

    path = Path(__file__).resolve().parents[1] / "eval/live_titles_20261031.jsonl"
    assert evaluate(load_cases(path))["micro"]["f1"] >= 0.96
