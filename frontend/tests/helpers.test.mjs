import test from 'node:test';
import assert from 'node:assert/strict';
import { emptyFilters, filterOffers, offerKey, safeUrl, orderOffers, validTopPick, escapeHtml, readRecent, moneyRange } from '../../backend/static/helpers.mjs';

const offers = [
  { platform: 'jd', platform_id: '1', title: 'NFC', price: 199, tags: [] },
  { platform: 'taobao', platform_id: '1', title: '标准版', price: 99, tags: ['疑似二手'] },
  { platform: 'pdd', platform_id: '2', title: '标准版', price: 299, tags: [] },
];
test('规格分组中的跨平台相同 ID 不串入其他商品', () => {
  assert.deepEqual(filterOffers(offers, { ...emptyFilters(), spec: 'NFC版' }, { NFC版: ['jd:1'] }), [offers[0]]);
  assert.notEqual(offerKey(offers[0]), offerKey(offers[1]));
});
test('平台、标签和价格组合筛选；空条件保留全部', () => {
  assert.deepEqual(filterOffers(offers, emptyFilters()), offers);
  assert.deepEqual(filterOffers(offers, { ...emptyFilters(), platforms: ['jd'], price_max: 200 }), [offers[0]]);
  assert.deepEqual(filterOffers(offers, { ...emptyFilters(), exclude_tags: ['疑似二手'], price_min: 200 }), [offers[2]]);
});
test('重排后索引映射到对应商品，筛选不会错用名次', () => {
  assert.deepEqual(orderOffers([offers[0], offers[2]], offers, [{ index: 2 }, { index: 0 }]), [offers[2], offers[0]]);
  assert.deepEqual(orderOffers(offers, offers, [], 'price'), [offers[1], offers[0], offers[2]]);
});
for (const value of ['javascript:alert(1)', 'data:text/html,test', '/unsafe', '', null, 'not a url', 'vbscript:test']) {
  test(`拒绝不可用的商品链接 ${value}`, () => assert.equal(safeUrl(value), ''));
}
test('允许 HTTP(S) 与协议相对图片地址', () => {
  assert.equal(safeUrl('//img.example.com/a.jpg'), 'https://img.example.com/a.jpg');
  assert.equal(safeUrl('https://item.jd.com/1.html'), 'https://item.jd.com/1.html');
});
test('首选在预算内、无警示且存在于实际候选集', () => {
  assert.equal(validTopPick({ offers, top_pick: offers[0], decision: { worth: 'skip' } }), null);
  assert.equal(validTopPick({ offers, top_pick: offers[0], intent: { budget: 100 } }), null);
  assert.equal(validTopPick({ offers, top_pick: offers[1] }), null);
  assert.equal(validTopPick({ offers: [], top_pick: offers[0] }), null);
  assert.deepEqual(validTopPick({ offers, top_pick: offers[0], intent: { budget: 199 } }), offers[0]);
});
test('标题与属性字符转义，避免外部商品信息注入页面', () => {
  assert.equal(escapeHtml('<img src=x onerror="bad">'), '&lt;img src=x onerror=&quot;bad&quot;&gt;');
});
test('损坏或格式异常的本地历史不影响加载', () => {
  for (const value of ['broken', 'null', '{"x":1}', '42']) assert.deepEqual(readRecent({ getItem: () => value }), []);
  assert.deepEqual(readRecent({ getItem: () => '["小米手环9", null, 42]' }), ['小米手环9']);
});

test('首选卡使用实际候选的警示和价格，不相信副本中的旧字段', () => {
  assert.equal(validTopPick({ offers, top_pick: { ...offers[1], tags: [] } }), null);
  assert.equal(validTopPick({ offers, top_pick: { ...offers[2], price: 1 }, intent: { budget: 100 } }), null);
});

test('价格草稿接受空值、零、相等边界和有效小数', () => {
  assert.deepEqual(moneyRange('', ''), { error: '', min: null, max: null });
  assert.deepEqual(moneyRange('0', '0'), { error: '', min: 0, max: 0 });
  assert.deepEqual(moneyRange('199.99', '300'), { error: '', min: 199.99, max: 300 });
});
test('无效金额和倒置区间不能作为新预算或筛选条件', () => {
  for (const input of ['-1', 'Infinity', 'NaN', 'text', '0.001']) assert.ok(moneyRange('', input).error, input);
  assert.ok(moneyRange('300', '200').error);
  assert.ok(moneyRange('', '', true).error); // number input may report badInput while value is empty.
  assert.equal(moneyRange('200', '300').error, '');
});
