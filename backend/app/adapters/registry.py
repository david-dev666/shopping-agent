import asyncio
import logging

from app.adapters.jd import JDUnionAdapter
from app.adapters.pdd import PddAdapter
from app.adapters.taobao import TaobaoAdapter
from app.adapters.webbridge import WebBridgeAdapter
from app.config import Settings
from app.models.offers import RawOffer

logger = logging.getLogger(__name__)


def get_adapters(settings: Settings) -> list:
    """每平台选一个数据源：配了官方联盟 API key 优先 API，否则走浏览器采集。

    二者都没有配置时返回空结果，不造假数据。
    """
    union = {
        "jd": JDUnionAdapter(settings),
        "pdd": PddAdapter(settings),
        "taobao": TaobaoAdapter(settings),
    }
    adapters = []
    for platform, u in union.items():
        if u.configured:
            adapters.append(u)
        elif settings.webbridge_enabled:
            adapters.append(WebBridgeAdapter(platform))
    return adapters


# WebBridge 单 tab 串行采集顺序：快的平台先执行，缩短整体尾延迟
WB_ORDER = {"pdd": 0, "taobao": 1, "jd": 2}


async def search_all(
    query: str, adapters: list
) -> tuple[list[RawOffer], dict[str, str]]:
    """并发查询所有平台，返回按到手价升序的 offers 和各平台错误信息。

    浏览器采集的平台共用一把锁（单 tab），按预期耗时排序提交任务
    （PDD SSR 秒出 → 淘宝 → 京东），联盟 API 平台真并发不受影响。
    """
    ordered = sorted(
        adapters,
        key=lambda a: WB_ORDER.get(getattr(a, "platform", ""), 9)
        if isinstance(a, WebBridgeAdapter)
        else -1,
    )
    results = await asyncio.gather(
        *(a.search(query) for a in ordered), return_exceptions=True
    )
    offers: list[RawOffer] = []
    errors: dict[str, str] = {}
    for adapter, result in zip(ordered, results, strict=True):
        if isinstance(result, BaseException):
            errors[adapter.platform] = repr(result)
            logger.warning("adapter %s failed: %r", adapter.platform, result)
        else:
            offers.extend(result)
    offers.sort(key=lambda o: o.price)
    return offers, errors
