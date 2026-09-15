/**
 * Коннектор раздела: одна дверь в JIRA для обеих поверхностей — кнопки
 * «Протестировать» в карточке настроек и инструментов модели в чате. Одна
 * дверь важна не для красоты: иначе проверка подключения и рабочий вызов
 * расходятся, и «зелёная» кнопка перестаёт что-либо обещать.
 *
 * Настройки читаются на каждый вызов, а не при старте: человек правит карточку
 * и сразу зовёт модель, без перезапуска харнесса.
 */
import { JiraError } from './errors.js'
import { JiraClient, type JiraTarget } from './jira/client.js'
import { buildStoriesJql, type StoriesQuery } from './jira/jql.js'
import type { JiraIdentity, JiraIssue, JiraSearchResult } from './jira/model.js'
import type { HttpPort } from './ports.js'
import {
  isConfigured, normalizeBaseUrl, resolveToken,
  type JiraSettings, type SprintSettings,
} from './settings.js'

/** Черновик из карточки: то, что человек ввёл, но ещё не сохранил. */
export type JiraDraft = Partial<Pick<JiraSettings, 'baseUrl' | 'token' | 'email' | 'projectKey' | 'storiesJql' | 'storyPointsField'>>

export interface ConnectorDeps {
  /** Текущий снимок документа настроек. */
  settings: () => SprintSettings
  /** Окружение процесса узла — запасной источник токена. */
  env: Record<string, string | undefined>
  http: HttpPort
  /** Бюджет ожидания одного запроса к JIRA. */
  timeoutMs: number
  /** Потолок числа задач в одной выдаче. */
  maxIssues: number
}

/** Что показывает «Протестировать» и что модель может сказать про подключение. */
export interface ConnectionReport {
  baseUrl: string
  identity: JiraIdentity
  /** Проверка запроса историй: JQL и сколько по нему нашлось. */
  stories?: { jql: string; total: number }
  /** Подключение есть, но что-то рядом не сложилось (например, не задан проект). */
  warning?: string
}

export class SprintConnector {
  /** Клиент и подпись цели, для которой он создан: меняются настройки — меняется клиент. */
  private cached: { signature: string; client: JiraClient } | undefined

  constructor(private readonly deps: ConnectorDeps) {}

  /** Настроен ли коннектор (без похода в сеть). */
  configured(): boolean {
    return isConfigured(this.deps.settings().jira, this.deps.env)
  }

  /** Настройки JIRA с наложенным черновиком карточки. */
  effective(draft?: JiraDraft): JiraSettings {
    const stored = this.deps.settings().jira
    if (draft === undefined) return stored
    const pick = (value: string | undefined, fallback: string): string =>
      value === undefined ? fallback : value
    return {
      ...stored,
      baseUrl: pick(draft.baseUrl, stored.baseUrl),
      token: pick(draft.token, stored.token),
      email: pick(draft.email, stored.email),
      projectKey: pick(draft.projectKey, stored.projectKey),
      storiesJql: pick(draft.storiesJql, stored.storiesJql),
      storyPointsField: pick(draft.storyPointsField, stored.storyPointsField),
    }
  }

  /**
   * Клиент для текущих настроек.
   * @throws JiraError — коннектор не настроен или настроен негодно.
   */
  client(draft?: JiraDraft): JiraClient {
    const settings = this.effective(draft)
    const base = normalizeBaseUrl(settings.baseUrl)
    if ('problem' in base) {
      throw new JiraError(
        settings.baseUrl.trim() === '' ? 'not-configured' : 'bad-config',
        `${base.problem}. Заполните «Настройки → Плагины → Управление спринтами → JIRA»`,
      )
    }
    const token = resolveToken(settings, this.deps.env)
    if (token === '') {
      throw new JiraError(
        'not-configured',
        'не задан токен доступа к JIRA. Укажите его в «Настройки → Плагины → Управление спринтами → JIRA» '
        + 'или задайте JIRA_TOKEN в окружении харнесса',
      )
    }
    const target: JiraTarget = {
      baseUrl: base.url,
      token,
      email: settings.email.trim(),
      storyPointsField: settings.storyPointsField.trim(),
    }
    const signature = JSON.stringify(target)
    if (this.cached?.signature !== signature) {
      this.cached = {
        signature,
        client: new JiraClient(target, { http: this.deps.http, timeoutMs: this.deps.timeoutMs }),
      }
    }
    return this.cached.client
  }

  /**
   * Проверка подключения: кто мы для этой JIRA и отвечает ли запрос историй.
   * Второй шаг не обязателен — подключение считается рабочим и без проекта.
   */
  async test(draft?: JiraDraft, signal?: AbortSignal): Promise<ConnectionReport> {
    const settings = this.effective(draft)
    const client = this.client(draft)
    const identity = await client.myself(signal)
    const base = normalizeBaseUrl(settings.baseUrl)
    const report: ConnectionReport = {
      baseUrl: 'url' in base ? base.url : settings.baseUrl,
      identity,
    }
    const jql = buildStoriesJql({ projectKey: settings.projectKey, storiesJql: settings.storiesJql })
    if ('problem' in jql) {
      report.warning = `${jql.problem} — инструмент историй команды пока не заработает`
      return report
    }
    try {
      const found = await client.search(jql.jql, { limit: 1, ...(signal === undefined ? {} : { signal }) })
      report.stories = { jql: found.jql, total: found.total }
    } catch (error) {
      report.warning = error instanceof JiraError
        ? `подключение есть, но запрос историй не прошёл — ${error.message}`
        : `подключение есть, но запрос историй не прошёл: ${String(error)}`
    }
    return report
  }

  /** Актуальные истории команды: активный спринт настроенного проекта. */
  async stories(
    params: { limit?: number; assignee?: string; status?: string; issueType?: string; sprint?: 'active' | 'any' },
    signal?: AbortSignal,
  ): Promise<JiraSearchResult> {
    // Порядок проверок — не вкусовщина: у ненастроенного коннектора причина одна
    // («не задан адрес/токен»), и называть вместо неё отсутствие ключа проекта
    // значит послать человека править не то поле.
    this.client()
    const settings = this.effective()
    const query: StoriesQuery = {
      projectKey: settings.projectKey,
      storiesJql: settings.storiesJql,
      ...(params.assignee === undefined ? {} : { assignee: params.assignee }),
      ...(params.status === undefined ? {} : { status: params.status }),
      ...(params.issueType === undefined ? {} : { issueType: params.issueType }),
      ...(params.sprint === undefined ? {} : { sprint: params.sprint }),
    }
    const jql = buildStoriesJql(query)
    if ('problem' in jql) throw new JiraError('bad-config', jql.problem)
    return this.search(jql.jql, params.limit, signal)
  }

  /** Произвольный JQL. */
  async search(jql: string, limit?: number, signal?: AbortSignal): Promise<JiraSearchResult> {
    const trimmed = jql.trim()
    if (trimmed === '') throw new JiraError('query', 'пустой JQL')
    return this.client().search(trimmed, {
      limit: this.clamp(limit),
      ...(signal === undefined ? {} : { signal }),
    })
  }

  /** Одна задача с описанием. */
  async issue(key: string, signal?: AbortSignal): Promise<JiraIssue> {
    return this.client().issue(key, signal)
  }

  /** Сколько задач просить у JIRA: не меньше одной, не больше потолка раздела. */
  private clamp(limit: number | undefined): number {
    const max = this.deps.maxIssues
    if (limit === undefined || !Number.isFinite(limit)) return Math.min(25, max)
    return Math.min(Math.max(Math.trunc(limit), 1), max)
  }
}
