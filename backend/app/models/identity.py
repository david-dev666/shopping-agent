"""Title evidence is a claim from the listing, never verification of its selected SKU."""

from typing import Literal

from pydantic import BaseModel, Field

IdentityField = Literal[
    "brand", "category", "model", "generation", "version", "feature", "color", "condition"
]


class ProductIdentity(BaseModel):
    brand: list[str] = Field(default_factory=list)
    category: list[str] = Field(default_factory=list)
    model: list[str] = Field(default_factory=list)
    generation: list[str] = Field(default_factory=list)
    version: list[str] = Field(default_factory=list)
    feature: list[str] = Field(default_factory=list)
    color: list[str] = Field(default_factory=list)
    condition: list[str] = Field(default_factory=list)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    ambiguities: list[str] = Field(default_factory=list)
    excluded: dict[str, list[str]] = Field(default_factory=dict)


class FieldMatch(BaseModel):
    field: IdentityField
    label: str
    status: Literal["consistent", "conflict", "unknown", "ambiguous", "not_requested"]
    requested: list[str]
    excluded: list[str] = Field(default_factory=list)
    observed: list[str]
    title_evidence: list[str] = Field(default_factory=list)
    explanation: str


class MatchReport(BaseModel):
    status: Literal["compatible", "conflict", "ambiguous", "insufficient"]
    checks: list[FieldMatch]
    reasons: list[str]
    source: Literal["title_rules_v1"] = "title_rules_v1"
    sku_verified: Literal[False] = False
    price_verified: Literal[False] = False

    @property
    def blocks_recommendation(self) -> bool:
        return self.status in {"conflict", "ambiguous"}
