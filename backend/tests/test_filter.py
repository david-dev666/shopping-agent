from app.matching.filter import filter_offers
from app.models.offers import RawOffer


def _offer(title: str, price: float = 100.0) -> RawOffer:
    return RawOffer(platform="jd", platform_id="1", title=title, price=price)


def test_second_hand_filtered() -> None:
    offers = [
        _offer("99 新小米手环9 标准NFC 二手非全新"),
        _offer("小米手环9 NFC 全新正品"),
    ]
    kept, stats, removed = filter_offers(offers, "小米手环9")
    assert stats["second_hand"] == 1
    assert len(kept) == 1
    assert removed[0]["reason"] == "second_hand"


def test_rival_brand_filtered() -> None:
    offers = [
        _offer("华为手环10 智能运动"),
        _offer("小米手环9 黑色"),
    ]
    kept, stats, _ = filter_offers(offers, "小米手环9")
    assert stats["rival"] == 1
    assert len(kept) == 1


def test_accessory_filtered() -> None:
    offers = [
        _offer("小米手环9 专用表带 硅胶"),
        _offer("小米手环9 智能手环"),
    ]
    kept, stats, _ = filter_offers(offers, "小米手环9")
    assert stats["accessory"] >= 1
    assert len(kept) == 1


def test_compatible_context_not_rival() -> None:
    offers = [_offer("小米手环9 适配华为手机")]
    kept, _, _ = filter_offers(offers, "小米手环9")
    assert len(kept) == 1


def test_no_brand_query_keeps() -> None:
    offers = [_offer("华为手环10"), _offer("联想手表")]
    kept, stats, _ = filter_offers(offers, "手环9")
    # query 无品牌：不做品牌过滤，仅二手/配件规则生效
    assert len(kept) == 2
