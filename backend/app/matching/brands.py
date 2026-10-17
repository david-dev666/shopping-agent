"""Shared brand aliases and title-context rules; no model or network calls."""

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


COMPATIBLE_WORDS = ["适配", "兼容", "支持", "适用于"]


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
