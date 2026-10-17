import { escapeHtml as h } from './helpers.mjs?v=20261017-identity2';

const labels = {
  compatible: '已识别属性一致',
  conflict: '规格冲突',
  ambiguous: '混卖或多规格',
  insufficient: '规格信息不足',
};
const fieldLabels = { consistent: '标题一致', conflict: '不一致', ambiguous: '多项待确认', unknown: '未说明', not_requested: '未限定' };
const scope = '仅核对标题文字，未验证实际 SKU、优惠资格或成交价。';

export function evidencePanel(offer) {
  const report = offer.match_report;
  if (!report) return '';
  const kind = Object.hasOwn(labels, report.status) ? report.status : 'insufficient';
  const checks = (report.checks || []).filter(c => c.requested?.length || c.observed?.length || c.excluded?.length);
  return `<details class="match-evidence ${kind}"><summary><span class="match-indicator" aria-hidden="true"></span><span>规格核对 · ${labels[kind]}</span><span class="match-expand" aria-hidden="true">⌄</span></summary><p class="match-scope">${scope}</p>${report.reasons?.length ? `<ul class="match-reasons">${report.reasons.map(r => `<li>${h(r)}</li>`).join('')}</ul>` : ''}<dl class="match-fields">${checks.map(c => `<div><dt>${h(c.label)}<small>${h(fieldLabels[c.status] || '待确认')}</small></dt><dd><span>需求：${h(c.requested?.join(' / ') || '未限定')}</span>${c.excluded?.length ? `<span>排除：${h(c.excluded.join(' / '))}</span>` : ''}<span>标题：${h(c.observed?.join(' / ') || '未说明')}</span>${c.title_evidence?.length ? `<q>${h(c.title_evidence.join(' · '))}</q>` : ''}</dd></div>`).join('')}</dl></details>`;
}

export function evidenceSummary(offers) {
  const reports = offers.map(o => o.match_report).filter(Boolean);
  if (!reports.length) return '';
  const counts = Object.fromEntries(Object.keys(labels).map(k => [k, reports.filter(r => r.status === k).length]));
  return `<div class="match-overview"><div><strong>标题规格核对</strong><p>${scope}</p><p>优先覆盖手环代数与版本；容量、套装等属性暂未核对。</p></div><div class="match-counts">${Object.entries(counts).filter(([, n]) => n).map(([k, n]) => `<span class="${k}">${labels[k]} <b>${n}</b></span>`).join('')}</div></div>`;
}
