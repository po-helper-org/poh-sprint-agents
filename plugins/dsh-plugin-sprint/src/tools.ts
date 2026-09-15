/**
 * Нативные инструменты модели. Это и есть ответ на исходную проблему: JIRA
 * приходит в чат не MCP-мостом, а инструментами самого раздела — схемы уходят в
 * системный промт автоматически (`ctx.tools.register`), и модель выбирает их по
 * описанию, без посредника, который в харнессе работал плохо.
 *
 * Инструментов три, и это осознанный потолок: «истории команды» (рабочий
 * сценарий), «поиск по JQL» (всё остальное) и «одна задача» (детали). Больше
 * инструментов — больше схем в каждом запросе и хуже выбор.
 */
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { ToolDefinition } from '@deepseek-ai/dsh-tools'
import type { SprintConnector } from './connector.js'
import { renderIssue, renderSearch } from './render.js'

/** Схема задачи в каноническом выводе инструментов. */
const ISSUE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    key: { type: 'string', required: true, description: 'Ключ задачи, например SPRINT-128' },
    summary: { type: 'string', required: true, description: 'Заголовок' },
    type: { type: 'string', description: 'Тип задачи, как он назван в этом контуре JIRA' },
    status: { type: 'string', description: 'Статус' },
    assignee: { type: 'string', description: 'Исполнитель; поля нет — не назначен' },
    storyPoints: { type: 'number', description: 'Оценка в story points, если поле оценки есть' },
    sprint: { type: 'string', description: 'Спринт' },
    priority: { type: 'string', description: 'Приоритет' },
    parent: { type: 'string', description: 'Ключ эпика или родительской задачи' },
    labels: { type: 'array', items: { type: 'string' }, description: 'Метки' },
    updated: { type: 'string', description: 'Дата последнего изменения (ISO 8601)' },
    url: { type: 'string', required: true, description: 'Ссылка на задачу' },
    description: { type: 'string', description: 'Описание; только в выдаче одной задачи' },
  },
} as const

/** Схема выдачи поиска. */
const SEARCH_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    jql: { type: 'string', required: true, description: 'JQL, которым получен результат' },
    total: { type: 'integer', required: true, description: 'Сколько задач нашла JIRA всего' },
    issues: { type: 'array', items: ISSUE_SCHEMA, required: true, description: 'Задачи выдачи' },
  },
} as const

/** Бюджет одного вызова инструмента: поиск плюс разовый поход за каталогом полей. */
export interface ToolOptions {
  timeoutMs: number
}

/**
 * Инструменты коннектора.
 * @param connector - одна дверь в JIRA, общая с кнопкой «Протестировать».
 * @param options - бюджет ожидания.
 * @returns готовые к регистрации определения.
 */
export function sprintTools(connector: SprintConnector, options: ToolOptions): ToolDefinition[] {
  return [
    defineTool({
      name: 'jira_current_stories',
      description:
        'Актуальные истории и задачи команды из корпоративной JIRA: активный спринт настроенного проекта. '
        + 'Вызывай на вопросы вида «покажи актуальные истории команды», «что в работе», «что в спринте», '
        + '«чем занят такой-то» — данные брать отсюда, а не из памяти. '
        + 'Фильтры необязательны; без них возвращается весь открытый спринт.',
      parameters: {
        limit: { type: 'integer', description: 'Сколько задач вернуть (по умолчанию 25)' },
        assignee: { type: 'string', description: 'Учётная запись исполнителя в JIRA' },
        status: { type: 'string', description: 'Фильтр по статусу, как он назван в JIRA' },
        issue_type: { type: 'string', description: 'Тип задачи: Story, История, Bug — как он назван в JIRA' },
        sprint: {
          type: 'string',
          enum: ['active', 'any'],
          description: 'active — только открытые спринты (по умолчанию); any — без фильтра по спринту',
        },
      },
      output: {
        schema: SEARCH_SCHEMA,
        render: (_args, value) => [{ type: 'text', text: renderSearch(value) }],
      },
      timeoutMs: options.timeoutMs,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return connector.stories({
          ...(args.limit === undefined ? {} : { limit: args.limit }),
          ...(args.assignee === undefined ? {} : { assignee: args.assignee }),
          ...(args.status === undefined ? {} : { status: args.status }),
          ...(args.issue_type === undefined ? {} : { issueType: args.issue_type }),
          ...(args.sprint === undefined ? {} : { sprint: args.sprint }),
        }, exec.signal)
      },
    }),

    defineTool({
      name: 'jira_search',
      description:
        'Поиск в корпоративной JIRA произвольным JQL. Для всего, что не покрывает jira_current_stories: '
        + 'другой проект, закрытый спринт, баги, фильтр по метке или дате.',
      parameters: {
        jql: { type: 'string', required: true, description: 'Запрос JQL целиком, вместе с ORDER BY' },
        limit: { type: 'integer', description: 'Сколько задач вернуть (по умолчанию 25)' },
      },
      output: {
        schema: SEARCH_SCHEMA,
        render: (_args, value) => [{ type: 'text', text: renderSearch(value) }],
      },
      timeoutMs: options.timeoutMs,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return connector.search(args.jql, args.limit, exec.signal)
      },
    }),

    defineTool({
      name: 'jira_issue',
      description:
        'Одна задача корпоративной JIRA по ключу (SPRINT-128), с описанием. '
        + 'Вызывай, когда нужны детали конкретной задачи, а не список.',
      parameters: {
        key: { type: 'string', required: true, description: 'Ключ задачи, например SPRINT-128' },
      },
      output: {
        schema: ISSUE_SCHEMA,
        render: (_args, value) => [{ type: 'text', text: renderIssue(value) }],
      },
      timeoutMs: options.timeoutMs,
      isConcurrencySafe: () => true,
      async execute(args, exec) {
        return connector.issue(args.key, exec.signal)
      },
    }),
  ]
}
