/** Incremental SSE framing; UTF-8 decoding is kept at the fetch boundary. */
export class EventFrames {
  buffer = '';
  push(text) {
    this.buffer = (this.buffer + text).replace(/\r\n/g, '\n');
    const events = [];
    let boundary;
    while ((boundary = this.buffer.indexOf('\n\n')) !== -1) {
      const frame = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      let event = 'message';
      const data = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim();
        if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
      }
      if (data.length) events.push({ event, data: JSON.parse(data.join('\n')) });
    }
    return events;
  }
}

export async function streamChat(body, signal, onProgress) {
  const response = await fetch('/api/chat/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}）`);
  }
  if (!response.body) throw new Error('浏览器不支持执行进度流');
  const reader = response.body.getReader();
  const text = new TextDecoder();
  const frames = new EventFrames();
  let result;
  try {
    while (true) {
      const chunk = await reader.read();
      const events = frames.push(text.decode(chunk.value, { stream: !chunk.done }));
      for (const item of events) {
        if (item.event === 'progress') onProgress(item.data);
        if (item.event === 'error') throw new Error(item.data.message || '任务执行失败');
        if (item.event === 'result') result = item.data.result;
      }
      if (chunk.done) break;
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  if (!result) throw new Error('执行连接已中断，请重试');
  return result;
}
