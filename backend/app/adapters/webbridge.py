import asyncio
import json
import logging

import httpx

from app.config import get_settings
from app.models.offers import RawOffer

logger = logging.getLogger(__name__)

# 京东搜索页提取器（新版 UI：JS 路由卡片，sku 从客服链接 pid 取）
# 检测到滑块验证时返回 {"captcha": true}，由 Python 侧转为提示
JD_EXTRACTOR = """
(() => {
  const txt = document.body.innerText || '';
  if (/快速验证|访问频繁|拖动滑块|请完成验证/.test(txt)) {
    return JSON.stringify({captcha: true, url: location.href});
  }
  const out = [];
  document.querySelectorAll('div[class*=card]').forEach(c => {
    const priceEl = c.querySelector('span[class*=price]');
    if (!priceEl) return;
    const price = parseFloat(priceEl.textContent.replace('¥',''));
    if (!(price > 0)) return;
    const pid = (c.querySelector('a[href*="pid="]')?.getAttribute('href') || '').match(/pid=(\\d+)/)?.[1];
    if (!pid) return;
    let title = [...c.querySelectorAll('[title]')].map(e => e.getAttribute('title'))
      .filter(t => t && t.length > 15).sort((a,b) => b.length - a.length)[0] || '';
    if (!title) {
      title = (c.innerText || '').split('\\n').map(s => s.trim()).filter(s => s.length > 15)
        .sort((a,b) => b.length - a.length)[0] || '';
    }
    const img = c.querySelector('img[data-src]')?.getAttribute('data-src')
      || c.querySelector('img')?.src;
    const shopEl = [...c.querySelectorAll('*')].find(e =>
      e.children.length===0 && /自营|旗舰店|专卖店|专营店/.test(e.textContent||''));
    const salesM = (c.innerText || '').match(/([\\d.,]+)\\s*([万亿]?)\\+?\\s*(?:人付款|人收货|条评价)/);
    let sales = null;
    if (salesM) {
      sales = parseFloat(salesM[1].replace(/,/g, ''));
      if (salesM[2] === '万') sales *= 10000;
      if (salesM[2] === '亿') sales *= 100000000;
      sales = Math.round(sales);
    }
    out.push({platform_id: pid, title: (title||'').slice(0,100), price,
      url: 'https://item.jd.com/' + pid + '.html',
      image: img ? ('https:' + img) : null,
      shop: shopEl ? shopEl.textContent.trim().slice(0,30) : null,
      sales});
  });
  return JSON.stringify(out.slice(0,15));
})()
"""

# 淘宝搜索页提取器（从商品链接向上找卡片，price 从 innerText 正则取）
TAOBAO_EXTRACTOR = """
(() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="item.taobao.com/item.htm"]').forEach(a => {
    const id = (a.href.match(/[?&]id=(\\d+)/) || [])[1];
    if (!id || seen.has(id)) return;
    const c = a.closest('[class*=doubleCard]') || a.closest('[class*=Card]');
    if (!c) return;
    const flat = (c.innerText || '').replace(/\\s+/g, ' ');
    const pm = flat.match(/¥\\s*(\\d+(?:\\.\\d+)?)/);
    if (!pm) return;
    const lines = (c.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
    const img = c.querySelector('img');
    const salesM = flat.match(/([\\d.,]+)\\s*([万亿]?)\\+?\\s*(?:人付款|人收货)/);
    let sales = null;
    if (salesM) {
      sales = parseFloat(salesM[1].replace(/,/g, ''));
      if (salesM[2] === '万') sales *= 10000;
      if (salesM[2] === '亿') sales *= 100000000;
      sales = Math.round(sales);
    }
    seen.add(id);
    out.push({platform_id: id, title: (lines[0] || '').slice(0,100),
      price: parseFloat(pm[1]),
      url: 'https://item.taobao.com/item.htm?id=' + id,
      image: img ? img.src : null,
      shop: (lines[lines.length-1] || '').slice(0,30),
      sales});
  });
  return JSON.stringify(out.slice(0,15));
})()
"""

