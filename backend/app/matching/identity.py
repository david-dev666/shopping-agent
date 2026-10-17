"""Conservative title matching, initially focused on wearable generations and variants.

Keep evidence from the complete original title. Absence is unknown, not a match.
Do not infer a standard variant from a missing NFC/Pro word, or a selected SKU from
a multi-variant search card. This module performs no network/model calls.
"""

import re

from app.matching.brands import BRAND_ALIASES, _brand_genuine
from app.models.identity import FieldMatch, MatchReport, ProductIdentity
from app.models.offers import RawOffer

LABELS = {
    "brand": "品牌",
    "category": "品类",
    "model": "型号",
    "generation": "代数",
    "version": "版本",
    "feature": "功能",
    "color": "颜色",
    "condition": "成色",
}
SERIES = re.compile(
    r"(?:手环|手表|band|watch)\s*(\d{1,2}(?:\s*(?:pro|nfc))?"
    r"(?:\s*[/、]\s*(?:(?:手环|手表|band|watch)\s*)?\d{1,2}"
    r"(?:\s*(?:pro|nfc))?)*)",
    re.I,
)
MODEL = re.compile(r"(?<![a-z0-9])(?:y\d{4}[a-z]*|rtx\s*\d{4}[a-z]*)(?![a-z0-9])", re.I)
NEGATION = re.compile(
    r"(?:不要|不接受|不考虑|不需要|不是|不买|不选|排除|不支持|不带|没有|非|无)\s*$"
)


def _positive(text: str, start: int) -> bool:
    return not NEGATION.search(text[max(0, start - 8) : start])


def extract_identity(text: str) -> ProductIdentity:
    identity = ProductIdentity()

    def add(field: str, value: str, evidence: str, excluded: bool = False) -> None:
        values = identity.excluded.setdefault(field, []) if excluded else getattr(identity, field)
        if value not in values:
            values.append(value)
        snippets = identity.evidence.setdefault(f"excluded.{field}" if excluded else field, [])
        if evidence not in snippets:
            snippets.append(evidence)

    lower = text.lower()
    for brand, aliases in BRAND_ALIASES.items():
        if _brand_genuine(lower, aliases):
            alias = next(a for a in aliases if a in lower)
            add("brand", brand, text[lower.index(alias) : lower.index(alias) + len(alias)])
    # Marketing text may call a band a watch as well; use the first explicit subject.
    category = re.search(r"手环|手表|(?<![a-z])band(?![a-z])|(?<![a-z])watch(?![a-z])", lower)
    if category:
        add("category", "手环" if category[0] in {"手环", "band"} else "手表", category[0])
    series_matches = list(SERIES.finditer(text))
    for match in series_matches:
        for generation in re.findall(r"\d+", match[1]):
            add("generation", str(int(generation)), match[0])
    if series_matches:
        # A search card may repeat a bare variant later: 手环9 … 10NFC.
        for match in re.finditer(r"(?<![a-z0-9])(\d{1,2})\s*(?:nfc|pro)(?![a-z])", text, re.I):
            prefix = text[max(0, match.start() - 12):match.start()]
            if not re.search(r"适配|兼容|支持|适用于", prefix):
                add("generation", str(int(match[1])), match[0])
    for match in MODEL.finditer(text):
        add("model", re.sub(r"\s", "", match[0]).upper(), match[0])

    versions = {
        "Pro": r"(?<![a-z])pro(?![a-z])",
        "NFC版": r"(?<![a-z])nfc(?![a-z])",
        "标准版": r"标准版|普通版|(?<![a-z])standard(?![a-z])",
        "陶瓷版": r"陶瓷(?:特别)?版|陶瓷特别款",
    }
    hits = {
        version: list(re.finditer(pattern, text, re.I))
        for version, pattern in versions.items()
    }
    # Pro/ceramic listings often advertise NFC as a feature, not a second variant.
    # Explicit option separators (9/NFC/Pro) must remain ambiguous instead.
    variant = r"(?:标准版|普通版|pro|nfc(?:版)?|陶瓷(?:特别)?版|\d+(?:pro|nfc)?)"
    option_list = bool(re.search(rf"{variant}\s*[/、或]\s*{variant}", text, re.I))
    for match in hits["NFC版"]:
        add("feature", "NFC", match[0], excluded=not _positive(text, match.start()))
    specific = any(
        _positive(text, m.start())
        for key in ("Pro", "陶瓷版", "标准版") for m in hits[key]
    )
    for version, matches in hits.items():
        if version == "NFC版" and specific:
            explicit_nfc_variant = any(text[m.end():].startswith("版") for m in matches)
            if not option_list and not explicit_nfc_variant:
                for match in matches:
                    if not _positive(text, match.start()):
                        add("version", version, match[0], excluded=True)
                continue
        for match in matches:
            add("version", version, match[0], excluded=not _positive(text, match.start()))
    if re.search(r"(?:手环|band)\s*\d+\s*/\s*(?:\d+\s*)?(?:nfc|pro)", text, re.I):
        identity.ambiguities.append("标题以斜线列出多个版本，无法确认此报价对应的 SKU")
    if len(identity.generation) > 1:
        identity.ambiguities.append("标题包含多个代数，无法确认此报价对应哪一代")
    if len(identity.version) > 1:
        identity.ambiguities.append("标题包含多个版本，无法确认此报价对应哪个版本")
    for match in re.finditer(r"黑色|银色|金色|玫瑰金|粉色|白色|蓝色|绿色", text):
        add("color", match[0], match[0], excluded=not _positive(text, match.start()))
    conditions = {"全新": r"全新", "二手": r"二手|\d+成新|仅拆封", "翻新": r"翻新|官翻"}
    for value, pattern in conditions.items():
        for match in re.finditer(pattern, text):
            add("condition", value, match[0], excluded=not _positive(text, match.start()))
    return identity


