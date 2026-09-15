import assert from 'node:assert/strict'
import test from 'node:test'
import { dispatch, draftOf, type TestReply } from '../src/channel.js'
import { SprintConnector } from '../src/connector.js'
import { DEFAULT_JIRA, type SprintSettings } from '../src/settings.js'
import { fakeHttp, issueJson, searchReply } from './support/http.js'

const EMPTY: SprintSettings = { jira: DEFAULT_JIRA }

function connector(settings: SprintSettings, route: Parameters<typeof fakeHttp>[0]) {
  const http = fakeHttp(route)
  return new SprintConnector({ settings: () => settings, env: {}, http: http.port, timeoutMs: 1000, maxIssues: 50 })
}

test('черновик из полезной нагрузки: свои поля берём, чужие отбрасываем', () => {
  assert.deepEqual(draftOf({ draft: { baseUrl: 'https://jira.example.com', token: 't', lol: 1 } }), {
    baseUrl: 'https://jira.example.com', token: 't',
  })
  assert.equal(draftOf({}), undefined)
  assert.equal(draftOf(null), undefined)
})

test('jira.test проверяет ИМЕННО черновик карточки, а не записанное', async () => {
  const subject = connector(EMPTY, (url) => {
    if (url.pathname === '/rest/api/2/myself') return { body: { displayName: 'Иванов И.', name: 'ivanov' } }
    if (url.pathname === '/rest/api/2/search') return searchReply([issueJson('SPRINT-1', {})], 4)
    return undefined
  })
  const answer = await dispatch(subject, 'jira.test', {
    draft: { baseUrl: 'https://jira.example.com', token: 'pat', projectKey: 'SPRINT' },
  })
  assert.ok(answer.ok)
  const reply = answer.value as TestReply
  assert.match(reply.summary, /Подключение к https:\/\/jira\.example\.com установлено: Иванов И\./)
  assert.match(reply.summary, /запрос историй вернул 4/)
})

test('отказ уходит результатом с кодом, а не броском из канала', async () => {
  const subject = connector(EMPTY, () => ({ status: 401, body: { errorMessages: ['токен не принят'] } }))
  const answer = await dispatch(subject, 'jira.test', {
    draft: { baseUrl: 'https://jira.example.com', token: 'плохой' },
  })
  assert.equal(answer.ok, false)
  if (answer.ok) return
  assert.equal(answer.error.code, 'auth')
  assert.match(answer.error.message, /401/)
})

test('ненастроенный коннектор виден в статусе', async () => {
  const subject = connector(EMPTY, () => undefined)
  const answer = await dispatch(subject, 'jira.status', {})
  assert.deepEqual(answer, { ok: true, value: { configured: false } })
})

test('неизвестная подкоманда названа, а не проглочена', async () => {
  const subject = connector(EMPTY, () => undefined)
  const answer = await dispatch(subject, 'jira.magic', {})
  assert.equal(answer.ok, false)
  if (answer.ok) return
  assert.equal(answer.error.code, 'unknown-endpoint')
})
