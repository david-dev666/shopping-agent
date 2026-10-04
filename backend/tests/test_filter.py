from app.matching.filter import apply_tag_guard, filter_offers
from app.models.offers import RawOffer


def _offer(title: str, price: float = 100.0, sales: int | None = None) -> RawOffer:
    return RawOffer(platform="jd", platform_id="1", title=title, price=price, sales=sales)


def test_second_hand_tagged_not_removed() -> None:
    # 软规则：二手只打标不剔除，由用户交互过滤
    offers = [
        _offer("99 新小米手环9 标准NFC 二手非全新"),
        _offer("小米手环9 NFC 全新正品"),
    ]
    kept, stats, removed = filter_offers(offers, "小米手环9")
    assert stats["second_hand"] == 1
    assert len(kept) == 2
    assert "疑似二手" in kept[0].tags
    assert kept[1].tags == []
    assert removed == []


def test_rival_brand_tagged() -> None:
    offers = [
        _offer("华为手环10 智能运动"),
        _offer("小米手环9 黑色"),
    ]
    kept, stats, removed = filter_offers(offers, "小米手环9")
    assert stats["rival"] == 1
    assert len(kept) == 2
    assert "其他品牌" in kept[0].tags
    assert removed == []


def test_accessory_tagged() -> None:
    offers = [
        _offer("小米手环9 专用表带 硅胶"),
        _offer("小米手环9 智能手环"),
    ]
    kept, stats, removed = filter_offers(offers, "小米手环9")
    assert stats["accessory"] >= 1
    assert len(kept) == 2
    assert "配件" in kept[0].tags
    assert removed == []


def test_compatible_context_not_rival() -> None:
    offers = [_offer("小米手环9 适配华为手机")]
    kept, _, _ = filter_offers(offers, "小米手环9")
    assert len(kept) == 1


def test_no_brand_query_keeps() -> None:
    offers = [_offer("华为手环10"), _offer("联想手表")]
    kept, stats, _ = filter_offers(offers, "手环9")
    # query 无品牌：不做品牌过滤，仅二手/配件规则生效
    assert len(kept) == 2


def test_price_outlier_tagged_not_removed() -> None:
    # 软规则：SKU 低价陷阱只打标，用户可自行排除
    offers = [_offer("小米手环9 陶瓷特别版 智能手环", price=9.0)] + [
        _offer(f"小米手环9 标准版 正品{i}号店", price=170 + i * 5) for i in range(9)
    ]
    kept, stats, removed = filter_offers(offers, "小米手环9")
    assert stats["price_outlier"] == 1
    assert len(kept) == 10
    assert "价格异常" in kept[0].tags
    assert not any(t for t in kept[1].tags if t == "价格异常")
    assert removed == []


def test_price_outlier_needs_samples() -> None:
    # 样本不足不做离群检测：一个低价 + 两个正常价，无标签
    offers = [
        _offer("小米手环9 促销", price=20.0),
        _offer("小米手环9 A", price=180.0),
        _offer("小米手环9 B", price=185.0),
    ]
    kept, stats, _ = filter_offers(offers, "小米手环9")
    assert stats["price_outlier"] == 0
    assert kept[0].tags == []


def test_normal_promo_not_outlier() -> None:
    # 正常促销价（中位数的 60%）不应被剔除
    offers = [_offer("小米手环9 百亿补贴", price=110.0)] + [
        _offer(f"小米手环9 正品{i}", price=175 + i * 5) for i in range(8)
    ]
    kept, stats, _ = filter_offers(offers, "小米手环9")
    assert stats["price_outlier"] == 0
    assert any(o.price == 110.0 for o in kept)


def test_low_sales_tagged() -> None:
    # 软规则：3C 标品场景低销量打标不剔除
    offers = [
        _offer("小米手环9NFC版正品跑步游泳", price=168.0, sales=105),
        _offer("小米手环9 A店", price=199.0, sales=460000),
        _offer("小米手环9 B店", price=205.0, sales=380000),
        _offer("小米手环9 C店", price=210.0, sales=520000),
    ]
    kept, stats, removed = filter_offers(offers, "小米手环9")
    assert stats["low_sales"] == 1
    assert len(kept) == 4
    assert "销量偏低" in kept[0].tags
    assert removed == []


