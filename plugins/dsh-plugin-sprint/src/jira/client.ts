/**
 * Клиент корпоративной JIRA. Прямой REST поверх порта — без MCP-моста: мост
 * добавлял третий процесс между моделью и трекером, и именно на нём сценарий
 * рассыпался (см. README раздела).
 *
 * Считаем целью Server/DC (`/rest/api/2`): именно так устроены корпоративные
 * контуры. Cloud поддержан отступлением: когда `/rest/api/2/search` отвечает
 * 404/410 (Atlassian убрала его в облаке), тот же запрос уходит в
 * `/rest/api/3/search/jql`. Ответы у обоих разбираются одним нормализатором.
 */
import { JiraError, asJiraError } from '../errors.js'
import { deadline, type HttpPort } from '../ports.js'
import type { JiraIdentity, JiraIssue, JiraSearchResult } from './model.js'
import { LIST_FIELDS, normalizeIssue } from './normalize.js'

/** Куда и чем ходить. Адрес уже нормализован (`normalizeBaseUrl`). */
export interface JiraTarget {
  baseUrl: string
  token: string
  /** Непусто — Basic (Jira Cloud), пусто — Bearer (Server/DC с персональным токеном). */
  email: string
  /** Поле оценки из настроек. Пусто — клиент ищет его сам по каталогу полей. */
  storyPointsField: string
}

export interface JiraClientOptions {
  http: HttpPort
  /** Бюджет ожидания одного запроса. */
  timeoutMs: number
}

interface RequestOptions {
  method: 'GET' | 'POST'
  path: string
  query?: Record<string, string>
  body?: unknown
  signal?: AbortSignal
}

/** Заголовок авторизации для цели. */
export function authorizationOf(target: JiraTarget): string {
  const email = target.email.trim()
  if (email !== '') return `Basic ${Buffer.from(`${email}:${target.token}`, 'utf8').toString('base64')}`
  return `Bearer ${target.token}`
}

export class JiraClient {
  private pointsField: Promise<string | undefined> | undefined

  constructor(private readonly target: JiraTarget, private readonly options: JiraClientOptions) {}

  /** Кто мы для этой JIRA. Им же проверяется подключение. */
  async myself(signal?: AbortSignal): Promise<JiraIdentity> {
    const body = await this.request({ method: 'GET', path: '/rest/api/2/myself', signal })
    const node = (typeof body === 'object' && body !== null ? body : {}) as Record<string, unknown>
    const displayName = typeof node.displayName === 'string' ? node.displayName : ''
    const name = typeof node.name === 'string'
      ? node.name
      : typeof node.accountId === 'string' ? node.accountId : ''
    if (displayName === '' && name === '') {
      throw new JiraError('not-json', 'JIRA ответила на /myself без учётной записи — адрес ведёт не в REST API')
    }
    const identity: JiraIdentity = { displayName: displayName === '' ? name : displayName, name }
    if (typeof node.emailAddress === 'string' && node.emailAddress !== '') identity.email = node.emailAddress
    return identity
  }

  /** Поиск по JQL. */
  async search(
    jql: string,
    options: { limit: number; withDescription?: boolean; signal?: AbortSignal },
  ): Promise<JiraSearchResult> {
    const pointsField = await this.resolvePointsField(options.signal)
    const fields = [...LIST_FIELDS, 'sprint']
    if (pointsField !== undefined) fields.push(pointsField)
    if (options.withDescription === true) fields.push('description')

    const body = await this.searchBody(jql, fields, options.limit, options.signal)
    const node = (typeof body === 'object' && body !== null ? body : {}) as Record<string, unknown>
    const raw = Array.isArray(node.issues) ? node.issues : []
    const issues: JiraIssue[] = []
    for (const entry of raw) {
      const issue = normalizeIssue(entry, {
        baseUrl: this.target.baseUrl,
        ...(pointsField === undefined ? {} : { storyPointsField: pointsField }),
        ...(options.withDescription === true ? { withDescription: true } : {}),
      })
      if (issue !== undefined) issues.push(issue)
    }
    // Cloud-ответ не несёт `total`; тогда единственное честное число — сколько вернулось.
    const total = typeof node.total === 'number' ? node.total : issues.length
    return { jql, total, issues }
  }

  /** Одна задача с описанием. */
  async issue(key: string, signal?: AbortSignal): Promise<JiraIssue> {
    const trimmed = key.trim().toUpperCase()
    if (!/^[A-Z][A-Z0-9_]*-\d+$/.test(trimmed)) {
      throw new JiraError('query', `«${key}» не похож на ключ задачи JIRA — ожидается вид PROJ-123`)
    }
    const pointsField = await this.resolvePointsField(signal)
    const fields = [...LIST_FIELDS, 'sprint', 'description']
    if (pointsField !== undefined) fields.push(pointsField)
    const body = await this.request({
      method: 'GET',
      path: `/rest/api/2/issue/${encodeURIComponent(trimmed)}`,
      query: { fields: fields.join(',') },
      signal,
    })
    const issue = normalizeIssue(body, {
      baseUrl: this.target.baseUrl,
      ...(pointsField === undefined ? {} : { storyPointsField: pointsField }),
      withDescription: true,
    })
    if (issue === undefined) throw new JiraError('not-json', `JIRA вернула по ${trimmed} ответ без задачи`)
    return issue
  }

