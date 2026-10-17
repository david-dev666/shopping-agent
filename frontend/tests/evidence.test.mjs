import test from 'node:test';
import assert from 'node:assert/strict';
import { evidencePanel, evidenceSummary } from '../../backend/static/evidence.mjs';
import { validTopPick, filterOffers, emptyFilters } from '../../backend/static/helpers.mjs';

const offer = status => ({ platform: 'jd', platform_id: '1', price: 99, tags: [], match_report: {
  status, reasons: ['<img src=x onerror=bad>'], checks: [{ label: '版本', status: 'unknown',
    requested: ['NFC版'], observed: [], excluded: [], title_evidence: ['<script>bad</script>'] }],
} });
test('规格证据只展示标题声明，未知值不伪装为已验证同款', () => {
  const panel = evidencePanel(offer('insufficient'));
  assert.match(panel, /规格信息不足/);
  assert.match(panel, /未验证实际 SKU/);
  assert.match(panel, /标题：未说明/);
  assert.match(panel, /&lt;img/);
  assert.doesNotMatch(panel, /<img|<script/);
});
test('混卖与冲突即使被响应指定为首选也不显示推荐购买卡', () => {
  for (const status of ['ambiguous', 'conflict']) {
    const candidate = offer(status);
    assert.equal(validTopPick({ offers: [candidate], top_pick: candidate }), null);
  }
});
test('汇总计数来自各候选的证据，不把未核对候选算作一致', () => {
  const summary = evidenceSummary([offer('ambiguous'), offer('ambiguous'), offer('compatible'), {}]);
  assert.match(summary, /混卖或多规格 <b>2/);
  assert.match(summary, /已识别属性一致 <b>1/);
  assert.equal(evidenceSummary([{}]), '');
});
test('兼容旧响应与未知状态，标签不执行外部内容', () => {
  assert.equal(evidencePanel({}), '');
  assert.match(evidencePanel(offer('<svg onload=bad>')), /规格信息不足/);
  assert.doesNotMatch(evidencePanel(offer('<svg onload=bad>')), /onload=bad/);
});
test('规格核对状态筛选不会把混卖和未核对报价算作一致', () => {
  const candidates = [offer('compatible'), offer('ambiguous'), {}];
  assert.deepEqual(filterOffers(candidates, { ...emptyFilters(), match_status: 'compatible' }), [candidates[0]]);
  assert.deepEqual(filterOffers(candidates, { ...emptyFilters(), match_status: 'ambiguous' }), [candidates[1]]);
});