# 拼多多搜索页提取器：从 SSR 数据 window.rawData 取商品列表（价格单位为分）
PDD_EXTRACTOR = """
(() => {
  const s = [...document.querySelectorAll('script')].filter(x => (x.textContent||'').includes('window.rawData='))[0];
  if (!s) return JSON.stringify([]);
  const t = s.textContent;
  const a = t.indexOf('window.rawData=') + 15;
  const b = t.indexOf(";document.dispatchEvent");
  let d;
  try { d = JSON.parse(t.slice(a, b)) } catch(e) { return JSON.stringify([]) }
  let arr = null;
  const walk = o => {
    if (!o || typeof o !== 'object' || arr) return;
    if (Array.isArray(o)) {
      if (o.length > 3 && o[0] && 'goodsID' in o[0]) { arr = o; return }
      o.forEach(walk); return;
    }
    Object.values(o).forEach(walk);
  };
  walk(d);
  if (!arr) return JSON.stringify([]);
  const toNum = t => {
    const m = String(t).match(/([\\d.]+)\\s*([万亿]?)\\+?(?:人|件)/);
    if (!m) return null;
    let n = parseFloat(m[1]);
    if (m[2] === '万') n *= 10000;
    if (m[2] === '亿') n *= 100000000;
    return Math.round(n);
  };
  return JSON.stringify(arr.slice(0,15).map(g => ({
    platform_id: String(g.goodsID),
    title: (g.goodsName || g.recTitle || '').slice(0,100),
    price: (g.price || 0) / 100,
    url: 'https://mobile.yangkeduo.com/' + (g.linkURL || ('goods.html?goods_id=' + g.goodsID)).split('&_oak')[0],
    image: (g.imgUrl || '').startsWith('//') ? 'https:' + g.imgUrl : (g.imgUrl || null),
    shop: (g.salesTip || '').slice(0,30),
    sales: g.salesTip ? toNum(g.salesTip) : null
  })));
})()
"""

SEARCH_URLS = {
    "jd": "https://search.jd.com/Search?keyword={kw}&enc=utf-8",
    "taobao": "https://s.taobao.com/search?q={kw}",
    "pdd": "https://mobile.yangkeduo.com/search_result.html?search_key={kw}",
}

EXTRACTORS = {"jd": JD_EXTRACTOR, "taobao": TAOBAO_EXTRACTOR, "pdd": PDD_EXTRACTOR}


class WebBridgeClient:
    """Kimi 浏览器扩展本地 daemon 的命令客户端。

    采集命令按调用方事件循环加锁串行执行：单 tab 模型下并发导航/求值会互相踩。
    锁按 event loop 惰性创建（LangGraph 同步节点经线程池跑 asyncio.run，
    每次是新循环，全局单锁会跨循环绑定报错）。
    """

    def __init__(self, base_url: str, session: str, timeout: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.timeout = timeout
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self) -> asyncio.Lock:
        loop_id = id(asyncio.get_running_loop())
        lock = self._locks.get(loop_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[loop_id] = lock
        return lock

    async def command(self, action: str, args: dict) -> dict:
        payload = {"action": action, "args": args, "session": self.session}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{self.base_url}/command", json=payload)
            resp.raise_for_status()
            body = resp.json()
        if not body.get("ok"):
            err = body.get("error", {})
            raise RuntimeError(f"webbridge {action} failed: {err.get('code')}: {err.get('message')}")
        return body["data"]

    async def navigate(self, url: str) -> None:
        await self.command("navigate", {"url": url})

    async def evaluate_json(self, code: str):
        data = await self.command("evaluate", {"code": code})
        value = data.get("value") if isinstance(data, dict) else None
        if isinstance(value, str):
            return json.loads(value)
        return value


_shared_client: WebBridgeClient | None = None


def get_webbridge_client() -> WebBridgeClient:
    global _shared_client
    if _shared_client is None:
        settings = get_settings()
        _shared_client = WebBridgeClient(
            base_url=settings.webbridge_base_url, session="shopping-agent"
        )
    return _shared_client


class WebBridgeAdapter:
    """通过用户真实浏览器（已登录态）采集单个平台的搜索报价。

    仅在对应联盟 API 未配置时启用，配置了 API key 的平台优先走官方接口。
    """

    def __init__(self, platform: str) -> None:
        self.platform = platform

    async def search(self, query: str) -> list[RawOffer]:
        from datetime import UTC, datetime
        from urllib.parse import quote

        client = get_webbridge_client()
        url = SEARCH_URLS[self.platform].format(kw=quote(query))
        async with client._get_lock():
            await client.navigate(url)
            # 页面懒加载（价格异步渲染）稍等片刻
            await asyncio.sleep(4)
            raw = await client.evaluate_json(EXTRACTORS[self.platform])

        # 滑块/风控验证：不绕过（项目边界），提示用户手点
        if isinstance(raw, dict) and raw.get("captcha"):
            raise RuntimeError(
                "NEED_MANUAL_VERIFY: 平台要求人工验证，请点击页面上的「去验证」完成滑块后重试"
            )

        now = datetime.now(UTC)
        offers = []
        for r in raw or []:
            try:
                price = float(r.get("price"))
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            offers.append(
                RawOffer(
                    platform=self.platform,
                    platform_id=str(r.get("platform_id") or ""),
                    title=(r.get("title") or "")[:512],
                    price=price,
                    url=r.get("url"),
                    image=r.get("image"),
                    shop=r.get("shop") or None,
                    sales=r.get("sales"),
                    ts=now,
                )
            )
        return offers
