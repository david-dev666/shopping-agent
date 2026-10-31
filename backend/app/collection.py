"""Process-local collection admission, single-flight and cooperative cancellation.

Only raw platform results are shared. Every consumer receives a detached copy;
filtering, feedback and model decisions remain request-local.
"""

import asyncio
import hashlib
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic

from app.config import get_settings
from app.models.offers import RawOffer


class CollectionBusy(RuntimeError):
    pass


class CollectionExpired(RuntimeError):
    pass


class CollectionStopped(RuntimeError):
    pass


request_cancel: ContextVar[threading.Event | None] = ContextVar("collection_cancel", default=None)


@dataclass
class CollectionContext:
    stop: threading.Event
    deadline: float

    def check(self):
        if self.stop.is_set():
            raise CollectionStopped("采集已停止")
        if monotonic() >= self.deadline:
            raise CollectionExpired("采集超时，请稍后重试")


collection_context: ContextVar[CollectionContext | None] = ContextVar(
    "collection_context", default=None
)


def check_collection():
    context = collection_context.get()
    if context:
        context.check()


@dataclass
class _Job:
    context: CollectionContext
    future: Future | None = None
    users: int = 0
    serial_browser: bool = False


class CollectionPool:
    """Bound active + queued platform jobs across threads and asyncio loops."""

    def __init__(self, workers=4, capacity=16, timeout=45.0):
        self.capacity = capacity
        self.timeout = timeout
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="collection")
        self._lock = threading.RLock()
        self._jobs: dict[tuple, _Job] = {}
        self._browser_queue = deque()
        self._browser_active = None
        self._closed = False
        self._counts = {"submitted": 0, "joined": 0, "rejected": 0}

    @staticmethod
    def _key(query, adapter):
        # Credentials scope the cache without storing secrets in its keys or logs.
        fields = ("app_key", "app_secret", "client_id", "client_secret", "adzone_id")
        scope = repr(
            (
                tuple((name, getattr(adapter, name, None)) for name in fields),
                get_settings().webbridge_base_url,
            )
        )
        return (
            type(adapter),
            adapter.platform,
            query.strip(),
            hashlib.sha256(scope.encode()).digest(),
        )

    def _run(self, query, adapter, job):
        token = collection_context.set(job.context)
        try:
            check_collection()
            if getattr(adapter, "serial_browser", False):
                # Browser actions stop at safe boundaries; never release its tab
                # while a daemon command may still be executing.
                return asyncio.run(adapter.search(query))

            async def bounded():
                task = asyncio.create_task(adapter.search(query))
                try:
                    while not task.done():
                        check_collection()
                        await asyncio.wait({task}, timeout=0.02)
                    return task.result()
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

            return asyncio.run(bounded())
        finally:
            collection_context.reset(token)

    def _done(self, key, job):
        with self._lock:
            if self._jobs.get(key) is job:
                del self._jobs[key]
            if job.serial_browser:
                self._browser_queue = deque(
                    entry for entry in self._browser_queue if entry[2] is not job
                )

    def _start_browser(self):
        # Called under _lock. Waiting browser jobs consume capacity, not workers.
        if self._closed or self._browser_active is not None:
            return
        while self._browser_queue:
            query, adapter, job = self._browser_queue.popleft()
            if job.future.cancelled():
                continue
            try:
                job.context.check()
            except (CollectionStopped, CollectionExpired) as exc:
                job.future.set_exception(exc)
                continue
            self._browser_active = job
            worker = self._executor.submit(self._run_browser, query, adapter, job)
            worker.add_done_callback(lambda result, job=job: self._browser_done(result, job))
            return

    def _run_browser(self, query, adapter, job):
        if job.future.set_running_or_notify_cancel():
            return self._run(query, adapter, job)
        return []

    def _browser_done(self, worker, job):
        with self._lock:
            if not job.future.cancelled():
                if worker.cancelled():
                    job.future.cancel()
                elif (exc := worker.exception()) is not None:
                    job.future.set_exception(exc)
                else:
                    job.future.set_result(worker.result())
            self._browser_active = None
            self._start_browser()

    async def search(self, query, adapter, cancelled=None):
        if cancelled is not None and cancelled.is_set():
            raise CollectionStopped("请求已停止")
        key = self._key(query, adapter)
        with self._lock:
            if self._closed:
                raise CollectionBusy("采集服务已关闭")
            job = self._jobs.get(key)
            if job is not None and job.context.stop.is_set():
                raise CollectionBusy("上次采集正在停止，请稍后重试")
            if job is None:
                if len(self._jobs) >= self.capacity:
                    self._counts["rejected"] += 1
                    raise CollectionBusy("采集队列已满，请稍后重试")
                job = _Job(
                    CollectionContext(threading.Event(), monotonic() + self.timeout),
                    serial_browser=bool(getattr(adapter, "serial_browser", False)),
                )
                self._jobs[key] = job
                if job.serial_browser:
                    job.future = Future()
                else:
                    job.future = self._executor.submit(self._run, query, adapter, job)
                job.future.add_done_callback(lambda _: self._done(key, job))
                if job.serial_browser:
                    self._browser_queue.append((query, adapter, job))
                    self._start_browser()
                self._counts["submitted"] += 1
            else:
                self._counts["joined"] += 1
            job.users += 1
        try:
            while True:
                if cancelled is not None and cancelled.is_set():
                    raise CollectionStopped("请求已停止")
                if job.future.done():
                    return [o.model_copy(deep=True) for o in job.future.result()]
                if monotonic() >= job.context.deadline:
                    raise CollectionExpired("采集超时，请稍后重试")
                await asyncio.sleep(0.02)
        finally:
            with self._lock:
                job.users -= 1
                if job.users == 0 and not job.future.done():
                    job.context.stop.set()
                    job.future.cancel()

    def stats(self):
        with self._lock:
            return {**self._counts, "outstanding": len(self._jobs), "capacity": self.capacity}

    def close(self):
        with self._lock:
            self._closed = True
            jobs = list(self._jobs.values())
            for job in jobs:
                job.context.stop.set()
                job.future.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)


_pool = None
_pool_lock = threading.Lock()


def get_collection_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            settings = get_settings()
            _pool = CollectionPool(
                settings.collection_workers,
                settings.collection_capacity,
                settings.collection_timeout_seconds,
            )
        return _pool


def close_collection_pool():
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool:
        pool.close()


async def search_all(query, adapters) -> tuple[list[RawOffer], dict[str, str]]:
    from app.adapters.registry import WB_ORDER

    if not adapters:
        return [], {}
    adapters = sorted(
        adapters,
        key=lambda adapter: WB_ORDER.get(adapter.platform, 9)
        if getattr(adapter, "serial_browser", False)
        else -1,
    )
    pool = get_collection_pool()
    cancelled = request_cancel.get()
    results = await asyncio.gather(
        *(pool.search(query, adapter, cancelled) for adapter in adapters), return_exceptions=True
    )
    if cancelled is not None and cancelled.is_set():
        raise CollectionStopped("请求已停止")
    offers, errors = [], {}
    for adapter, result in zip(adapters, results, strict=True):
        if isinstance(result, BaseException):
            errors[adapter.platform] = f"{type(result).__name__}: {result}"
        else:
            offers.extend(result)
    if not offers and all(isinstance(r, CollectionBusy) for r in results):
        raise CollectionBusy("采集队列繁忙，请稍后重试")
    offers.sort(key=lambda offer: offer.price)
    return offers, errors
