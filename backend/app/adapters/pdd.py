import logging
from datetime import UTC, datetime

import httpx

from app.adapters.signing import md5_sign, raise_on_error_response
from app.config import Settings
from app.models.offers import RawOffer

logger = logging.getLogger(__name__)

API_URL = "https://open-api.pdd.com"


def _cents_to_yuan(value: object) -> float | None:
    try:
        return int(value) / 100  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class PddAdapter:
    """拼多多多多进宝商品搜索（pdd.ddk.goods.search）。

    无 client_id/client_secret 时返回空列表，不造假数据。
    """

    platform = "pdd"

    def __init__(self, settings: Settings) -> None:
        self.client_id = settings.pdd_client_id
        self.client_secret = settings.pdd_client_secret

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def search(self, query: str) -> list[RawOffer]:
        if not self.configured:
            logger.info("pdd adapter not configured, skip")
            return []

        params = {
            "type": "pdd.ddk.goods.search",
            "client_id": self.client_id,
            "keyword": query,
            "page": "1",
            "page_size": "15",
        }
        params["sign"] = md5_sign(self.client_secret, params)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(API_URL, json=params)
            resp.raise_for_status()
            body = resp.json()
        raise_on_error_response(body, "pdd")

        goods = body.get("goods_search_response", {}).get("goods_list") or []

        now = datetime.now(UTC)
        offers: list[RawOffer] = []
        for g in goods:
            # 优先单独购买价，缺失时用拼团价；金额单位为分
            base = _cents_to_yuan(g.get("min_normal_price")) or _cents_to_yuan(
                g.get("min_group_price")
            )
            if base is None:
                continue
            coupon = _cents_to_yuan(g.get("coupon_discount"))
            final_price = max(base - (coupon or 0), 0.0)

            goods_id = str(g.get("goods_id") or "")
            goods_url = (
                f"https://mobile.yangkeduo.com/goods.html?goods_id={goods_id}" if goods_id else None
            )
            offers.append(
                RawOffer(
                    platform=self.platform,
                    platform_id=g.get("goods_sign") or goods_id,
                    title=g.get("goods_name") or "",
                    price=final_price,
                    original_price=base,
                    coupon=coupon,
                    url=goods_url,
                    image=g.get("goods_thumbnail_url"),
                    shop=g.get("mall_name"),
                    ts=now,
                )
            )
        return offers
