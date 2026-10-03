"""规格提取：从商品标题识别版本/规格标签，用于前端分组筛选。

确定性正则，无 LLM。只提取用户筛选时关心的粒度（版本/材质），
不追求覆盖所有规格——漏识别的商品归入「其他」，不影响使用。
"""

import re

# 规格词典：key 为规范名，value 为标题匹配用的正则（按顺序取首个命中）
SPEC_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Pro", re.compile(r"pro\b|pro版", re.I)),
    ("NFC版", re.compile(r"nfc版|nfc\b", re.I)),
    ("陶瓷版", re.compile(r"陶瓷")),
    ("银色", re.compile(r"银色")),
    ("黑色", re.compile(r"黑色")),
    ("金色", re.compile(r"金色|玫瑰金")),
    ("粉色", re.compile(r"粉色|粉\b")),
]

# 型号数字（如 手环9 / 手环10）：用于排除「同品类不同代」混入
GEN_RE = re.compile(r"手环\s*(\d+)|band\s*(\d+)|watch\s*(\d+)", re.I)


def extract_spec(title: str) -> str | None:
    """返回标题的规格标签，无命中返回 None（前端归入「其他」）。"""
    for name, pat in SPEC_PATTERNS:
        if pat.search(title or ""):
            return name
    return None


def extract_generation(title: str) -> int | None:
    """返回标题里的代数数字（手环9 → 9），用于同代过滤提示。"""
    m = GEN_RE.search(title or "")
    if not m:
        return None
    for g in m.groups():
        if g:
            return int(g)
    return None


def group_specs(offers: list) -> dict[str, list]:
    """按规格分组 offers，返回 {规格名: [offers]}。

    规格名「其他」收纳无命中项；返回顺序按组内最低价升序。
    """
    groups: dict[str, list] = {}
    for o in offers:
        spec = extract_spec(o.title)
        groups.setdefault(spec or "其他", []).append(o)
    return dict(sorted(groups.items(), key=lambda kv: min(o.price for o in kv[1])))