def assess_match(query: str, title: str) -> MatchReport:
    requested, observed = extract_identity(query), extract_identity(title)
    checks = []
    for field, label in LABELS.items():
        expected, actual = getattr(requested, field), getattr(observed, field)
        excluded = requested.excluded.get(field, [])
        denied = observed.excluded.get(field, [])
        if set(excluded).intersection(actual) or set(expected).intersection(denied):
            status, explanation = "conflict", f"需求与标题明确声明的{label}条件冲突"
        elif not expected and not excluded:
            status, explanation = "not_requested", "需求未限定此属性"
        elif not actual:
            status, explanation = "unknown", f"标题未明确说明{label}，不能视为一致"
        elif len(actual) > 1:
            status, explanation = "ambiguous", f"标题列出多个{label}，无法对应单一报价"
        elif expected and not set(expected).intersection(actual):
            status, explanation = "conflict", f"需求与标题中的{label}不一致"
        else:
            status, explanation = "consistent", "标题声明与需求一致，仍需核对实际 SKU"
        checks.append(
            FieldMatch(
                field=field,
                label=label,
                status=status,
                requested=expected,
                excluded=excluded,
                observed=actual,
                title_evidence=observed.evidence.get(field, [])
                + observed.evidence.get(f"excluded.{field}", []),
                explanation=explanation,
            )
        )
    conflicts = [c.explanation for c in checks if c.status == "conflict"]
    ambiguities = list(observed.ambiguities)
    ambiguities.extend(c.explanation for c in checks if c.status == "ambiguous")
    unknown = [c.explanation for c in checks if c.status == "unknown"]
    if requested.ambiguities and not re.search(r"都行|均可|都可|不限|或者|或", query):
        unknown.append("需求包含多个代数或版本，请先明确本次要比较的规格")
    specific = bool(requested.model or requested.generation)
    status = (
        "conflict" if conflicts else "ambiguous" if ambiguities else
        "insufficient" if unknown or not specific else "compatible"
    )
    reasons = list(dict.fromkeys(conflicts + ambiguities + unknown))
    if not specific:
        reasons.append("需求缺少可识别的具体型号或代数，仅凭标题不能确认同款")
    return MatchReport(
        status=status,
        checks=checks,
        reasons=reasons or ["已识别的标题属性一致，不代表实际 SKU 或价格条件已验证"],
    )


def assess_offers(offers: list[RawOffer], query: str) -> None:
    """Always recompute from title; never trust reports supplied by a client or model."""
    for offer in offers:
        offer.match_report = assess_match(query, offer.title)


def evidence_allows_pick(offer: RawOffer) -> bool:
    return offer.match_report is None or not offer.match_report.blocks_recommendation


def evidence_priority(offer: RawOffer) -> int:
    if not evidence_allows_pick(offer):
        return 2
    return 0 if offer.match_report and offer.match_report.status == "compatible" else 1


def prompt_evidence(offer: RawOffer) -> str:
    """Compact structured evidence; full source text remains in the offer's title."""
    import json

    report = offer.match_report
    if report is None:
        return "未核对"
    return json.dumps(
        {
            "status": report.status,
            "attributes": {c.field: c.observed for c in report.checks if c.observed},
            "reasons": report.reasons,
            "sku_verified": False,
            "price_verified": False,
        },
        ensure_ascii=False,
    )
