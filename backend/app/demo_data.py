"""DEMO_MODE 的内置样例数据。

来源：一次真实采集的冻结快照（`app/demo/*.json`），仅用于「无数据源时开箱预览」。
所有响应显式带 `demo=True`，由前端标注，绝不混入真实采集 / 决策链路。
"""

import json
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).with_name("demo")


@lru_cache
def _load(name: str) -> dict:
    return json.loads((_DIR / name).read_text(encoding="utf-8"))


def demo_query_response() -> dict:
    """直接比价模式的样例响应。"""
    return {**_load("query.json"), "cached": False, "demo": True}


def demo_chat_response() -> dict:
    """Agent 决策模式的样例响应（含 trace）。"""
    return {**_load("chat.json"), "demo": True}


def demo_rank_response() -> dict:
    """综合排序的样例响应。"""
    chat = _load("chat.json")
    return {
        "items": chat["rank_items"],
        "summary": (chat.get("decision") or {}).get("reason", ""),
        "demo": True,
    }
