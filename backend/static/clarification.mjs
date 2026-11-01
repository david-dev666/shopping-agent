import { escapeHtml as h } from './helpers.mjs';

export function clarificationPanel(data, stale = false) {
  const questions = data.clarification_questions || [];
  if (data.status !== 'awaiting_clarification' || !questions.length) return '';
  return `<form id="clarification-form" class="no-pick"><h3>先确认一下规格</h3><p>当前候选有不同规格。确认后会使用已有报价继续比较。</p>${questions.map((q, index) => `<p><label for="clarification-${index}">${h(q.question)}</label><select id="clarification-${index}" name="${h(q.field)}" required><option value="">请选择</option>${q.options.map(value => `<option value="${h(value)}">${h(value)}</option>`).join('')}</select></p>`).join('')}<button type="submit" class="button primary" ${stale ? 'disabled' : ''}>确认并继续</button>${stale ? '<p>请先更新推荐，再回答当前规格问题。</p>' : ''}</form>`;
}
