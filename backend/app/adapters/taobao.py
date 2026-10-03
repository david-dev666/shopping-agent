import logging
from datetime import UTC, datetime

import httpx

from app.adapters.signing import md5_sign, raise_on_error_response
from app.config import Settings
from app.models.offers import RawOffer

logger = logging.getLogger(__name__)

API_URL = "https://eco.taobao.com/router/rest"


def _f(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class TaobaoAdapter:
    """淘宝客物料搜索（taobao.tbk.dg.material.optional）。

    无 app_key/app_secret/adzone_id 时返回空列表，不造假数据。
    """

    platform = "taobao"

    def __init__(self, settings: Settings) -> None:
        self.app_key = settings.tbk_app_key
        self.app_secret = settings.tbk_app_secret
        self.adzone_id = settings.tbk_adzone_id

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.app_secret and self.adzone_id)

    async def search(self, query: str) -> list[RawOffer]:
        if not self.configured:
            logger.info("taobao adapter not configured, skip")
            return []

        params = {
            "method": "taobao.tbk.dg.material.optional",
            "app_key": self.app_key,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
            "q": query,
            "adzone_id": str(self.adzone_id),
        }
        params["sign"] = md5_sign(self.app_secret, params)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(API_URL, data=params)
            resp.raise_for_status()
            body = resp.json()
        raise_on_error_response(body, "taobao")

        data = (
            body.get("tbk_dg_material_optional_response", {})
            .get("result_list", {})
            .get("map_data")
            or []
        )

        now = datetime.now(UTC)
        offers: list[RawOffer] = []
        for m in data:
            price = _f(m.get("zk_final_price"))
            if price is None:
                continue
            coupon = _f(m.get("coupon_amount"))
            start_fee = _f(m.get("coupon_start_fee")) or 0.0
            if coupon and price >= start_fee:
                final_price = max(price - coupon, 0.0)
            else:
                coupon = None
                final_price = price

            offers.append(
                RawOffer(
                    platform=self.platform,
                    platform_id=str(m.get("item_id") or m.get("num_iid") or ""),
                    title=m.get("title") or "",
                    price=final_price,
                    original_price=_f(m.get("reserve_price")) or price,
                    coupon=coupon,
                    url=m.get("coupon_click_url") or m.get("url"),
                    image=m.get("pict_url"),
                    shop=m.get("shop_title"),
                    ts=now,
                )
            )
        return offers
