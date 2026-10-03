import json
import logging
from datetime import UTC, datetime

import httpx

from app.adapters.signing import md5_sign, raise_on_error_response
from app.config import Settings
from app.models.offers import RawOffer

logger = logging.getLogger(__name__)

API_URL = "https://api.jd.com/routerjson"


def _f(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class JDUnionAdapter:
    """京东联盟商品搜索（jd.union.open.goods.search）。

    无 app_key/app_secret 时返回空列表，不造假数据。
    """

    platform = "jd"

    def __init__(self, settings: Settings) -> None:
        self.app_key = settings.jd_union_app_key
        self.app_secret = settings.jd_union_app_secret

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret)

    async def search(self, query: str) -> list[RawOffer]:
        if not self.configured:
            logger.info("jd adapter not configured, skip")
            return []

        param_json = json.dumps(
            {"goodsReqDTO": {"keyword": query, "pageIndex": 1, "pageSize": 15}},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        params = {
            "method": "jd.union.open.goods.search",
            "app_key": self.app_key,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "1.0",
            "param_json": param_json,
        }
        params["sign"] = md5_sign(self.app_secret, params)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(API_URL, params=params)
            resp.raise_for_status()
            body = resp.json()
        raise_on_error_response(body, "jd")

        # 京东联盟的 result 是二次 JSON 编码的字符串
        result = body.get("jd_union_open_goods_search_responce", {}).get("result")
        if isinstance(result, str):
            result = json.loads(result)
        goods = (result or {}).get("data") or []

        now = datetime.now(UTC)
        offers: list[RawOffer] = []
        for g in goods:
            price = _f((g.get("priceInfo") or {}).get("price"))
            if price is None:
                continue

            # couponList: [{"discount": 券额, "quota": 使用门槛}]，取可用且面额最大的一张
            coupons = (g.get("couponInfo") or {}).get("couponList") or []
            best = max(
                (
                    c
                    for c in coupons
                    if _f(c.get("discount"))
                    and (_f(c.get("quota")) or 0) <= price
                ),
                key=lambda c: _f(c.get("discount")) or 0,
                default=None,
            )
            coupon = _f(best.get("discount")) if best else None
            final_price = max(price - (coupon or 0), 0.0)

            image_list = (g.get("imageInfo") or {}).get("imageList") or []
            offers.append(
                RawOffer(
                    platform=self.platform,
                    platform_id=str(g.get("skuId") or ""),
                    title=g.get("skuName") or "",
                    price=final_price,
                    original_price=price,
                    coupon=coupon,
                    url=g.get("materialURL"),
                    image=image_list[0].get("url") if image_list else None,
                    shop=(g.get("shopInfo") or {}).get("shopName"),
                    ts=now,
                )
            )
        return offers