def test_low_sales_dress_category_not_filtered() -> None:
    # 女装低销量品类：中位销量本就低（<1000），不触发销量过滤，整类保留
    offers = [
        _offer("绿野仙踪森系复古连衣裙 A", price=129.0, sales=2),
        _offer("绿野仙踪森系复古连衣裙 B", price=149.0, sales=7),
        _offer("绿野仙踪森系复古连衣裙 C", price=168.0, sales=0),
        _offer("绿野仙踪森系复古连衣裙 D", price=199.0, sales=35),
    ]
    kept, stats, _ = filter_offers(offers, "绿野仙踪复古系连衣裙")
    assert stats["low_sales"] == 0
    assert len(kept) == 4


def test_unknown_sales_kept() -> None:
    # 销量未知不判定，避免误杀（如新品、京东联盟无销量字段）
    offers = [_offer("小米手环9 全新上市", price=199.0, sales=None)]
    kept, stats, _ = filter_offers(offers, "小米手环9")
    assert stats["low_sales"] == 0
    assert len(kept) == 1


def test_model_token_mismatch_tagged() -> None:
    # 搜 y7000x：老款/其他型号打「其他型号」标签，不再剔除
    offers = [
        _offer("联想拯救者R7000 游戏本", price=6599.0),
        _offer("联想拯救者Y7000X 2026款 RTX5060", price=11298.0),
        _offer("拯救者Y7000P 2025款", price=8999.0),
    ]
    kept, stats, removed = filter_offers(offers, "拯救者y7000x")
    assert stats["model_mismatch"] == 2
    assert len(kept) == 3
    assert "其他型号" in kept[0].tags
    assert kept[1].tags == []
    assert removed == []


def test_model_token_case_and_space_insensitive() -> None:
    # 大小写 / 空格差异不误杀
    offers = [_offer("联想 拯救者 Y7000X 2026款")]
    kept, stats, _ = filter_offers(offers, "拯救者 Y7000X")
    assert stats["model_mismatch"] == 0
    assert len(kept) == 1


def test_no_model_token_no_rule() -> None:
    # query 无型号 token（纯中文/纯数字）不启用该规则
    offers = [_offer("小米手环9 标准版"), _offer("小米手环10 NFC")]
    kept, stats, _ = filter_offers(offers, "小米手环9")
    assert stats["model_mismatch"] == 0


def test_nothing_is_ever_removed() -> None:
    # 全量软标签：任何输入都不再产生剔除
    offers = [
        _offer("华为手环10 智能运动"),
        _offer("小米手环9 专用表带 硅胶"),
        _offer("小米手环9 99新 二手"),
        _offer("联想拯救者R7000 游戏本"),
    ]
    kept, _, removed = filter_offers(offers, "小米手环9 拯救者y7000x")
    assert removed == []
    assert len(kept) == 4


def test_tag_guard_demotes_tagged_below_clean() -> None:
    # 低销量（打标）不得排在未打标的高销量同款之前；分数同步压低以保持一致
    offers = [_offer("小米手环9 高销量", sales=50000), _offer("小米手环9 低销量")]
    offers[1].tags = ["销量偏低"]
    items = [
        {"index": 1, "score": 84, "reason": "价格低"},
        {"index": 0, "score": 60, "reason": "销量高"},
    ]
    out = apply_tag_guard(items, offers)
    assert [it["index"] for it in out] == [0, 1]
    assert out[0]["score"] > out[1]["score"]


def test_tag_guard_noop_when_all_tagged() -> None:
    # 全部打标（同类目普遍低销量）：保持原顺序，不误伤
    offers = [_offer("小米手环9 A"), _offer("小米手环9 B")]
    offers[0].tags = ["疑似二手"]
    offers[1].tags = ["销量偏低"]
    items = [{"index": 0, "score": 90}, {"index": 1, "score": 80}]
    out = apply_tag_guard(items, offers)
    assert [it["index"] for it in out] == [0, 1]
