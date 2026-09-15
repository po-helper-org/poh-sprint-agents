/**
 * Секция системного промта про контур JIRA. Схемы инструментов харнесс кладёт в
 * промт сам; секция отвечает на другой вопрос — КОГДА ими пользоваться и что
 * это за контур. Без неё модель видит три инструмента без привязки к тому, что
 * «истории команды» живут именно здесь.
 *
 * Сюда же попадает промт подключения из карточки настроек: владелец контура
 * описывает свою JIRA своими словами (какой проект команды, как называются
 * статусы, что считать историей), и это едет модели без правки кода.
 *
 * Коннектор не настроен — секция пуста, а пустая секция в промт не попадает.
 */
import type { SprintSettings } from './settings.js'
import { isConfigured, normalizeBaseUrl } from './settings.js'

/** Порядок секции: после персоны и PLAN_POLICY, рядом с блоками подсказок по инструментам. */
export const DEFAULT_PROMPT_ORDER = 1200

/** Имя секции в реестре системного промта. */
export const PROMPT_SECTION = 'connector:jira'

/**
 * Текст секции.
 * @param settings - текущий снимок настроек раздела.
 * @param env - окружение узла (запасной источник токена).
 * @returns текст секции либо пустую строку, если коннектор не настроен.
 */
export function jiraPromptText(settings: SprintSettings, env: Record<string, string | undefined>): string {
  const { jira } = settings
  if (!isConfigured(jira, env)) return ''
  const base = normalizeBaseUrl(jira.baseUrl)
  const host = 'url' in base ? base.url : jira.baseUrl.trim()

  const lines = [
    '## Корпоративная JIRA (раздел «Управление спринтами»)',
    '',
    `Контур: ${host}.`,
  ]
  const project = jira.projectKey.trim()
  if (project !== '') lines.push(`Проект команды: ${project}.`)
  lines.push(
    '',
    '- Задачи, истории, спринт и загрузку команды бери инструментами `jira_current_stories`, '
    + '`jira_search`, `jira_issue`. Это встроенный коннектор раздела: он ходит в JIRA напрямую.',
    '- Вопрос про актуальные истории, работу команды или содержимое спринта — это вызов '
    + '`jira_current_stories`, а не ответ по памяти.',
    '- Не выдумывай ключи, статусы, оценки и исполнителей. Чего нет в ответе инструмента — того не утверждай; '
    + 'вместо догадки скажи, чего не хватает в настройках коннектора.',
    `- Ссылка на задачу — \`${host}/browse/КЛЮЧ\`.`,
  )

  const prompt = jira.prompt.trim()
  if (prompt !== '') {
    lines.push('', 'Промт подключения от владельца контура:', '', prompt)
  }
  return lines.join('\n')
}
