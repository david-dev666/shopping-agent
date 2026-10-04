from pydantic import BaseModel, Field


class FilterSpec(BaseModel):
    """前端筛选面板传给 agent 的筛选条件。

    这些条件由确定性代码（`matching/filter.py:apply_filters`）应用，
    LLM 不参与；筛选后的候选集再交给 decide 节点重新排序。
    """

    exclude_tags: list[str] = Field(default_factory=list, description="要排除的标签")
    platforms: list[str] = Field(default_factory=list, description="限定平台，空表示不限")
    spec: str | None = Field(default=None, description="限定规格名（group_specs 的键）")
    price_min: float | None = Field(default=None, description="价格下限（含）")
    price_max: float | None = Field(default=None, description="价格上限（含）")

    def is_empty(self) -> bool:
        return not (self.exclude_tags or self.platforms or self.spec) and (
            self.price_min is None and self.price_max is None
        )
