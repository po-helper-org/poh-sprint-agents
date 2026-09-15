/**
 * Ошибки коннектора. Текст каждой годится показать человеку как есть: он уходит
 * и в карточку настроек («Протестировать»), и в результат инструмента модели.
 *
 * Разделение по классам — не украшение: карточка красит статус по `kind`, а
 * инструмент по нему же решает, что советовать («настройте коннектор» против
 * «JIRA ответила отказом»).
 */

/** Код отказа. Один код — одна причина, по которой ничего не получилось. */
export type JiraFailureKind =
  /** Коннектор не настроен: нет адреса или токена. */
  | 'not-configured'
  /** Настройка задана, но негодна (адрес без схемы, пустой проект при пустом JQL). */
  | 'bad-config'
  /** Сеть: DNS, отказ соединения, обрыв. */
  | 'network'
  /** Превышен бюджет ожидания. */
  | 'timeout'
  /** Токен не принят (401) или доступа не хватает (403). */
  | 'auth'
  /** JIRA ответила кодом ошибки. */
  | 'http'
  /** Ответ не разобран: не JSON — как правило, страница входа SSO вместо API. */
  | 'not-json'
  /** Запрос отвергнут самой JIRA (неверный JQL, неизвестное поле). */
  | 'query'

/** Отказ коннектора с текстом, годным для человека. */
export class JiraError extends Error {
  readonly kind: JiraFailureKind
  /** HTTP-код, когда он был. */
  readonly status?: number

  constructor(kind: JiraFailureKind, message: string, status?: number) {
    super(message)
    this.name = 'JiraError'
    this.kind = kind
    this.status = status
  }
}

/** Приводит любое пойманное значение к отказу коннектора. */
export function asJiraError(error: unknown): JiraError {
  if (error instanceof JiraError) return error
  if (error instanceof Error) {
    if (error.name === 'AbortError' || error.name === 'TimeoutError') {
      return new JiraError('timeout', 'JIRA не ответила в отведённое время')
    }
    return new JiraError('network', `не удалось обратиться к JIRA: ${error.message}`)
  }
  return new JiraError('network', `не удалось обратиться к JIRA: ${String(error)}`)
}
