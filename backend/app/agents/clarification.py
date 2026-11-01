"""Ask only about supported, missing attributes that distinguish viable candidates."""

from pydantic import BaseModel, ConfigDict, Field

from app.matching.filter import WARN_TAGS
from app.matching.identity import extract_identity
from app.models.offers import RawOffer

ANY = "不限"


class ClarificationAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation: str | None = Field(default=None, max_length=20)
    version: str | None = Field(default=None, max_length=20)


def effective_query(query: str, answers: dict[str, str]) -> str:
    identity = extract_identity(query)
    additions = []
    if answers.get("generation") not in (None, ANY):
        category = identity.category[0] if identity.category else "手环"
        additions.append(f"{category}{answers['generation']}")
    if answers.get("version") not in (None, ANY):
        additions.append(answers["version"])
    return query + ("；用户确认：" + " ".join(additions) if additions else "")


def questions_for(
    query: str,
    offers: list[RawOffer],
    budget: float | None = None,
    answers: dict[str, str] | None = None,
) -> list[dict]:
    answers = answers or {}
    requested = extract_identity(query)
    # Scope is deliberately limited to the wearable attributes supported by title rules.
    if not requested.brand or not requested.category:
        return []
    viable = [
        extract_identity(o.title)
        for o in offers
        if not (set(o.tags) & WARN_TAGS)
        and (budget is None or o.price <= budget)
        and o.match_report is not None
        and not o.match_report.blocks_recommendation
    ]
    questions = []
    for field, label in (("generation", "代数"), ("version", "版本")):
        if field in answers or getattr(requested, field) or requested.excluded.get(field):
            continue
        values = sorted({
            getattr(identity, field)[0]
            for identity in viable if len(getattr(identity, field)) == 1
        })
        if len(values) < 2:
            continue
        questions.append({
            "field": field,
            "question": f"当前候选包含不同{label}，你希望比较哪一种？",
            "options": [*values, ANY],
        })
    return questions


def validate_answers(questions: list[dict], answers: dict[str, str]) -> None:
    allowed = {q["field"]: set(q["options"]) for q in questions}
    for field, value in answers.items():
        if value not in allowed.get(field, set()):
            raise ValueError("请回答当前候选提供的规格问题；更换商品请重新查询")
