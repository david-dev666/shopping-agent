from datetime import UTC, datetime

from pydantic import BaseModel, Field

PLATFORMS = ("jd", "taobao", "pdd")


class RawOffer(BaseModel):
    """各平台采集输出的统一结构。"""

    platform: str = Field(description="平台标识: jd / taobao / pdd")
    platform_id: str
    title: str
    price: float = Field(description="到手价（券后），单位元")
    original_price: float | None = Field(default=None, description="原始价，单位元")
    coupon: float | None = Field(default=None, description="券金额，单位元")
    url: str | None = Field(default=None, description="购买入口")
    image: str | None = None
    shop: str | None = None
    sales: int | None = Field(default=None, description="已售数量（件），未知为 None")
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
