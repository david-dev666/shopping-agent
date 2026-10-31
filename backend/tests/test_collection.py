"""Offline concurrency checks against controlled platform adapters."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.collection import (
    CollectionBusy,
    CollectionExpired,
    CollectionPool,
    CollectionStopped,
    check_collection,
)
from app.models.offers import RawOffer


class Controlled:
    platform = "jd"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    async def search(self, query):
        self.calls += 1
        self.started.set()
        while not self.release.is_set():
            check_collection()
            await asyncio.sleep(0.005)
        return [RawOffer(platform=self.platform, platform_id="1", title=query, price=100)]


@pytest.fixture
def pool():
    p = CollectionPool(workers=2, capacity=3, timeout=2)
    try:
        yield p
    finally:
        p.close()


async def entered(adapter):
    assert await asyncio.to_thread(adapter.started.wait, 1)


@pytest.mark.parametrize("serial_browser", [False, True])
async def test_many_identical_queries_share_collection_but_not_mutable_results(
    pool, serial_browser
):
    adapter = Controlled()
    adapter.serial_browser = serial_browser
    tasks = [asyncio.create_task(pool.search("item", adapter)) for _ in range(20)]
    await entered(adapter)
    await asyncio.sleep(0.03)
    adapter.release.set()
    results = await asyncio.gather(*tasks)
    assert adapter.calls == 1
    assert pool.stats()["joined"] == 19
    results[0][0].tags.append("modified")
    assert results[1][0].tags == []


@pytest.mark.parametrize("serial_browser", [False, True])
async def test_cancel_one_consumer_preserves_shared_collection(pool, serial_browser):
    adapter = Controlled()
    adapter.serial_browser = serial_browser
    stop = threading.Event()
    a = asyncio.create_task(pool.search("same", adapter, stop))
    b = asyncio.create_task(pool.search("same", adapter))
    await entered(adapter)
    stop.set()
    with pytest.raises(CollectionStopped):
        await a
    assert not b.done()
    adapter.release.set()
    assert (await b)[0].price == 100
    assert adapter.calls == 1


@pytest.mark.parametrize("serial_browser", [False, True])
async def test_native_async_cancellation_does_not_cancel_other_consumer(pool, serial_browser):
    adapter = Controlled()
    adapter.serial_browser = serial_browser
    a = asyncio.create_task(pool.search("same", adapter))
    b = asyncio.create_task(pool.search("same", adapter))
    await entered(adapter)
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    adapter.release.set()
    assert (await b)[0].price == 100


async def test_last_cancel_stops_cooperative_running_collection(pool):
    adapter = Controlled()
    stop = threading.Event()
    task = asyncio.create_task(pool.search("same", adapter, stop))
    await entered(adapter)
    stop.set()
    with pytest.raises(CollectionStopped):
        await task
    for _ in range(100):
        if pool.stats()["outstanding"] == 0:
            break
        await asyncio.sleep(0.005)
    assert pool.stats()["outstanding"] == 0


async def test_capacity_rejects_distinct_work_but_allows_join():
    pool = CollectionPool(workers=1, capacity=1, timeout=2)
    adapter = Controlled()
    try:
        a = asyncio.create_task(pool.search("first", adapter))
        await entered(adapter)
        with pytest.raises(CollectionBusy):
            await pool.search("second", adapter)
        b = asyncio.create_task(pool.search("first", adapter))
        await asyncio.sleep(0.02)
        adapter.release.set()
        await asyncio.gather(a, b)
        assert adapter.calls == 1
    finally:
        adapter.release.set()
        pool.close()


async def test_deadline_includes_time_queued_and_queued_cancel_skips_adapter():
    pool = CollectionPool(workers=1, capacity=2, timeout=0.12)
    running = Controlled()
    running.serial_browser = True
    queued = Controlled()

    async def command(query):
        running.started.set()
        while not running.release.is_set():
            await asyncio.sleep(0.005)
        check_collection()
        return []

    running.search = command
    try:
        a = asyncio.create_task(pool.search("a", running))
        await entered(running)
        b = asyncio.create_task(pool.search("b", queued))
        results = await asyncio.gather(a, b, return_exceptions=True)
        assert all(isinstance(r, (CollectionExpired, TimeoutError)) for r in results)
        assert queued.calls == 0
    finally:
        running.release.set()
        pool.close()


async def test_browser_command_remains_owned_until_it_finishes():
    pool = CollectionPool(workers=1, capacity=2, timeout=0.08)
    adapter = Controlled()
    adapter.serial_browser = True

    async def command(query):
        adapter.calls += 1
        adapter.started.set()
        # A daemon command cannot be assumed stopped when its waiter goes away.
        while not adapter.release.is_set():
            await asyncio.sleep(0.005)
        check_collection()
        return []

    adapter.search = command
    try:
        a = asyncio.create_task(pool.search("a", adapter))
        await entered(adapter)
        with pytest.raises(CollectionExpired):
            await a
        assert pool.stats()["outstanding"] == 1
        with pytest.raises(CollectionBusy):
            await pool.search("a", adapter)
        adapter.release.set()
    finally:
        adapter.release.set()
        pool.close()


def test_single_flight_is_shared_between_event_loops_and_threads(pool):
    adapter = Controlled()
    barrier = threading.Barrier(2)

    def request():
        async def run():
            barrier.wait(timeout=1)
            return await pool.search("same", adapter)

        return asyncio.run(run())

    with ThreadPoolExecutor(max_workers=2) as workers:
        a = workers.submit(request)
        b = workers.submit(request)
        assert adapter.started.wait(1)
        import time

        time.sleep(0.04)
        adapter.release.set()
        assert a.result(timeout=1)[0].price == b.result(timeout=1)[0].price
    assert adapter.calls == 1


async def test_completed_result_is_not_a_hidden_price_cache(pool):
    adapter = Controlled()
    adapter.release.set()
    await pool.search("same", adapter)
    await pool.search("same", adapter)
    assert adapter.calls == 2


async def test_close_rejects_new_work():
    pool = CollectionPool()
    pool.close()
    with pytest.raises(CollectionBusy):
        await pool.search("same", Controlled())


async def test_different_credentials_do_not_share_candidates(pool):
    a, b = Controlled(), Controlled()
    a.app_key, b.app_key = "one", "two"
    a.release.set()
    b.release.set()
    await asyncio.gather(pool.search("same", a), pool.search("same", b))
    assert a.calls == b.calls == 1


async def test_one_platform_failure_preserves_successful_results(monkeypatch, pool):
    import app.collection as collection

    good, bad = Controlled(), Controlled()
    bad.platform = "pdd"
    good.release.set()

    async def failure(query):
        raise ValueError("unavailable")

    bad.search = failure
    monkeypatch.setattr(collection, "get_collection_pool", lambda: pool)
    offers, errors = await collection.search_all("item", [good, bad])
    assert len(offers) == 1
    assert "pdd" in errors and "jd" not in errors


async def test_cancelled_browser_waiter_does_not_enter_tab():
    from time import monotonic

    from app.adapters.webbridge import WebBridgeClient
    from app.collection import CollectionContext, collection_context

    client = WebBridgeClient("http://unused", "test")
    stop = threading.Event()
    client._lock.acquire()
    token = collection_context.set(CollectionContext(stop, monotonic() + 1))
    try:

        async def wait():
            async with client._get_lock():
                pytest.fail("cancelled waiter acquired browser")

        task = asyncio.create_task(wait())
        await asyncio.sleep(0.02)
        stop.set()
        with pytest.raises(CollectionStopped):
            await task
    finally:
        client._lock.release()
        collection_context.reset(token)


async def test_browser_transport_timeout_requires_reconciliation(monkeypatch):
    import httpx

    from app.adapters.webbridge import WebBridgeClient

    async def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("unknown command outcome")

    monkeypatch.setattr(httpx.AsyncClient, "post", timeout)
    client = WebBridgeClient("http://unused", "test")
    with pytest.raises(httpx.ReadTimeout):
        async with client._get_lock():
            await client.navigate("http://unused")
    with pytest.raises(RuntimeError, match="状态未知"):
        async with client._get_lock():
            pytest.fail("uncertain browser reused")


async def test_busy_api_returns_retryable_429(monkeypatch):
    import httpx

    from app.main import app

    async def busy(*args):
        raise CollectionBusy("queue full")

    monkeypatch.setattr("app.api.routes.search_all", busy)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/query",
            json={
                "query": "unique-overload-case",
                "data_mode": "live",
                "refresh": True,
            },
        )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"


async def test_last_waiter_cancels_inflight_api_task(pool):
    adapter = Controlled()
    stopped = threading.Event()
    cancel = threading.Event()

    async def http_call(query):
        adapter.started.set()
        try:
            await asyncio.sleep(10)
        finally:
            stopped.set()

    adapter.search = http_call
    task = asyncio.create_task(pool.search("same", adapter, cancel))
    await entered(adapter)
    cancel.set()
    with pytest.raises(CollectionStopped):
        await task
    assert await asyncio.to_thread(stopped.wait, 1)


async def test_pre_cancelled_request_does_not_submit_work(pool):
    stop = threading.Event()
    stop.set()
    with pytest.raises(CollectionStopped):
        await pool.search("same", Controlled(), stop)
    assert pool.stats()["submitted"] == 0


@pytest.mark.parametrize("workers", [1, 4])
async def test_fast_browser_platforms_finish_before_slow_jd_deadline(monkeypatch, workers):
    import app.collection as collection
    from app.adapters.webbridge import WebBridgeAdapter, WebBridgeClient

    pool = CollectionPool(workers=workers, capacity=3, timeout=0.3)
    client = WebBridgeClient("http://unused", "test")
    order = []

    async def search(adapter, query):
        async with client._get_lock():
            order.append(adapter.platform)
            if adapter.platform == "jd":
                while True:
                    check_collection()
                    await asyncio.sleep(0.005)
            return [RawOffer(platform=adapter.platform, platform_id="1", title=query, price=100)]

    monkeypatch.setattr(WebBridgeAdapter, "search", search)
    monkeypatch.setattr(collection, "get_collection_pool", lambda: pool)
    try:
        offers, errors = await collection.search_all(
            "item", [WebBridgeAdapter(p) for p in ("jd", "pdd", "taobao")]
        )
        assert order == ["pdd", "taobao", "jd"]
        assert {offer.platform for offer in offers} == {"pdd", "taobao"}
        assert set(errors) == {"jd"}
        assert "CollectionExpired" in errors["jd"]
    finally:
        pool.close()


async def test_queued_browser_work_does_not_occupy_api_workers():
    pool = CollectionPool(workers=2, capacity=4, timeout=2)
    browser = [Controlled() for _ in range(3)]
    for adapter, platform in zip(browser, ("pdd", "taobao", "jd"), strict=True):
        adapter.platform = platform
        adapter.serial_browser = True
    api = Controlled()
    api.release.set()
    tasks = []
    try:
        tasks.append(asyncio.create_task(pool.search("first", browser[0])))
        await entered(browser[0])
        tasks.extend(asyncio.create_task(pool.search("first", a)) for a in browser[1:])
        await asyncio.sleep(0.03)
        assert browser[1].calls == browser[2].calls == 0
        assert (await asyncio.wait_for(pool.search("api", api), timeout=0.5))[0].price == 100
        browser[0].release.set()
        await entered(browser[1])
        assert browser[2].calls == 0
        browser[1].release.set()
        await entered(browser[2])
        browser[2].release.set()
        await asyncio.gather(*tasks)
    finally:
        for adapter in browser:
            adapter.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        pool.close()


async def test_cancelled_browser_queue_item_never_runs_or_blocks_following_work():
    pool = CollectionPool(workers=2, capacity=3, timeout=2)
    adapter = Controlled()
    adapter.serial_browser = True
    stop = threading.Event()
    tasks = []
    try:
        tasks.append(asyncio.create_task(pool.search("first", adapter)))
        await entered(adapter)
        middle = asyncio.create_task(pool.search("cancelled", adapter, stop))
        tasks.append(middle)
        tasks.append(asyncio.create_task(pool.search("last", adapter)))
        await asyncio.sleep(0.03)
        stop.set()
        with pytest.raises(CollectionStopped):
            await middle
        assert pool.stats()["outstanding"] == 2
        adapter.release.set()
        first, last = await asyncio.gather(tasks[0], tasks[2])
        assert first[0].title == "first"
        assert last[0].title == "last"
        assert adapter.calls == 2
    finally:
        adapter.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        pool.close()


async def test_failed_browser_job_releases_next_queued_job():
    pool = CollectionPool(workers=2, capacity=2, timeout=2)
    adapter = Controlled()
    adapter.serial_browser = True

    async def search(query):
        if query == "bad":
            raise ValueError("unavailable")
        return [RawOffer(platform="jd", platform_id="1", title=query, price=100)]

    adapter.search = search
    try:
        failed, success = await asyncio.gather(
            pool.search("bad", adapter), pool.search("good", adapter), return_exceptions=True
        )
        assert isinstance(failed, ValueError)
        assert success[0].title == "good"
    finally:
        pool.close()


async def test_expired_browser_queue_item_never_enters_adapter():
    pool = CollectionPool(workers=2, capacity=2, timeout=0.12)
    running, queued = Controlled(), Controlled()
    running.serial_browser = queued.serial_browser = True
    tasks = []

    async def command(query):
        running.started.set()
        while not running.release.is_set():
            await asyncio.sleep(0.005)
        check_collection()
        return []

    running.search = command
    try:
        tasks.append(asyncio.create_task(pool.search("running", running)))
        await entered(running)
        tasks.append(asyncio.create_task(pool.search("queued", queued)))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, CollectionExpired) for result in results)
        assert queued.calls == 0
        assert pool.stats()["outstanding"] == 1
    finally:
        running.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        pool.close()


async def test_close_cancels_browser_queue_without_starting_waiters():
    pool = CollectionPool(workers=2, capacity=3, timeout=2)
    adapter = Controlled()
    adapter.serial_browser = True
    tasks = []
    try:
        tasks.append(asyncio.create_task(pool.search("running", adapter)))
        await entered(adapter)
        tasks.extend(
            asyncio.create_task(pool.search(query, adapter)) for query in ("queued-a", "queued-b")
        )
        await asyncio.sleep(0.03)
        await asyncio.to_thread(pool.close)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, BaseException) for result in results)
        assert adapter.calls == 1
        assert pool.stats()["outstanding"] == 0
    finally:
        adapter.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        pool.close()
