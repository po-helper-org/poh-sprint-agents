/**
 * Подделка сетевого порта. Тесты описывают ответы JIRA таблицей «путь → ответ»,
 * поэтому разбор проверяется на настоящих формах ответов, без сети и без стенда.
 */
import type { HttpPort, HttpRequest, HttpResponse } from '../../src/ports.js'

export interface FakeReply {
  status?: number
  contentType?: string
  /** Объект будет сериализован; строка уйдёт как есть. */
  body?: unknown
  headers?: Record<string, string>
}

export interface Recorded {
  url: string
  request: HttpRequest
}

export interface FakeHttp {
  port: HttpPort
  calls: Recorded[]
}

/** Порт из функции-маршрутизатора. Вернула `undefined` — отвечаем 404. */
export function fakeHttp(route: (url: URL, request: HttpRequest) => FakeReply | undefined): FakeHttp {
  const calls: Recorded[] = []
  const port: HttpPort = async (url, request) => {
    calls.push({ url, request })
    const reply = route(new URL(url), request) ?? { status: 404, body: { errorMessages: ['нет такого пути'] } }
    const status = reply.status ?? 200
    const contentType = reply.contentType ?? 'application/json;charset=UTF-8'
    const headers = new Map<string, string>([['content-type', contentType]])
    for (const [key, value] of Object.entries(reply.headers ?? {})) headers.set(key.toLowerCase(), value)
    const body = typeof reply.body === 'string' ? reply.body : JSON.stringify(reply.body ?? {})
    const response: HttpResponse = {
      status,
      ok: status >= 200 && status < 300,
      headers: { get: (name) => headers.get(name.toLowerCase()) ?? null },
      text: async () => body,
    }
    return response
  }
  return { port, calls }
}

/** Ответ JIRA на поиск: обёртка вокруг задач. */
export function searchReply(issues: unknown[], total = issues.length): FakeReply {
  return { body: { startAt: 0, maxResults: issues.length, total, issues } }
}

/** Одна задача в форме Server/DC. */
export function issueJson(key: string, fields: Record<string, unknown>): Record<string, unknown> {
  return { id: '1', key, fields }
}
