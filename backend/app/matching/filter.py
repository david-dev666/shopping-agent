"""查询结果的相关性标注：确定性规则，不依赖 LLM。

原则：全部规则只打软标签，不剔除任何报价；由前端「排除标签」让用户自行过滤。
"""

import re

from app.matching.brands import BRAND_ALIASES, _brand_genuine, _compatible_context, extract_brand
from app.matching.identity import assess_offers
from app.matching.specs import extract_generation, extract_version
from app.models.offers import offer_key

# 竞品判定：query 品牌未命中这些词时，标题出现即视为其他品牌商品
RIVAL_BRANDS = [
    "小米",
    "xiaomi",
    "华为",
    "huawei",
    "荣耀",
    "honor",
    "联想",
    "lenovo",
    "amazfit",
    "华米",
    "苹果",
    "apple",
    "三星",
    "samsung",
    "oppo",
    "vivo",
    "一加",
    "佳明",
    "garmin",
    "小天才",
    "dido",
    "埃微",
]

# 二手 / 翻新特征（注：\b 对中文边界无效，用前后非数字断言）
SECOND_HAND_RE = re.compile(
    r"二手|\d+\s*成新|(?<![0-9])9[59]\s*新(?![0-9])|(?<!未)拆封|翻新|官翻|回收"
)

# 配件特征（标题只有这些、没有主体词时视为配件）
ACCESSORY_WORDS = [
    "表带",
    "腕带",
    "保护壳",
    "保护套",
    "保护膜",
    "贴膜",
    "钢化膜",
    "充电器",
    "充电线",
    "充电底座",
    "挂绳",
    "收纳",
    "贴纸",
    "腕带扣",
]

# 主体词（任一命中则不是纯配件）
SUBJECT_WORDS = ["手环", "手表", "band", "watch", " bracelet"]


# 规则 → 标签文案（既是软标签，也是前端「排除标签」使用的显示名）
REASON_LABELS = {
    "second_hand": "疑似二手",
    "rival": "其他品牌",
    "accessory": "配件",
    "off_brand": "品牌不明",
    "price_outlier": "价格异常",
    "low_sales": "销量偏低",
    "model_mismatch": "其他型号",
}

# 型号 token：字母数字混合且含数字的连续段（如 y7000x、rtx5060、手环9 中的纯数字不算）
MODEL_TOKEN_RE = re.compile(r"[a-z][a-z0-9]*\d[a-z0-9]*", re.I)

# 销量标签（相对判定，品类自适应）：销量低于中位数的该比例即标「销量偏低」
# 女装（中位 5）→ < 0 标不出；标品（中位 5 万）→ < 5000 标出，均合理
LOW_SALES_RATIO = 0.2


def _median(values: list[float]) -> float:
    vs = sorted(values)
    n = len(vs)
    if n == 0:
        return 0.0
    return vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2


# 价格离群阈值：低于全体中位数的该比例视为异常（如 SKU 显示的是配件最低价）
OUTLIER_RATIO = 0.3
# 样本至少这么多才做离群检测，避免小样本中位数失真
OUTLIER_MIN_SAMPLES = 6


