/**
 * Текст выдачи для модели. Таблица, а не JSON-дамп: модель читает её глазами
 * человека, а лишние поля стоят контекста. Канонический JSON инструмента
 * остаётся рядом — он объявлен в схеме и никуда не девается.
 *
 * Проза — по writing_style репозитория: деловая, без декоративных эмодзи.
 */
import type { JiraIssue, JiraSearchResult } from './jira/model.js'

function cell(value: string | number | undefined): string {
  if (value === undefined) return '—'
  const text = String(value).replace(/\|/g, '\\|').replace(/\s+/g, ' ').trim()
  return text === '' ? '—' : text
}

/** Список задач таблицей: ключ, тип, статус, исполнитель, SP, спринт, заголовок. */
export function renderSearch(result: JiraSearchResult): string {
  const head = `JQL: ${result.jql}\nНайдено в JIRA: ${result.total}; показано: ${result.issues.length}`
  if (result.issues.length === 0) {
    return `${head}\n\nПо запросу ничего не найдено.`
  }
  const rows = result.issues.map((issue) => [
    cell(issue.key), cell(issue.type), cell(issue.status), cell(issue.assignee),
    cell(issue.storyPoints), cell(issue.sprint), cell(issue.summary),
  ].join(' | '))
  return [
    head,
    '',
    'Ключ | Тип | Статус | Исполнитель | SP | Спринт | Заголовок',
    '--- | --- | --- | --- | --- | --- | ---',
    ...rows,
  ].join('\n')
}

/** Одна задача: карточка полей плюс описание, если оно есть. */
export function renderIssue(issue: JiraIssue): string {
  const lines = [
    `${issue.key} — ${issue.summary}`,
    `Ссылка: ${issue.url}`,
    `Тип: ${cell(issue.type)}; статус: ${cell(issue.status)}; исполнитель: ${cell(issue.assignee)}`,
    `SP: ${cell(issue.storyPoints)}; спринт: ${cell(issue.sprint)}; приоритет: ${cell(issue.priority)}`,
  ]
  if (issue.parent !== undefined) lines.push(`Родитель/эпик: ${issue.parent}`)
  if (issue.labels !== undefined && issue.labels.length > 0) lines.push(`Метки: ${issue.labels.join(', ')}`)
  if (issue.updated !== undefined) lines.push(`Изменена: ${issue.updated}`)
  if (issue.description !== undefined) lines.push('', 'Описание:', issue.description)
  return lines.join('\n')
}

/** Итог проверки подключения одной строкой — им же карточка подписывает статус. */
export function renderConnection(report: {
  baseUrl: string
  identity: { displayName: string; name: string }
  stories?: { jql: string; total: number }
  warning?: string
}): string {
  const who = report.identity.displayName === '' ? report.identity.name : report.identity.displayName
  const head = `Подключение к ${report.baseUrl} установлено: ${who}`
  const stories = report.stories === undefined
    ? undefined
    : `запрос историй вернул ${report.stories.total}`
  const parts = [head, stories, report.warning].filter((part): part is string => part !== undefined)
  return parts.join('; ')
}