  /**
   * Поиск: сначала `/rest/api/2/search` (Server/DC), при 404/410 — облачный
   * `/rest/api/3/search/jql`. Отступление делается один раз на вызов и молча:
   * для человека это один и тот же поиск.
   */
  private async searchBody(
    jql: string, fields: string[], limit: number, signal?: AbortSignal,
  ): Promise<unknown> {
    try {
      return await this.request({
        method: 'POST',
        path: '/rest/api/2/search',
        body: { jql, maxResults: limit, startAt: 0, fields },
        signal,
      })
    } catch (error) {
      const failure = asJiraError(error)
      if (failure.kind !== 'http' || (failure.status !== 404 && failure.status !== 410)) throw failure
      return this.request({
        method: 'GET',
        path: '/rest/api/3/search/jql',
        query: { jql, maxResults: String(limit), fields: fields.join(',') },
        signal,
      })
    }
  }

  /**
   * Поле оценки: заданное в настройках либо найденное по каталогу полей. Ищется
   * один раз на клиента; отказ каталога не роняет запрос — задачи просто придут
   * без SP, и это видно, в отличие от подставленного наугад customfield.
   */
  private async resolvePointsField(signal?: AbortSignal): Promise<string | undefined> {
    const own = this.target.storyPointsField.trim()
    if (own !== '') return own
    this.pointsField ??= this.discoverPointsField(signal).catch(() => undefined)
    return this.pointsField
  }

  private async discoverPointsField(signal?: AbortSignal): Promise<string | undefined> {
    const body = await this.request({ method: 'GET', path: '/rest/api/2/field', signal })
    if (!Array.isArray(body)) return undefined
    const fields = body
      .filter((entry): entry is Record<string, unknown> => typeof entry === 'object' && entry !== null)
      .map((entry) => ({
        id: typeof entry.id === 'string' ? entry.id : '',
        name: typeof entry.name === 'string' ? entry.name : '',
      }))
      .filter((entry) => entry.id !== '')
    const exact = fields.find((entry) => /^story\s*points?(\s+estimate)?$/i.test(entry.name.trim()))
    if (exact !== undefined) return exact.id
    const loose = fields.find((entry) => /story\s*point/i.test(entry.name) || /оценка\s*\(sp\)|story\s*points/i.test(entry.name))
    return loose?.id
  }

  /** Один запрос: заголовки, бюджет ожидания, разбор ответа и отказов. */
  private async request(options: RequestOptions): Promise<unknown> {
    if (this.target.token.trim() === '') {
      throw new JiraError('not-configured', 'не задан токен доступа к JIRA')
    }
    const url = new URL(`${this.target.baseUrl}${options.path}`)
    for (const [key, value] of Object.entries(options.query ?? {})) url.searchParams.set(key, value)

    const headers: Record<string, string> = {
      Accept: 'application/json',
      Authorization: authorizationOf(this.target),
    }
    if (options.body !== undefined) headers['Content-Type'] = 'application/json'

    let response
    try {
      response = await this.options.http(url.toString(), {
        method: options.method,
        headers,
        ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
        signal: deadline(this.options.timeoutMs, options.signal),
      })
    } catch (error) {
      throw asJiraError(error)
    }

    const text = await response.text().catch(() => '')
    if (!response.ok) throw failureOf(response.status, response.headers.get('x-authentication-denied-reason'), text)

    const contentType = response.headers.get('content-type') ?? ''
    if (!contentType.toLowerCase().includes('json')) {
      throw new JiraError(
        'not-json',
        `JIRA ответила не JSON (content-type: ${contentType || 'не указан'}). `
        + 'Обычно это страница входа SSO вместо REST API: проверьте адрес и что токен — персональный токен JIRA',
        response.status,
      )
    }
    try {
      return JSON.parse(text)
    } catch {
      throw new JiraError('not-json', 'ответ JIRA не разбирается как JSON', response.status)
    }
  }
}

/** Отказ JIRA в понятную человеку причину. */
export function failureOf(status: number, deniedReason: string | null, body: string): JiraError {
  const detail = jiraMessage(body)
  const tail = detail === undefined ? '' : `: ${detail}`
  if (status === 401) {
    return new JiraError('auth', `JIRA не приняла токен (401)${tail}`, status)
  }
  if (status === 403) {
    const captcha = deniedReason !== null && deniedReason !== ''
      ? ` (JIRA требует входа через браузер: ${deniedReason})`
      : ''
    return new JiraError('auth', `JIRA отказала в доступе (403)${captcha}${tail}`, status)
  }
  if (status === 400) return new JiraError('query', `JIRA отвергла запрос (400)${tail}`, status)
  if (status === 404) return new JiraError('http', `JIRA не нашла адрес запроса (404)${tail}`, status)
  if (status === 429) return new JiraError('http', `JIRA ограничила частоту запросов (429)${tail}`, status)
  if (status >= 500) return new JiraError('http', `JIRA ответила ошибкой ${status}${tail}`, status)
  return new JiraError('http', `JIRA ответила кодом ${status}${tail}`, status)
}

/** Текст ошибки из тела ответа JIRA, если он там есть. */
function jiraMessage(body: string): string | undefined {
  if (body.trim() === '') return undefined
  try {
    const parsed = JSON.parse(body) as { errorMessages?: unknown; errors?: unknown; message?: unknown }
    const messages = Array.isArray(parsed.errorMessages)
      ? parsed.errorMessages.filter((entry): entry is string => typeof entry === 'string')
      : []
    const fields = typeof parsed.errors === 'object' && parsed.errors !== null
      ? Object.entries(parsed.errors as Record<string, unknown>)
        .filter((entry): entry is [string, string] => typeof entry[1] === 'string')
        .map(([field, message]) => `${field}: ${message}`)
      : []
    const single = typeof parsed.message === 'string' ? [parsed.message] : []
    const all = [...messages, ...fields, ...single]
    return all.length === 0 ? undefined : all.join('; ')
  } catch {
    // Не JSON — берём короткую выжимку тела, но не вываливаем HTML-страницу целиком.
    const snippet = body.replace(/\s+/g, ' ').trim().slice(0, 200)
    return snippet === '' ? undefined : snippet
  }
}
