import assert from 'node:assert/strict'
import test from 'node:test'
import type { ToolRunContext } from '@deepseek-ai/dsh-tools'
import { SprintConnector } from '../src/connector.js'
import { DEFAULT_JIRA, type SprintSettings } from '../src/settings.js'
import { sprintTools } from '../src/tools.js'
import { fakeHttp, issueJson, searchReply } from './support/http.js'

const CONFIGURED: SprintSettings = {
  jira: {
    ...DEFAULT_JIRA,
    baseUrl: 'https://jira.example.com',
    token: 'pat',
    projectKey: 'SPRINT',
    storyPointsField: 'customfield_10004',
  },
}

/** Контекст исполнения: инструментам нужен только сигнал отмены. */
const EXEC = { signal: new AbortController().signal } as unknown as ToolRunContext

function tools(settings: SprintSettings, route: Parameters<typeof fakeHttp>[0]) {
  const http = fakeHttp(route)
  const connector = new SprintConnector({
    settings: () => settings, env: {}, http: http.port, timeoutMs: 1000, maxIssues: 50,
  })
  const list = sprintTools(connector, { timeoutMs: 5000 })
  const byName = new Map(list.map((tool) => [tool.name, tool]))
  return { list, byName, http }
}

test('раздел даёт ровно три инструмента с говорящими именами', () => {
  const { list } = tools(CONFIGURED, () => undefined)
  assert.deepEqual(list.map((tool) => tool.name), ['jira_current_stories', 'jira_search', 'jira_issue'])
})

test('описание инструмента историй ловит запрос «покажи актуальные истории команды»', () => {
  const { byName } = tools(CONFIGURED, () => undefined)
  const description = byName.get('jira_current_stories')?.description ?? ''
  assert.match(description, /актуальные истории/i)
  assert.match(description, /спринт/i)
})

test('jira_current_stories ходит в JIRA и отдаёт канонический JSON', async () => {
  const { byName, http } = tools(CONFIGURED, (url) => url.pathname === '/rest/api/2/search'
    ? searchReply([issueJson('SPRINT-1', {
      summary: 'Витрина кино',
      status: { name: 'В работе' },
      assignee: { displayName: 'Иванов И.' },
      customfield_10004: 5,
    })], 1)
    : undefined)

  const tool = byName.get('jira_current_stories')
  assert.ok(tool !== undefined)
  const value = await tool.execute({ limit: 10 }, EXEC) as { jql: string; total: number; issues: unknown[] }
  assert.equal(value.total, 1)
  assert.equal(value.jql, 'project = "SPRINT" AND sprint in openSprints() ORDER BY updated DESC')
  assert.equal(http.calls.length, 1)
})

test('фильтры инструмента доезжают до JQL', async () => {
  const { byName, http } = tools(CONFIGURED, (url) => url.pathname === '/rest/api/2/search' ? searchReply([]) : undefined)
  const tool = byName.get('jira_current_stories')
  assert.ok(tool !== undefined)
  await tool.execute({ assignee: 'ivanov', sprint: 'any' }, EXEC)
  const body = JSON.parse(http.calls[0]?.request.body ?? '{}') as { jql: string }
  assert.equal(body.jql, 'project = "SPRINT" AND assignee = "ivanov" ORDER BY updated DESC')
})

test('выдача рисуется таблицей — модель читает её, а не JSON-дамп', () => {
  const { byName } = tools(CONFIGURED, () => undefined)
  const tool = byName.get('jira_current_stories')
  assert.ok(tool !== undefined)
  const blocks = tool.output.render({}, {
    jql: 'project = "SPRINT"',
    total: 1,
    issues: [{
      key: 'SPRINT-1', summary: 'Витрина кино', url: 'https://jira.example.com/browse/SPRINT-1',
      status: 'В работе', assignee: 'Иванов И.', storyPoints: 5,
    }],
  })
  const text = blocks.map((block) => (block.type === 'text' ? block.text : '')).join('\n')
  assert.match(text, /Ключ \| Тип \| Статус \| Исполнитель \| SP \| Спринт \| Заголовок/)
  assert.match(text, /SPRINT-1 \| — \| В работе \| Иванов И\. \| 5 \| — \| Витрина кино/)
})

test('ненастроенный коннектор говорит модели, что именно настроить', async () => {
  const { byName } = tools({ jira: DEFAULT_JIRA }, () => undefined)
  const tool = byName.get('jira_search')
  assert.ok(tool !== undefined)
  await assert.rejects(
    tool.execute({ jql: 'project = "SPRINT"' }, EXEC),
    /Настройки → Плагины → Управление спринтами/,
  )
})

test('jira_issue отдаёт одну задачу с описанием', async () => {
  const { byName } = tools(CONFIGURED, (url) => url.pathname === '/rest/api/2/issue/SPRINT-128'
    ? { body: issueJson('SPRINT-128', { summary: 'Кино', description: 'БЫЛО→СТАЛО' }) }
    : undefined)
  const tool = byName.get('jira_issue')
  assert.ok(tool !== undefined)
  const value = await tool.execute({ key: 'SPRINT-128' }, EXEC) as { key: string; description?: string }
  assert.equal(value.key, 'SPRINT-128')
  assert.equal(value.description, 'БЫЛО→СТАЛО')
})
