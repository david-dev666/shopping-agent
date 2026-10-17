import test from 'node:test';
import assert from 'node:assert/strict';
import { EventFrames, streamChat } from '../../backend/static/stream.mjs';
import { provenance } from '../../backend/static/helpers.mjs';

test('SSE 分帧支持分割在任意位置的 CRLF、JSON 与心跳', () => {
  const parser = new EventFrames();
  const input = ': keepalive\r\n\r\nevent: progress\r\ndata: {"node":"理解需求"}\r\n\r\nevent: result\r\ndata: {"result":{"offers":[]}}\r\n\r\n';
  const events = [...input].flatMap(char => parser.push(char));
  assert.equal(events.length, 2);
  assert.equal(events[0].data.node, '理解需求');
  assert.equal(events[1].event, 'result');
});

test('真实进度流跨 UTF-8 字节解码，不丢失中文或最终结果', async () => {
  const original = globalThis.fetch;
  const bytes = new TextEncoder().encode('event: progress\ndata: {"node":"research","status":"running"}\n\nevent: result\ndata: {"result":{"query":"小米手环9","offers":[]}}\n\n');
  globalThis.fetch = async () => new Response(new ReadableStream({ start(controller) { for (const byte of bytes) controller.enqueue(Uint8Array.of(byte)); controller.close(); } }));
  try {
    const progress = [];
    const result = await streamChat({}, undefined, event => progress.push(event));
    assert.equal(result.query, '小米手环9');
    assert.deepEqual(progress, [{ node: 'research', status: 'running' }]);
  } finally { globalThis.fetch = original; }
});

test('执行失败和意外断开都不会被当成成功结果', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response('event: error\ndata: {"message":"采集失败"}\n\n');
    await assert.rejects(streamChat({}, undefined, () => {}), /采集失败/);
    globalThis.fetch = async () => new Response('event: progress\ndata: {"node":"intent"}\n\n');
    await assert.rejects(streamChat({}, undefined, () => {}), /中断/);
  } finally { globalThis.fetch = original; }
});

test('样例、缓存、重新评估与实时查询有明确来源，优先识别样例', () => {
  assert.equal(provenance({ demo: true, cached: true }).kind, 'sample');
  assert.equal(provenance({ cached: true, cache_age_seconds: 42 }).description, '命中时已有 42 秒 · 缓存有效期 5 分钟');
  assert.equal(provenance({ origin: 'refine' }).kind, 'refine');
  assert.equal(provenance({ origin: 'live' }).kind, 'live');
});
