"""LLM 输出解析的公共工具：JSON 提取 + 容错重试 + 优雅降级。"""

import json
import logging
from collections.abc import Callable

import httpx
from openai import APIError

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（容忍 markdown 代码块包裹）。

    解析失败抛 ValueError，由调用方决定重试或降级。
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
    fallback: dict | None = None,
    validate: Callable[[dict], dict] | None = None,
) -> dict:
    """调用 LLM 并解析为 JSON，带重试与降级。

    - 首次 + 最多 retries 次重试（在提示词后附加纠错指令）
    - 全部失败时：fallback 有值则降级返回，无值则抛最后异常
    """
    if llm is None:
        if fallback is not None:
            return fallback
        raise RuntimeError("LLM 未配置")
    last_err: Exception | None = None
    attempt_prompt = prompt
    for attempt in range(retries + 1):
        try:
            result = llm.invoke(attempt_prompt)
            data = extract_json(result.content)
            return validate(data) if validate else data
        except (APIError, httpx.HTTPError, TimeoutError, ConnectionError) as e:
            # 服务不可用时直接走规则降级；不叠加 SDK 重试造成长时间等待。
            last_err = e
            logger.warning("llm unavailable: %s", type(e).__name__)
            break
        except ValueError as e:
            last_err = e
            logger.warning("llm json parse failed (attempt %d/%d): %s", attempt + 1, retries + 1, e)
            attempt_prompt = (
                prompt + "\n\n注意：你上一次的输出无法解析为 JSON，本次必须只输出合法 JSON。"
            )
    if fallback is not None:
        logger.warning("llm json degraded to fallback: %r", last_err)
        return fallback
    raise last_err if last_err else RuntimeError("invoke_json: no result")
