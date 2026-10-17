"""Compare title rules with Codex's weak labels, never independently verified SKU truth."""

import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.matching.identity import assess_match
from app.models.offers import RawOffer, offer_key


class Pair(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    id: str = Field(min_length=1)
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    reference: RawOffer
    candidate: RawOffer
    title_match: StrictBool | None
    suitable: StrictBool | None
    reviewer: Literal["codex"]
    evidence: str = Field(min_length=1)


def validate_pairs(rows: list[dict]) -> list[Pair]:
    pairs = [Pair.model_validate(row) for row in rows]
    if not pairs:
        raise ValueError("没有 AI 评阅案例")
    ids, candidates, titles, queries = set(), set(), set(), {}
    for pair in pairs:
        key = tuple(
            sorted(
                re.sub(r"[\W_]", "", o.title.casefold()) for o in (pair.reference, pair.candidate)
            )
        )
        if not all(key) and pair.title_match is not None:
            raise ValueError("缺少标题时必须标为待确认")
        if pair.id in ids or key in titles:
            raise ValueError(f"重复商品对: {pair.id}")
        if pair.reference.platform == pair.candidate.platform:
            raise ValueError(f"不是跨平台商品对: {pair.id}")
        candidate_key = (pair.query_id, offer_key(pair.candidate))
        if candidate_key in candidates:
            raise ValueError(f"同一查询有重复候选 ID: {pair.id}")
        query = (pair.query, pair.reference.model_dump(mode="json", exclude={"ts"}))
        if pair.query_id in queries and queries[pair.query_id] != query:
            raise ValueError(f"query_id 对应多个需求或参考商品: {pair.query_id}")
        ids.add(pair.id)
        titles.add(key)
        candidates.add(candidate_key)
        queries[pair.query_id] = query
    return pairs


def evaluate_pairs(rows: list[dict], predictions: dict | None = None) -> dict:
    pairs = validate_pairs(rows)
    known = [p for p in pairs if p.title_match is not None]
    tp = fp = fn = correct = 0
    for pair in known:
        matched = assess_match(pair.reference.title, pair.candidate.title).status == "compatible"
        tp += int(matched and pair.title_match)
        fp += int(matched and not pair.title_match)
        fn += int(not matched and pair.title_match)
        correct += int(matched == pair.title_match)
    groups = defaultdict(dict)
    for pair in pairs:
        groups[pair.query_id][pair.id] = pair
    ranking = None
    if predictions is not None:
        if (
            not isinstance(predictions, dict)
            or any(
                not isinstance(k, str) or (v is not None and not isinstance(v, str))
                for k, v in predictions.items()
            )
            or set(predictions) - set(groups)
        ):
            raise ValueError("推荐结果必须为本次 query_id 到商品对 id 或 null 的映射")
        selected = suitable = unknown = 0
        for query_id, selected_id in predictions.items():
            if selected_id is None:
                continue
            if selected_id not in groups[query_id]:
                raise ValueError(f"首选不属于该查询候选集: {query_id}")
            label = groups[query_id][selected_id].suitable
            selected += 1
            unknown += int(label is None)
            suitable += int(label is True)
        judged = selected - unknown
        ranking = {
            "evaluated_queries": len(predictions),
            "total_queries": len(groups),
            "query_coverage": len(predictions) / len(groups),
            "selected": selected,
            "unjudged_selected": unknown,
            "abstained": len(predictions) - selected,
            "recommendation_coverage": selected / len(predictions) if predictions else None,
            "top1_suitable_rate": suitable / judged if judged else None,
            "wrong_recommendation_rate": (judged - suitable) / judged if judged else None,
        }
    return {
        "label_source": "codex_title_review",
        "independent_ground_truth": False,
        "pairs": len(pairs),
        "title_labelled": len(known),
        "title_pending": len(pairs) - len(known),
        "label_coverage": len(known) / len(pairs),
        "matching": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "agreement": correct / len(known) if known else None,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
        },
        "ranking": ranking,
        "scope": "与 Codex 基于历史标题及采集报价的弱标签比较；未验证实际 SKU、成色或成交条件",
    }
