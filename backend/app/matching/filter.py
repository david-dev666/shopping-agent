"""查询结果的相关性过滤：确定性规则，不依赖 LLM。

原则：宁可漏掉边缘商品，不让明显不相关的（二手/竞品/配件）混进比价结果。
"""

import re

# 品牌词典（query 命中品牌后，标题必须兼容该品牌且不得出现竞品主词）
BRAND_ALIASES = {
    "小米": ["小米", "xiaomi", "xiaomi"],
    "华为": ["华为", "huawei", "huawei"],
    "荣耀": ["荣耀", "honor"],
    "苹果": ["苹果", "apple"],
    "三星": ["三星", "samsung"],
    "oppo": ["oppo"],
    "vivo": ["vivo"],
}

# 竞品判定：query 品牌未命中这些词时，标题出现即视为其他品牌商品
RIVAL_BRANDS = [
    "小米", "xiaomi", "华为", "huawei", "荣耀", "honor", "联想", "lenovo",
    "amazfit", "华米", "苹果", "apple", "三星", "samsung", "oppo", "vivo",
    "一加", "佳明", "garmin", "小天才", "dido", "埃微",
]

# “适配/兼容”语境词：其后出现的品牌词是卖点描述，不算竞品
COMPATIBLE_WORDS = ["适配", "兼容", "支持", "适用于"]

# 二手 / 翻新特征（注：\b 对中文边界无效，用前后非数字断言）
SECOND_HAND_RE = re.compile(
    r"二手|9[59]\s*成新|(?<![0-9])9[59]\s*新(?![0-9])|拆封|仅拆封|翻新|官翻|回收"
)

# 配件特征（标题只有这些、没有主体词时视为配件）
ACCESSORY_WORDS = [
    "表带", "腕带", "保护壳", "保护套", "保护膜", "贴膜", "钢化膜",
    "充电器", "充电线", "充电底座", "挂绳", "收纳", "贴纸", "腕带扣",
]

# 主体词（任一命中则不是纯配件）
SUBJECT_WORDS = ["手环", "手表", "band", "watch", " bracelet"]


def extract_brand(query: str) -> str | None:
    """从查询词提取明确品牌（最长优先）。"""
    best = None
    for brand, aliases in BRAND_ALIASES.items():
        if any(a in query.lower() for a in aliases):
            if best is None or len(brand) > len(best):
                best = brand
    return best


def _compatible_context(title: str, word: str) -> bool:
    """判断品牌词 word 首次出现位置是否在“适配/兼容”语境里。"""
    idx = title.find(word)
    prefix = title[max(0, idx - 12) : idx]
    return any(c in prefix for c in COMPATIBLE_WORDS)


def _brand_genuine(title: str, brand_alias: list[str]) -> bool:
    """品牌词在标题中存在任一非“适配/兼容”语境的出现位置，即视为该品牌商品。

    例如“小米手环9 适配华为手机”：小米开头（非兼容语境）→ 真小米；
    “联想手表 适配苹果华为小米荣耀”：小米仅在兼容语境 → 非小米商品。
    """
    for a in brand_alias:
        start = 0
        while True:
            idx = title.find(a, start)
            if idx == -1:
                break
            prefix = title[max(0, idx - 12) : idx]
            if not any(c in prefix for c in COMPATIBLE_WORDS):
                return True
            start = idx + 1
    return False


REASON_LABELS = {
    "second_hand": "二手/翻新",
    "rival": "其他品牌",
    "accessory": "配件",
    "off_brand": "品牌不明",
}


def filter_offers(offers: list, query: str) -> tuple[list, dict, list]:
    """过滤不相关 offer，返回 (过滤后列表, 统计信息, 被剔除列表)。

    被剔除列表元素为 {"offer": ..., "reason": ...}，前端可折叠展示，
    保持过滤过程透明、可人工复核。
    """
    brand = extract_brand(query)
    brand_alias = BRAND_ALIASES.get(brand, []) if brand else []

    stats = {"total": len(offers), "second_hand": 0, "rival": 0, "accessory": 0, "off_brand": 0}
    kept: list = []
    removed: list = []

    def drop(o, reason: str) -> None:
        stats[reason] += 1
        removed.append({"offer": o, "reason": reason})

    for o in offers:
        title = (o.title or "").lower()

        # 1. 二手/翻新
        if SECOND_HAND_RE.search(title):
            drop(o, "second_hand")
            continue

        # 2. 品牌冲突：query 有明确品牌
        if brand:
            # 品牌词必须出现在非“适配/兼容”语境，才算真正的品牌商品
            alias_hit = _brand_genuine(title, brand_alias)
            rival_hit = None
            for r in RIVAL_BRANDS:
                if r in brand_alias:
                    continue
                if r in title and not _compatible_context(title, r):
                    rival_hit = r
                    break
            if rival_hit and not alias_hit:
                drop(o, "rival")
                continue
            if not alias_hit:
                # query 品牌未命中：无法确认是同品牌商品
                drop(o, "off_brand")
                continue

        # 3. 配件：有配件词但无主体词
        has_subject = any(s in title for s in SUBJECT_WORDS)
        has_accessory = any(a in title for a in ACCESSORY_WORDS)
        if has_accessory and not has_subject:
            drop(o, "accessory")
            continue
        # 配件词位于标题尾部区域：商品本体大概率是配件（如“小米手环9 专用表带”）
        if has_accessory and has_subject:
            acc_idx = max(title.find(a) for a in ACCESSORY_WORDS if a in title)
            if acc_idx > len(title) * 0.6:
                drop(o, "accessory")
                continue

        kept.append(o)

    stats["kept"] = len(kept)
    return kept, stats, removed
