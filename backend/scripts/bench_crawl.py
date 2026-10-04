"""测量三平台采集耗时（需 webbridge daemon 在跑，或已配置联盟 API）。

用法（在 backend/ 下）：
    uv run python scripts/bench_crawl.py 小米手环9
"""

import asyncio
import sys
import time

from app.adapters.registry import get_adapters
from app.config import get_settings


async def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "小米手环9"
    print(f"query: {query}")
    for adapter in get_adapters(get_settings()):
        start = time.perf_counter()
        try:
            offers = await adapter.search(query)
            status = f"{len(offers):3d} offers"
        except Exception as e:  # noqa: BLE001 - 采集失败也要打印耗时
            status = f"ERROR {e!r}"[:70]
        ms = (time.perf_counter() - start) * 1000
        print(f"  {adapter.platform:8}{ms:9.0f} ms   {status}")


if __name__ == "__main__":
    asyncio.run(main())
