from typing import Protocol

from app.models.offers import RawOffer


class PlatformAdapter(Protocol):
    """采集层统一接口，每个平台实现一个。"""

    platform: str

    async def search(self, query: str) -> list[RawOffer]: ...
