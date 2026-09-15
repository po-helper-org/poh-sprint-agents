/**
 * Канал раздела. Одна регистрация, подкоманды разбираются внутри — как у
 * соседних разделов харнесса.
 *
 * Канал нужен ровно для карточки настроек: кнопка «Протестировать» и строка
 * состояния. Модель ходит в JIRA не сюда, а инструментами (`tools.ts`).
 */
import { JiraError, asJiraError } from './errors.js'
import type { ConnectionReport, JiraDraft, SprintConnector } from './connector.js'
import { renderConnection } from './render.js'

export const SPRINT_CHANNEL = '/sprint'

export type RpcResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: { code: string; message: string; details: object } }

function ok<T>(value: T): RpcResult<T> {
  return { ok: true, value }
}

function fail(code: string, message: string): RpcResult<never> {
  return { ok: false, error: { code, message, details: {} } }
}

/** Ответ на `jira.test`: отчёт плюс готовая строка для карточки. */
export interface TestReply {
  report: ConnectionReport
  summary: string
}

/** Черновик карточки из полезной нагрузки. Чужие поля отбрасываются. */
export function draftOf(payload: unknown): JiraDraft | undefined {
  const node = typeof payload === 'object' && payload !== null
    ? (payload as { draft?: unknown }).draft
    : undefined
  if (typeof node !== 'object' || node === null) return undefined
  const raw = node as Record<string, unknown>
  const draft: JiraDraft = {}
  for (const field of ['baseUrl', 'token', 'email', 'projectKey', 'storiesJql', 'storyPointsField'] as const) {
    const value = raw[field]
    if (typeof value === 'string') draft[field] = value
  }
  return Object.keys(draft).length === 0 ? undefined : draft
}

/**
 * Разбор подкоманды канала.
 * @returns всегда значение: наружу канала отказ уходит результатом, а не броском.
 */
export async function dispatch(
  connector: SprintConnector,
  endpoint: string,
  payload: unknown,
  signal?: AbortSignal,
): Promise<RpcResult<unknown>> {
  try {
    switch (endpoint) {
      case 'jira.test': {
        const report = await connector.test(draftOf(payload), signal)
        const reply: TestReply = { report, summary: renderConnection(report) }
        return ok(reply)
      }
      case 'jira.status':
        return ok({ configured: connector.configured() })
      default:
        return fail('unknown-endpoint', `неизвестная подкоманда канала: ${endpoint}`)
    }
  } catch (error) {
    const failure = error instanceof JiraError ? error : asJiraError(error)
    return fail(failure.kind, failure.message)
  }
}
