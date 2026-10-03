"""LLM 输出解析的公共工具：JSON 提取 + 容错重试 + 优雅降级。"""

import json
import logging

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（容忍 markdown 代码块包裹）。

    解析失败抛 ValueError，由调用方决定重试或降级。
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"模型输出不含 JSON: {text[:200]}")
    return json.loads(text[start : end + 1])


def invoke_json(llm, prompt: str, *, retries: int = 2, fallback: dict | None = None) -> dict:
    """调用 LLM 并解析为 JSON，带重试与降级。

    - 首次 + 最多 retries 次重试（在提示词后附加纠错指令）
    - 全部失败时：fallback 有值则降级返回，无值则抛最后异常
    """
    last_err: Exception | None = None
    attempt_prompt = prompt
    for attempt in range(retries + 1):
        try:
            result = llm.invoke(attempt_prompt)
            return extract_json(result.content)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            logger.warning("llm json parse failed (attempt %d/%d): %s", attempt + 1, retries + 1, e)
            attempt_prompt = (
                prompt + "\n\n注意：你上一次的输出无法解析为 JSON，本次必须只输出合法 JSON。"
            )
    if fallback is not None:
        logger.warning("llm json degraded to fallback: %r", last_err)
        return fallback
    raise last_err if last_err else RuntimeError("invoke_json: no result")
