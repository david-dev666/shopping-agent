"""规则层评测：在标注集上计算各标签的 precision / recall / F1。

标注集 `eval/rules_eval.jsonl`，每行 `{query, title, expect}`：
expect 为该标题应命中的规则键（见 `REASON_LABELS`），空数组表示不应命中任何标签。

只评测「单条可判定」的规则（型号 / 品牌 / 配件 / 二手）；
价格异常与销量偏低是批次相对规则，由单元测试覆盖。
"""

import json
from collections import defaultdict
from pathlib import Path

from app.matching.filter import REASON_LABELS, filter_offers
from app.models.offers import RawOffer

EVAL_PATH = Path(__file__).with_name("rules_eval.jsonl")
LABEL_TO_REASON = {v: k for k, v in REASON_LABELS.items()}


def load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in EVAL_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def predict(case: dict) -> set[str]:
    """对单条标题预测命中的规则键。"""
    offer = RawOffer(platform="jd", platform_id="1", title=case["title"], price=100.0)
    kept, _, _ = filter_offers([offer], case["query"])
    return {LABEL_TO_REASON[t] for t in (kept[0].tags or []) if t in LABEL_TO_REASON}


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def evaluate() -> dict:
    """返回 {n_cases, per_rule, micro, errors}。"""
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    cases = load_cases()
    errors = []

    for case in cases:
        exp = set(case["expect"])
        got = predict(case)
        for r in exp & got:
            tp[r] += 1
        for r in got - exp:
            fp[r] += 1
        for r in exp - got:
            fn[r] += 1
        if exp != got:
            errors.append(
                {"query": case["query"], "title": case["title"],
                 "expect": sorted(exp), "got": sorted(got)}
            )

    rules = sorted(set(tp) | set(fp) | set(fn))
    per_rule = {r: _prf(tp[r], fp[r], fn[r]) for r in rules}
    micro = _prf(sum(tp.values()), sum(fp.values()), sum(fn.values()))
    return {"n_cases": len(cases), "per_rule": per_rule, "micro": micro, "errors": errors}
