from app.matching.filter import filter_offers
from app.models.offers import RawOffer


def _offer(title: str, price: float = 100.0, sales: int | None = None) -> RawOffer:
    return RawOffer(platform="jd", platform_id="1", title=title, price=price, sales=sales)


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


def test_price_outlier_filtered() -> None:
    # 模拟淘宝 SKU 最低价：主体商品标题但价格是配件（表带 9 元）
    offers = [_offer("小米手环9 陶瓷特别版 智能手环", price=9.0)] + [
        _offer(f"小米手环9 标准版 正品{i}号店", price=170 + i * 5) for i in range(9)
    ]
    kept, stats, removed = filter_offers(offers, "小米手环9")
    assert stats["price_outlier"] == 1
    assert removed[0]["reason"] == "price_outlier"
    assert len(kept) == 9


def test_price_outlier_needs_samples() -> None:
    # 样本不足不做离群检测：一个低价 + 两个正常价，低价保留
    offers = [
        _offer("小米手环9 促销", price=20.0),
        _offer("小米手环9 A", price=180.0),
        _offer("小米手环9 B", price=185.0),
    ]
    kept, stats, _ = filter_offers(offers, "小米手环9")
    assert stats["price_outlier"] == 0
    assert len(kept) == 3


def test_normal_promo_not_outlier() -> None:
    # 正常促销价（中位数的 60%）不应被剔除
    offers = [_offer("小米手环9 百亿补贴", price=110.0)] + [
        _offer(f"小米手环9 正品{i}", price=175 + i * 5) for i in range(8)
    ]
    kept, stats, _ = filter_offers(offers, "小米手环9")
    assert stats["price_outlier"] == 0
    assert any(o.price == 110.0 for o in kept)


def test_low_sales_filtered() -> None:
    # 二手卖家挂正品标题：销量已知且极低 → 剔除
    offers = [
        _offer("小米手环9NFC版正品跑步游泳", price=168.0, sales=105),
        _offer("小米手环9 标准版 官方", price=199.0, sales=460000),
    ]
    kept, stats, removed = filter_offers(offers, "小米手环9")
    assert stats["low_sales"] == 1
    assert removed[0]["reason"] == "low_sales"
    assert len(kept) == 1


def test_unknown_sales_kept() -> None:
    # 销量未知不判定，避免误杀（如新品、京东联盟无销量字段）
    offers = [_offer("小米手环9 全新上市", price=199.0, sales=None)]
    kept, stats, _ = filter_offers(offers, "小米手环9")
    assert stats["low_sales"] == 0
    assert len(kept) == 1


def test_model_token_mismatch_filtered() -> None:
    # 搜 y7000x：老款拯救者（标题无 y7000x）被剔除
    offers = [
        _offer("联想拯救者R7000 游戏本", price=6599.0),
        _offer("联想拯救者Y7000X 2026款 RTX5060", price=11298.0),
        _offer("拯救者Y7000P 2025款", price=8999.0),
    ]
    kept, stats, removed = filter_offers(offers, "拯救者y7000x")
    assert stats["model_mismatch"] == 2
    assert removed[0]["reason"] == "model_mismatch"
    assert len(kept) == 1 and kept[0].price == 11298.0


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
