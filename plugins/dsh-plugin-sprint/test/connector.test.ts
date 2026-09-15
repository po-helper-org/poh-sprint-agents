import assert from 'node:assert/strict'
import test from 'node:test'
import { SprintConnector } from '../src/connector.js'
import { JiraError } from '../src/errors.js'
import { DEFAULT_JIRA, type SprintSettings } from '../src/settings.js'
import { fakeHttp, issueJson, searchReply } from './support/http.js'

const CONFIGURED: SprintSettings = {
  jira: {
    ...DEFAULT_JIRA,
    baseUrl: 'https://jira.example.com/',
    token: 'pat-token',
    projectKey: 'SPRINT',
    storyPointsField: 'customfield_10004',
  },
}

function connector(settings: SprintSettings, route: Parameters<typeof fakeHttp>[0], env: Record<string, string | undefined> = {}) {
  const http = fakeHttp(route)
  return {
    connector: new SprintConnector({
      settings: () => settings, env, http: http.port, timeoutMs: 1000, maxIssues: 50,
    }),
    http,
  }
}

test('ненастроенный коннектор отказывает с адресом настроек, а не «не смог»', async () => {
  const fixture = connector({ jira: DEFAULT_JIRA }, () => undefined)
  assert.equal(fixture.connector.configured(), false)
  await assert.rejects(fixture.connector.stories({}), (error: unknown) => {
    assert.ok(error instanceof JiraError)
    assert.equal(error.kind, 'not-configured')
    assert.match(error.message, /Настройки → Плагины → Управление спринтами/)
    return true
  })
  assert.equal(fixture.http.calls.length, 0)
})

test('токен из окружения делает коннектор настроенным без поля в карточке', () => {
  const settings: SprintSettings = { jira: { ...DEFAULT_JIRA, baseUrl: 'https://jira.example.com' } }
  const fixture = connector(settings, () => undefined, { JIRA_TOKEN: 'env-token' })
  assert.equal(fixture.connector.configured(), true)
})

test('истории команды идут запросом из настроек', async () => {
  const fixture = connector(CONFIGURED, (url) => url.pathname === '/rest/api/2/search'
    ? searchReply([issueJson('SPRINT-1', { summary: 'Кино', customfield_10004: 5 })], 1)
    : undefined)
  const result = await fixture.connector.stories({ limit: 5 })
  assert.equal(result.jql, 'project = "SPRINT" AND sprint in openSprints() ORDER BY updated DESC')
  assert.equal(result.issues[0]?.storyPoints, 5)
})

test('черновик карточки перекрывает документ настроек — проверять можно до сохранения', () => {
  const fixture = connector({ jira: DEFAULT_JIRA }, () => undefined)
  const effective = fixture.connector.effective({ baseUrl: 'https://draft.example.com', token: 'draft' })
  assert.equal(effective.baseUrl, 'https://draft.example.com')
  assert.equal(effective.token, 'draft')
})

test('потолок выдачи не обходится параметром инструмента', async () => {
  const fixture = connector(CONFIGURED, (url) => url.pathname === '/rest/api/2/search' ? searchReply([]) : undefined)
  await fixture.connector.search('project = "SPRINT"', 5000)
  const body = JSON.parse(fixture.http.calls[0]?.request.body ?? '{}') as { maxResults: number }
  assert.equal(body.maxResults, 50)

  await fixture.connector.search('project = "SPRINT"', 0)
  const second = JSON.parse(fixture.http.calls[1]?.request.body ?? '{}') as { maxResults: number }
  assert.equal(second.maxResults, 1)
})

test('проверка подключения: учётная запись плюс контрольный запрос историй', async () => {
  const fixture = connector(CONFIGURED, (url) => {
    if (url.pathname === '/rest/api/2/myself') return { body: { displayName: 'Иванов И.', name: 'ivanov' } }
    if (url.pathname === '/rest/api/2/search') return searchReply([issueJson('SPRINT-1', {})], 12)
    return undefined
  })
  const report = await fixture.connector.test()
  assert.equal(report.identity.displayName, 'Иванов И.')
  assert.equal(report.baseUrl, 'https://jira.example.com')
  assert.equal(report.stories?.total, 12)
  assert.equal(report.warning, undefined)
})

test('нет проекта — подключение засчитано, но предупреждение названо', async () => {
  const settings: SprintSettings = { jira: { ...CONFIGURED.jira, projectKey: '' } }
  const fixture = connector(settings, (url) => url.pathname === '/rest/api/2/myself'
    ? { body: { displayName: 'Иванов И.', name: 'ivanov' } }
    : undefined)
  const report = await fixture.connector.test()
  assert.equal(report.stories, undefined)
  assert.match(report.warning ?? '', /ключ проекта/)
})

test('отказ контрольного запроса не выдаётся за отказ подключения', async () => {
  const fixture = connector(CONFIGURED, (url) => {
    if (url.pathname === '/rest/api/2/myself') return { body: { displayName: 'Иванов И.', name: 'ivanov' } }
    if (url.pathname === '/rest/api/2/search') {
      return { status: 400, body: { errorMessages: ["Field 'sprint' does not exist"] } }
    }
    return undefined
  })
  const report = await fixture.connector.test()
  assert.equal(report.identity.name, 'ivanov')
  assert.match(report.warning ?? '', /запрос историй не прошёл/)
})
