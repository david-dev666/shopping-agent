import test from 'node:test';
import assert from 'node:assert/strict';
import { clarificationPanel } from '../../backend/static/clarification.mjs';

const waiting = { status: 'awaiting_clarification', clarification_questions: [{ field: 'version', question: '希望哪个版本？', options: ['标准版', 'NFC版', '不限'] }] };

test('等待规格确认时提供必填选择和继续入口', () => {
  const html = clarificationPanel(waiting);
  assert.match(html, /id="clarification-form"/);
  assert.match(html, /name="version" required/);
  assert.match(html, /NFC版/);
  assert.match(html, /确认并继续/);
  assert.doesNotMatch(html, /disabled/);
});

test('候选或条件变化时须更新问题，已完成决策不展示追问', () => {
  assert.match(clarificationPanel(waiting, true), /disabled/);
  assert.equal(clarificationPanel({ ...waiting, status: 'complete' }), '');
  assert.equal(clarificationPanel({}), '');
});

test('追问内容与选项均转义', () => {
  const html = clarificationPanel({ ...waiting, clarification_questions: [{ field: 'version', question: '<img src=x>', options: ['"><script>alert(1)</script>'] }] });
  assert.doesNotMatch(html, /<img|<script/);
  assert.match(html, /&lt;script&gt;/);
});
