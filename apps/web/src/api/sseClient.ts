/**
 * SSE 流式客户端。
 * EventSource 不支持 POST,这里用 fetch + ReadableStream 手动解析 event/data 块。
 */

export interface SseEvent {
  event: string
  data: Record<string, unknown>
}

export async function* sseStream(
  url: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || `请求失败:${response.status}`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let separator = buffer.indexOf('\n\n')
    while (separator !== -1) {
      const block = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      let event = 'message'
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) yield { event, data: JSON.parse(data) as Record<string, unknown> }
      separator = buffer.indexOf('\n\n')
    }
  }
}
