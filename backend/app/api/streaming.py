"""把同步 Agent 的真实节点更新转换为 SSE；断开连接时发出协作取消信号。"""

import asyncio
import json
import logging
import queue
import threading
from collections.abc import AsyncIterator
from time import monotonic

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool

from app.agents.graph import stream_agent

logger = logging.getLogger(__name__)


def encode_event(event: dict) -> str:
    name = event.get("event", "message")
    body = {key: value for key, value in event.items() if key != "event"}
    return f"event: {name}\ndata: {json.dumps(jsonable_encoder(body), ensure_ascii=False)}\n\n"


async def agent_events(query: str, request: Request) -> AsyncIterator[str]:
    messages: queue.SimpleQueue = queue.SimpleQueue()
    cancelled = threading.Event()

    def work():
        try:
            for event in stream_agent(query, cancelled):
                if cancelled.is_set():
                    break
                messages.put(event)
        except Exception:
            logger.exception("agent stream failed")
            messages.put({"event": "error", "message": "本次任务未完成，请重试或检查数据源配置"})
        finally:
            messages.put(None)

    worker = asyncio.create_task(run_in_threadpool(work))
    heartbeat = monotonic()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = messages.get_nowait()
            except queue.Empty:
                if monotonic() - heartbeat >= 10:
                    yield ": keepalive\n\n"
                    heartbeat = monotonic()
                await asyncio.sleep(0.05)
                continue
            if event is None:
                break
            yield encode_event(event)
    finally:
        cancelled.set()
        # 当前模型/HTTP 请求可能仍需结束，取消信号阻止后续图节点启动。
        worker.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
