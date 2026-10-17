export const PLATFORMS = { jd: '京东', taobao: '淘宝', pdd: '拼多多' };
export const offerKey = o => `${o.platform}:${o.platform_id}`;
export const money = n => Number(n).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export function safeUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return '';
  try {
    const url = new URL(value.startsWith('//') ? `https:${value}` : value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : '';
  } catch { return ''; }
}
export const emptyFilters = () => ({ platforms: [], exclude_tags: [], spec: null, price_min: null, price_max: null });
export function filterOffers(offers, filters, specs = {}) {
  const specKeys = filters.spec ? new Set(specs[filters.spec] || []) : null;
  return offers.filter(o => (!filters.platforms.length || filters.platforms.includes(o.platform))
    && !(o.tags || []).some(tag => filters.exclude_tags.includes(tag))
    && (!specKeys || specKeys.has(offerKey(o)))
    && (filters.price_min == null || o.price >= filters.price_min)
    && (filters.price_max == null || o.price <= filters.price_max));
}
export function orderOffers(offers, allOffers, items = [], sort = 'recommended') {
  if (sort === 'price') return [...offers].sort((a, b) => a.price - b.price);
  const ranks = new Map(items.map((item, n) => [offerKey(allOffers[item.index] || {}), n]));
  return [...offers].sort((a, b) => (ranks.get(offerKey(a)) ?? Infinity) - (ranks.get(offerKey(b)) ?? Infinity) || a.price - b.price);
}
export function validTopPick(data) {
  if (!data.top_pick || data.decision?.worth === 'skip') return null;
  const candidate = data.offers.find(o => offerKey(o) === offerKey(data.top_pick));
  const budget = data.intent?.budget;
  if (!candidate || (candidate.tags || []).length || (budget != null && candidate.price > budget)) return null;
  return candidate;
}
export function readRecent(storage) {
  try {
    const value = JSON.parse(storage.getItem('shopping-agent:recent') || '[]');
    return Array.isArray(value) ? value.filter(q => typeof q === 'string' && q.length <= 500).slice(0, 5) : [];
  } catch { return []; }
}
export function salesLabel(n) {
  if (n == null) return '销量未提供';
  return `销量 ${n >= 10000 ? `${(n / 10000).toFixed(1)}万` : n.toLocaleString('zh-CN')}`;
}

export function provenance(data) {
  if (data.demo || data.origin === 'sample') return { kind: 'sample', label: '样例数据', description: '固定样例 · 未进行实时采集' };
  if (data.cached || data.origin === 'cache') {
    const age = Math.max(0, Math.floor(Number(data.cache_age_seconds) || 0));
    return { kind: 'cache', label: '缓存报价', description: `命中时已有 ${age} 秒 · 缓存有效期 5 分钟` };
  }
  if (data.origin === 'refine') return { kind: 'refine', label: '已更新推荐', description: '复用已有报价 · 未重新采集' };
  return { kind: 'live', label: '本次采集', description: '来自本次平台查询，具体采集时间见商品卡片' };
}

// Invalid drafts must not silently replace the last valid filter or budget.
export function moneyRange(minText, maxText, badInput = false) {
  const parse = text => String(text).trim() === '' ? null : Number(text);
  const min = parse(minText), max = parse(maxText);
  const valid = n => n == null || (Number.isFinite(n) && n >= 0 && Math.abs(n * 100 - Math.round(n * 100)) < 0.000001);
  if (badInput || !valid(min) || !valid(max)) return { error: '请输入不小于 0、最多两位小数的金额', min, max };
  if (min != null && max != null && min > max) return { error: '最低报价不能高于最高报价', min, max };
  return { error: '', min, max };
}
