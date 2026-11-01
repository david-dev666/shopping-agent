"""LLM 输出解析的公共工具：JSON 提取、结构校验与有限重试。"""

import json
import logging
from collections.abc import Callable

import httpx
from openai import APIError

logger = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    """A configured, reachable model is required for intelligent shopping."""


class ModelResponseError(RuntimeError):
    """The model did not return a usable structured response."""


def extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（容忍 markdown 代码块包裹）。

    解析失败抛 ValueError，由调用方决定重试或返回错误。
    """
    if not isinstance(text, str):
        raise ValueError("模型输出必须为文本")
    text = text.strip()
    if text.startswith("```"):
        if "\n" not in text:
            raise ValueError("模型输出代码块不完整")
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"模型输出不含 JSON: {text[:200]}")
    result = json.loads(text[start : end + 1])
    if not isinstance(result, dict):
        raise ValueError("模型输出必须为 JSON 对象")
    return result


def invoke_json(
    llm,
    prompt: str,
    *,
    retries: int = 2,
    validate: Callable[[dict], dict] | None = None,
) -> dict:
    """调用模型并校验结构；有限纠错后明确报错，不替换为规则结论。"""
    if llm is None:
        raise ModelUnavailable("智能选购需要配置模型；请配置后重试，或使用直接比价")
    last_err: Exception | None = None
    attempt_prompt = prompt
    for attempt in range(retries + 1):
        try:
            result = llm.invoke(attempt_prompt)
            data = extract_json(result.content)
            return validate(data) if validate else data
        except (APIError, httpx.HTTPError, TimeoutError, ConnectionError) as e:
            logger.warning("llm unavailable: %s", type(e).__name__)
            raise ModelUnavailable("模型暂时不可用，请稍后重试") from e
        except ValueError as e:
            last_err = e
            logger.warning("llm json parse failed (attempt %d/%d): %s", attempt + 1, retries + 1, e)
            attempt_prompt = (
                prompt + "\n\n注意：你上一次的输出无法解析为 JSON，本次必须只输出合法 JSON。"
            )
    raise ModelResponseError("模型输出未通过校验，请重试") from last_err
