/** Форма задачи JIRA, которую видят модель и карточка. Ровно то, что нужно для спринта. */
export interface JiraIssue {
  key: string
  summary: string
  /** Тип задачи, как он назван в этом контуре JIRA. */
  type?: string
  status?: string
  /** Отображаемое имя исполнителя. Отсутствие поля означает «не назначен». */
  assignee?: string
  /** Оценка в story points, если поле оценки нашлось. */
  storyPoints?: number
  /** Имя спринта, в котором стоит задача. */
  sprint?: string
  priority?: string
  /** Ключ эпика или родительской задачи. */
  parent?: string
  labels?: string[]
  /** Дата последнего изменения в виде, отданном JIRA (ISO 8601). */
  updated?: string
  /** Прямая ссылка на задачу. */
  url: string
  /** Описание — только в выдаче одной задачи, в списках не запрашивается. */
  description?: string
}

/** Результат поиска по JQL. */
export interface JiraSearchResult {
  /** Запрос, которым получен результат: модель должна видеть, что именно спросили. */
  jql: string
  /** Сколько задач нашла JIRA всего (не сколько вернулось). */
  total: number
  issues: JiraIssue[]
}

/** Кто мы для этой JIRA — ответ `/myself`. */
export interface JiraIdentity {
  /** Отображаемое имя учётной записи. */
  displayName: string
  /** Логин (Server/DC) или accountId (Cloud), что отдала JIRA. */
  name: string
  email?: string
}
