/**
 * Приведение ответа JIRA к нашей форме. Отдельно от клиента, потому что это
 * чистая функция над JSON: её проверяют тесты на снимках настоящих ответов, без
 * сети.
 *
 * Разбор терпим к форме: Server/DC и Cloud отдают спринт и оценку по-разному, а
 * корпоративные контуры добавляют свои поля. Чего нет — того нет в результате;
 * выдумывать значение нельзя (принцип нулевого допуска к галлюцинациям).
 */
import type { JiraIssue } from './model.js'

/** Поля, которых достаточно для списка. Описание в списках не запрашивается: оно длинное. */
export const LIST_FIELDS = [
  'summary', 'status', 'assignee', 'issuetype', 'priority', 'labels', 'updated', 'parent',
] as const

type Fields = Record<string, unknown>

function record(value: unknown): Fields | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Fields) : undefined
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() !== '' ? value : undefined
}

function named(value: unknown): string | undefined {
  const node = record(value)
  if (node === undefined) return undefined
  return str(node.displayName) ?? str(node.name) ?? str(node.value)
}

/**
 * Имя спринта задачи. Cloud отдаёт объекты, Server/DC — строки вида
 * `...Sprint@1a2b[id=42,...,name=2026Q3-S7,state=ACTIVE,...]`. Активный спринт
 * выигрывает у закрытого: задача часто носит историю всех своих спринтов.
 */
export function sprintNameOf(fields: Fields): string | undefined {
  let fallback: string | undefined
  for (const [key, value] of Object.entries(fields)) {
    if (key !== 'sprint' && !key.startsWith('customfield_')) continue
    for (const entry of Array.isArray(value) ? value : [value]) {
      const node = record(entry)
      if (node !== undefined) {
        const name = str(node.name)
        if (name === undefined) continue
        if (str(node.state)?.toUpperCase() === 'ACTIVE') return name
        fallback ??= name
        continue
      }
      const text = str(entry)
      if (text === undefined || !text.includes('Sprint@')) continue
      const name = /[,[]name=([^,\]]+)/.exec(text)?.[1]
      if (name === undefined) continue
      if (/[,[]state=ACTIVE/i.test(text)) return name
      fallback ??= name
    }
  }
  return fallback
}

/** Оценка в story points из названного поля. Не число — значит оценки нет. */
export function storyPointsOf(fields: Fields, field: string | undefined): number | undefined {
  if (field === undefined || field === '') return undefined
  const value = fields[field]
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

/** Настройки разбора: адрес для ссылки и поле оценки, найденное клиентом. */
export interface NormalizeOptions {
  baseUrl: string
  storyPointsField?: string
  /** Забрать описание (выдача одной задачи). */
  withDescription?: boolean
}

/**
 * Одна задача JIRA в нашу форму.
 * @returns задачу либо `undefined`, если у записи нет ключа (не задача).
 */
export function normalizeIssue(raw: unknown, options: NormalizeOptions): JiraIssue | undefined {
  const node = record(raw)
  if (node === undefined) return undefined
  const key = str(node.key)
  if (key === undefined) return undefined
  const fields = record(node.fields) ?? {}

  const issue: JiraIssue = {
    key,
    summary: str(fields.summary) ?? '',
    url: `${options.baseUrl}/browse/${key}`,
  }
  const type = named(fields.issuetype)
  if (type !== undefined) issue.type = type
  const status = named(fields.status)
  if (status !== undefined) issue.status = status
  const assignee = named(fields.assignee)
  if (assignee !== undefined) issue.assignee = assignee
  const priority = named(fields.priority)
  if (priority !== undefined) issue.priority = priority
  const points = storyPointsOf(fields, options.storyPointsField)
  if (points !== undefined) issue.storyPoints = points
  const sprint = sprintNameOf(fields)
  if (sprint !== undefined) issue.sprint = sprint
  const parent = str(record(fields.parent)?.key)
  if (parent !== undefined) issue.parent = parent
  const labels = Array.isArray(fields.labels)
    ? fields.labels.filter((label): label is string => typeof label === 'string')
    : []
  if (labels.length > 0) issue.labels = labels
  const updated = str(fields.updated)
  if (updated !== undefined) issue.updated = updated
  if (options.withDescription === true) {
    const description = descriptionOf(fields.description)
    if (description !== undefined) issue.description = description
  }
  return issue
}

/**
 * Описание задачи текстом. Server/DC отдаёт разметку строкой, Cloud — документ
 * ADF: из него собирается плоский текст, потому что модели нужен смысл, а не
 * дерево узлов.
 */
export function descriptionOf(value: unknown): string | undefined {
  const text = str(value)
  if (text !== undefined) return text
  const node = record(value)
  if (node === undefined) return undefined
  const parts: string[] = []
  const walk = (entry: unknown): void => {
    const current = record(entry)
    if (current === undefined) return
    const own = str(current.text)
    if (own !== undefined) parts.push(own)
    const content = current.content
    if (Array.isArray(content)) {
      for (const child of content) walk(child)
      if (str(current.type) === 'paragraph') parts.push('\n')
    }
  }
  walk(node)
  const joined = parts.join(' ').replace(/ *\n */g, '\n').trim()
  return joined === '' ? undefined : joined
}