def filter_offers(offers: list, query: str) -> tuple[list, dict, list]:
    """全部规则统一打软标签：命中即写 offer.tags，不再剔除任何报价。

    七个规则（型号不符 / 竞品 / 品牌不明 / 配件 / 二手 / 价格异常 / 销量偏低）
    一律只打标；由前端「排除标签」让用户自行过滤。
    返回值保留 (offers, stats, removed) 三元素签名，removed 恒为空（兼容旧调用方）。
    """
    brand = extract_brand(query)
    brand_alias = BRAND_ALIASES.get(brand, []) if brand else []

    stats = {
        "total": len(offers),
        "rival": 0,
        "accessory": 0,
        "off_brand": 0,
        "model_mismatch": 0,
        "second_hand": 0,
        "low_sales": 0,
        "price_outlier": 0,
    }
    removed: list = []

    def tag(o, reason: str) -> None:
        stats[reason] += 1
        label = REASON_LABELS[reason]
        o.tags = [t for t in (o.tags or []) if t != label] + [label]

    # 保留英文词边界，避免把 Xiaomi Band 9 拼成 xiaomiband9 这个伪型号。
    norm_query = re.sub(r"([a-z])[\s\-_]+(?=\d)", r"\1", query.lower())
    model_tokens = [
        t.lower()
        for t in MODEL_TOKEN_RE.findall(norm_query)
        if len(t) >= 4 and not re.fullmatch(r"(?:band|watch)\d+(?:pro)?", t, re.I)
    ]
    generation = extract_generation(query)
    version = extract_version(query)

    for o in offers:
        o.tags = [t for t in o.tags if t not in REASON_LABELS.values()]
        title = (o.title or "").lower()
        norm_title = re.sub(r"[\s\-_]", "", title)

        # 1. 型号不符：型号 token 缺失即其他型号（如搜 y7000x 来了老款拯救者）
        if model_tokens and not all(t in norm_title for t in model_tokens):
            tag(o, "model_mismatch")
        elif generation is not None:
            actual = extract_generation(title)
            same_brand = not brand or _brand_genuine(title, brand_alias)
            if same_brand and actual is not None and actual != generation:
                tag(o, "model_mismatch")
        actual_version = extract_version(title)
        if (
            version
            and actual_version
            and version != actual_version
            and REASON_LABELS["model_mismatch"] not in o.tags
        ):
            tag(o, "model_mismatch")

        # 2. 品牌冲突：query 有明确品牌时，标题须命中该品牌且不得出现竞品
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
                tag(o, "rival")
            elif not alias_hit:
                tag(o, "off_brand")

        # 3. 配件：有配件词但无主体词；或配件词出现在标题尾部区域
        has_subject = any(s in title for s in SUBJECT_WORDS)
        has_accessory = any(a in title for a in ACCESSORY_WORDS)
        # 赠品描述不等于商品主体；明确配件即使位于标题中段也应识别。
        main_title = re.split(r"赠送|赠品|附赠|赠|送", title, maxsplit=1)[0]
        main_accessory = any(a in main_title for a in ACCESSORY_WORDS)
        if main_accessory and not has_subject:
            tag(o, "accessory")
        elif has_accessory and main_accessory:
            tag(o, "accessory")

        # 4. 二手/翻新（标题 + 店铺文本）
        if SECOND_HAND_RE.search(title) or (o.shop and SECOND_HAND_RE.search(o.shop.lower())):
            tag(o, "second_hand")

    # 5. 价格异常：显著低于中位数（SKU 最低价陷阱）
    if len(offers) >= OUTLIER_MIN_SAMPLES:
        median = _median([o.price for o in offers])
        if median > 0:
            for o in offers:
                if o.price < median * OUTLIER_RATIO and median * OUTLIER_RATIO > 1:
                    tag(o, "price_outlier")

    # 6. 销量偏低：相对中位数（品类自适应，女装/标品同一规则）
    sales_known = [o.sales for o in offers if o.sales is not None]
    if len(sales_known) >= 4:
        sales_median = _median(sales_known)
        # 阈值不足 1 件时不判定，避免低销量品类（女装）满分标
        if sales_median * LOW_SALES_RATIO > 1:
            for o in offers:
                if o.sales is not None and o.sales < sales_median * LOW_SALES_RATIO:
                    tag(o, "low_sales")

    stats["kept"] = len(offers)
    assess_offers(offers, query)
    return offers, stats, removed


def apply_filters(offers: list, spec) -> list:
    """按前端筛选条件确定性缩小候选集（平台 / 规格 / 标签 / 价格）。

    与打标分离：打标是「给每条报价贴标签」，本函数是「按用户选择挑子集」。
    规格分组在传入的全量集合上计算，保证与前端展示的分组一致。
    """
    from app.matching.specs import group_specs

    result = list(offers)
    if spec.platforms:
        allowed = set(spec.platforms)
        result = [o for o in result if o.platform in allowed]
    if spec.exclude_tags:
        excluded = set(spec.exclude_tags)
        result = [o for o in result if not (set(o.tags or []) & excluded)]
    if spec.spec:
        ids = {offer_key(o) for o in group_specs(offers).get(spec.spec, [])}
        result = [o for o in result if offer_key(o) in ids]
    if spec.price_min is not None:
        result = [o for o in result if o.price >= spec.price_min]
    if spec.match_status:
        result = [
            o for o in result if o.match_report and o.match_report.status == spec.match_status
        ]
    if spec.price_max is not None:
        result = [o for o in result if o.price <= spec.price_max]
    return result


# 警示标签：带任一标签的报价在综合排序中应让位于未打标报价
WARN_TAGS = frozenset(REASON_LABELS.values())


def apply_tag_guard(rank_items: list, offers: list) -> list:
    """确定性兜底：带警示标签的报价不得排在未打标报价之前。

    排序与 LLM 给的 score 可能冲突，这里同步压低被降级项的 score，
    维持「分数与顺序一致」不变量（前端排名/分值环依赖它）。
    """
    clean: list = []
    flagged: list = []
    for it in rank_items:
        tags = set(offers[it["index"]].tags or [])
        (flagged if tags & WARN_TAGS else clean).append(it)
    if not clean or not flagged:
        return rank_items
    cap = min(it.get("score", 0) for it in clean) - 1
    demoted = []
    for i, it in enumerate(flagged):
        item = dict(it)
        item["score"] = max(0, cap - i)
        demoted.append(item)
    return clean + demoted
