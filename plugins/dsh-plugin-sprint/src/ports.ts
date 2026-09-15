/**
 * Порт доступа в сеть. Коннектор знает порт, а не `fetch`: тесты подменяют его
 * подделкой и проверяют разбор ответов без сети и без живой JIRA.
 */

/** Ответ, которого коннектору достаточно. Подмножество `Response`. */
export interface HttpResponse {
  readonly status: number
  readonly ok: boolean
  readonly headers: { get(name: string): string | null }
  text(): Promise<string>
}

/** Запрос, который делает коннектор. */
export interface HttpRequest {
  readonly method: 'GET' | 'POST'
  readonly headers: Record<string, string>
  readonly body?: string
  readonly signal?: AbortSignal
}

/** Порт: адрес и запрос — ответ. Бросает только на сетевом отказе. */
export type HttpPort = (url: string, request: HttpRequest) => Promise<HttpResponse>

/** Штатная реализация порта поверх глобального `fetch` (Node 22+). */
export const fetchPort: HttpPort = async (url, request) => {
  const response = await fetch(url, {
    method: request.method,
    headers: request.headers,
    body: request.body,
    signal: request.signal,
  })
  return response
}

/**
 * Сигнал с бюджетом ожидания: свой таймер плюс сигнал вызывающего, если он есть.
 * Отдельная функция, потому что `AbortSignal.any` принимает только массив, а
 * вызывающий сигнал необязателен.
 */
export function deadline(timeoutMs: number, caller?: AbortSignal): AbortSignal {
  const own = AbortSignal.timeout(timeoutMs)
  return caller === undefined ? own : AbortSignal.any([own, caller])
}
