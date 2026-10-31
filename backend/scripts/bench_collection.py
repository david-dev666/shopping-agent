"""Offline request-coalescing benchmark; does not measure real platform latency."""

import asyncio
import json

from app.collection import CollectionPool
from app.models.offers import RawOffer


class Source:
    def __init__(self, platform):
        self.platform = platform
        self.calls = 0

    async def search(self, query):
        self.calls += 1
        await asyncio.sleep(0.05)
        return [RawOffer(platform=self.platform, platform_id="1", title=query, price=100)]


async def main():
    baseline = [Source(p) for p in ("jd", "taobao", "pdd")]
    await asyncio.gather(*(s.search("same item") for _ in range(20) for s in baseline))
    baseline_calls = sum(s.calls for s in baseline)
    sources = [Source(p) for p in ("jd", "taobao", "pdd")]
    pool = CollectionPool(workers=4, capacity=16, timeout=2)
    try:
        results = await asyncio.gather(
            *(pool.search("same item", source) for _ in range(20) for source in sources)
        )
        calls = sum(source.calls for source in sources)
        assert calls == 3 and len(results) == 60
        print(
            json.dumps(
                {
                    "mode": "offline controlled adapters; not production throughput",
                    "concurrent_requests": 20,
                    "platforms_per_request": 3,
                    "adapter_calls_without_coalescing": baseline_calls,
                    "adapter_calls": calls,
                    **pool.stats(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        pool.close()


if __name__ == "__main__":
    asyncio.run(main())
