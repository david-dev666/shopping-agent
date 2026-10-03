from app.matching.specs import extract_spec, group_specs
from app.models.offers import RawOffer


def _offer(title: str, price: float = 100.0) -> RawOffer:
    return RawOffer(platform="jd", platform_id=title[:8], title=title, price=price)


def test_extract_pro() -> None:
    assert extract_spec("小米手环9Pro 智能运动") == "Pro"


def test_extract_nfc() -> None:
    assert extract_spec("小米手环9 NFC版 黑色") == "NFC版"


def test_extract_ceramic() -> None:
    assert extract_spec("小米手环9陶瓷特别版") == "陶瓷版"


def test_extract_none() -> None:
    assert extract_spec("小米手环9 标准版") is None


def test_priority_pro_over_nfc() -> None:
    # Pro 优先于 NFC（更高级别的版本区分）
    assert extract_spec("小米手环9 Pro NFC") == "Pro"


def test_group_specs_orders_by_min_price() -> None:
    offers = [
        _offer("小米手环9 标准版", 199.0),
        _offer("小米手环9 Pro", 259.0),
        _offer("小米手环9 Pro 高配", 279.0),
        _offer("小米手环9 NFC版", 229.0),
    ]
    groups = group_specs(offers)
    # 组间按最低价升序：NFC(229) < Pro(259) < 其他(199)? 其他组最低价 199 应排最前
    names = list(groups.keys())
    assert groups["Pro"] and len(groups["Pro"]) == 2
    mins = [min(o.price for o in groups[n]) for n in names]
    assert mins == sorted(mins)


def test_group_specs_other_bucket() -> None:
    offers = [_offer("小米手环9 标准版"), _offer("小米手环9Pro")]
    groups = group_specs(offers)
    assert "其他" in groups and "Pro" in groups
    assert len(groups["其他"]) == 1
