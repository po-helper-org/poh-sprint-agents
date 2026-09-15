/**
 * Сборка JQL. Отдельный модуль, потому что это единственное место, где строка
 * запроса склеивается из пользовательских значений: экранирование живёт здесь
 * и проверяется тестами, а не расползается по вызовам.
 */

/** Значение в JQL-литерал: экранируются обратная косая и кавычка. */
export function quoteJql(value: string): string {
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`
}

/** Запрос историй команды. */
export interface StoriesQuery {
  /** Ключ проекта из настроек. */
  projectKey: string
  /** Свой JQL из настроек. Непусто — берётся он, фильтры дописываются к нему. */
  storiesJql: string
  /** Фильтр по исполнителю (имя учётной записи JIRA). */
  assignee?: string
  /** Фильтр по статусу. */
  status?: string
  /** Тип задачи: `Story`, `История` — как он называется в этом контуре. */
  issueType?: string
  /** `active` — только открытые спринты (по умолчанию), `any` — без спринт-фильтра. */
  sprint?: 'active' | 'any'
}

/**
 * Разрезает JQL на условия и хвост `ORDER BY`: фильтры дописываются к условиям,
 * а не после сортировки, иначе запрос перестаёт разбираться.
 */
export function splitOrderBy(jql: string): { where: string; order: string } {
  const match = /\border\s+by\b/i.exec(jql)
  if (match === null) return { where: jql.trim(), order: '' }
  return { where: jql.slice(0, match.index).trim(), order: jql.slice(match.index).trim() }
}

/**
 * Строит JQL историй команды.
 * @returns готовый запрос либо причину, по которой его не из чего построить.
 */
export function buildStoriesJql(query: StoriesQuery): { jql: string } | { problem: string } {
  const filters: string[] = []
  if (query.assignee !== undefined && query.assignee.trim() !== '') {
    filters.push(`assignee = ${quoteJql(query.assignee.trim())}`)
  }
  if (query.status !== undefined && query.status.trim() !== '') {
    filters.push(`status = ${quoteJql(query.status.trim())}`)
  }
  if (query.issueType !== undefined && query.issueType.trim() !== '') {
    filters.push(`issuetype = ${quoteJql(query.issueType.trim())}`)
  }

  const own = query.storiesJql.trim()
  if (own !== '') {
    const { where, order } = splitOrderBy(own)
    const clauses = [where, ...filters].filter((clause) => clause !== '')
    const joined = clauses.map((clause, index) => (index === 0 ? clause : `(${clause})`)).join(' AND ')
    return { jql: order === '' ? joined : `${joined} ${order}` }
  }

  const key = query.projectKey.trim()
  if (key === '') {
    return {
      problem: 'не задан ни ключ проекта, ни свой JQL — заполните «Проект» или «JQL историй» '
        + 'в «Настройки → Плагины → Управление спринтами»',
    }
  }
  const clauses = [`project = ${quoteJql(key)}`]
  if ((query.sprint ?? 'active') === 'active') clauses.push('sprint in openSprints()')
  clauses.push(...filters)
  return { jql: `${clauses.join(' AND ')} ORDER BY updated DESC` }
}
