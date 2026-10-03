"""综合排序：LLM 评估商品综合价值，确定性代码负责数据校验。

原则：LLM 只输出排序与理由，价格一律取采集原值，不信任模型算出的任何数字。
"""

import json
import logging

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.models.offers import RawOffer

logger = logging.getLogger(__name__)


class RankedItem(BaseModel):
    """单条商品的排序结果。"""

    index: int = Field(description="对应输入列表中的下标，从 0 开始")
    score: int = Field(ge=0, le=100, description="综合分 0-100")
    reason: str = Field(description="一句话推荐理由，不超过 30 字")


class RankResult(BaseModel):
    """整批排序结果。"""

    items: list[RankedItem]
    summary: str = Field(default="", description="整体选购建议，不超过 80 字")


PROMPT = """你是一名购物比价助手。根据以下商品列表做综合排序，评估维度：

1. 价格（到手价，越低越好，但明显偏离市场价的低报价要降权）
2. 店铺可信度（自营 > 旗舰店 > 普通店）
3. 销量与热度（有销量数据的加权）
4. 标题与需求的相关度（型号/规格匹配程度）

用户需求：{query}

商品列表（下标 | 平台 | 到手价 | 原价 | 店铺 | 标题）：
{offers_text}

规则：
- 只允许对输入下标排序，不得编造不存在的下标
- score 为 0-100 整数
- reason 用中文，直接给结论，例如「自营低价，规格完全匹配」
- 必须覆盖全部输入商品
- 只输出 JSON，不要任何其他文字。格式：
  {{"items": [{{"index": 0, "score": 85, "reason": "自营低价"}}], "summary": "一句话"}}"""


def _extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（容忍 markdown 代码块包裹）。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"模型输出不含 JSON: {text[:200]}")
    return json.loads(text[start : end + 1])


def _offers_text(offers: list[RawOffer]) -> str:
    lines = []
    for i, o in enumerate(offers):
        orig = f"¥{o.original_price:.0f}" if o.original_price else "-"
        shop = o.shop or "-"
        lines.append(f"{i} | {o.platform} | ¥{o.price:.2f} | {orig} | {shop} | {o.title[:60]}")
    return "\n".join(lines)


def rank_offers(query: str, offers: list[RawOffer]) -> dict:
    """LLM 综合排序。返回 {items: [{index, score, reason}], summary}。

    未配置 LLM key 时抛出 RuntimeError，由 API 层转为错误信息。
    """
    settings = get_settings()
    if not settings.llm_api_key:
        raise RuntimeError("LLM 未配置：请在 .env 中设置 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL")

    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url or None,
        model=settings.llm_model or "gpt-4o-mini",
        temperature=0,
    )

    prompt = PROMPT.format(query=query, offers_text=_offers_text(offers))
    # 不用 with_structured_output：DeepSeek 等服务不支持 response_format，
    # 改为提示词约定 JSON + Pydantic 校验解析
    raw = llm.invoke(prompt)
    result = RankResult.model_validate(_extract_json(raw.content))

    # 确定性校验：下标必须落在输入范围内且不重复
    valid = set(range(len(offers)))
    seen: set[int] = set()
    items = []
    for it in result.items:
        if it.index in valid and it.index not in seen:
            seen.add(it.index)
            items.append(it.model_dump())
    if len(items) != len(offers):
        logger.warning(
            "rank result incomplete: %d/%d covered, filling rest by price", len(items), len(offers)
        )
        # 缺失的按价格升序补齐，保证输出完整
        missing = sorted((i for i in valid if i not in seen), key=lambda i: offers[i].price)
        for i in missing:
            items.append({"index": i, "score": 0, "reason": ""})

    return {"items": items, "summary": result.summary}
