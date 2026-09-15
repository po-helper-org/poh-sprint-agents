import assert from 'node:assert/strict'
import test from 'node:test'
import { JiraClient, authorizationOf, failureOf } from '../src/jira/client.js'
import { JiraError } from '../src/errors.js'
import { fakeHttp, issueJson, searchReply } from './support/http.js'

const TARGET = {
  baseUrl: 'https://jira.example.com',
  token: 'pat-token',
  email: '',
  storyPointsField: 'customfield_10004',
}

function client(route: Parameters<typeof fakeHttp>[0], target = TARGET) {
  const http = fakeHttp(route)
  return { client: new JiraClient(target, { http: http.port, timeoutMs: 1000 }), http }
}

test('Server/DC — Bearer, Cloud с учётной записью — Basic', () => {
  assert.equal(authorizationOf(TARGET), 'Bearer pat-token')
  assert.equal(
    authorizationOf({ ...TARGET, email: 'po@example.com' }),
    `Basic ${Buffer.from('po@example.com:pat-token', 'utf8').toString('base64')}`,
  )
})

test('/myself отдаёт учётную запись и подписывается токеном', async () => {
  const fixture = client((url) => url.pathname === '/rest/api/2/myself'
    ? { body: { displayName: 'Иванов И.', name: 'ivanov', emailAddress: 'ivanov@example.com' } }
    : undefined)
  const identity = await fixture.client.myself()
  assert.deepEqual(identity, { displayName: 'Иванов И.', name: 'ivanov', email: 'ivanov@example.com' })
  assert.equal(fixture.http.calls[0]?.request.headers.Authorization, 'Bearer pat-token')
})

test('поиск уходит POST-ом на /rest/api/2/search с JQL, полями и потолком', async () => {
  const fixture = client((url) => url.pathname === '/rest/api/2/search'
    ? searchReply([issueJson('SPRINT-1', { summary: 'Истории', status: { name: 'Открыта' } })], 7)
    : undefined)
  const result = await fixture.client.search('project = "SPRINT"', { limit: 10 })

  assert.equal(result.total, 7)
  assert.equal(result.issues.length, 1)
  assert.equal(result.issues[0]?.url, 'https://jira.example.com/browse/SPRINT-1')
  const call = fixture.http.calls[0]
  assert.equal(call?.request.method, 'POST')
  const body = JSON.parse(call?.request.body ?? '{}') as { jql: string; maxResults: number; fields: string[] }
  assert.equal(body.jql, 'project = "SPRINT"')
  assert.equal(body.maxResults, 10)
  assert.ok(body.fields.includes('customfield_10004'))
  assert.ok(body.fields.includes('sprint'))
})

test('облачная JIRA: 404 на /rest/api/2/search — отступление на /rest/api/3/search/jql', async () => {
  const fixture = client((url) => {
    if (url.pathname === '/rest/api/2/search') return { status: 404, body: { errorMessages: ['gone'] } }
    if (url.pathname === '/rest/api/3/search/jql') return { body: { issues: [issueJson('CLOUD-2', { summary: 'Облако' })] } }
    return undefined
  })
  const result = await fixture.client.search('project = "CLOUD"', { limit: 5 })
  assert.equal(result.issues[0]?.key, 'CLOUD-2')
  // total облако не отдаёт — честнее показать, сколько вернулось, чем выдумать число
  assert.equal(result.total, 1)
  assert.equal(fixture.http.calls.length, 2)
})

test('страница входа SSO вместо API названа страницей входа, а не «пустым ответом»', async () => {
  const fixture = client(() => ({ contentType: 'text/html;charset=utf-8', body: '<html>login</html>' }))
  await assert.rejects(fixture.client.myself(), (error: unknown) => {
    assert.ok(error instanceof JiraError)
    assert.equal(error.kind, 'not-json')
    assert.match(error.message, /страница входа SSO/)
    return true
  })
})

test('401 и 403 различимы и несут текст JIRA', () => {
  const unauthorized = failureOf(401, null, JSON.stringify({ errorMessages: ['токен истёк'] }))
  assert.equal(unauthorized.kind, 'auth')
  assert.match(unauthorized.message, /401.*токен истёк/)

  const captcha = failureOf(403, 'CAPTCHA_CHALLENGE', '')
  assert.equal(captcha.kind, 'auth')
  assert.match(captcha.message, /CAPTCHA_CHALLENGE/)

  const jql = failureOf(400, null, JSON.stringify({ errorMessages: ['Field \'sprint\' does not exist'] }))
  assert.equal(jql.kind, 'query')
  assert.match(jql.message, /sprint/)
})

test('поле оценки находится по каталогу полей, когда не задано в настройках', async () => {
  const fixture = client((url) => {
    if (url.pathname === '/rest/api/2/field') {
      return {
        body: [
          { id: 'customfield_10001', name: 'Эпик' },
          { id: 'customfield_10016', name: 'Story Points' },
        ],
      }
    }
    if (url.pathname === '/rest/api/2/search') return searchReply([issueJson('SPRINT-3', { customfield_10016: 3 })])
    return undefined
  }, { ...TARGET, storyPointsField: '' })

  const result = await fixture.client.search('project = "SPRINT"', { limit: 5 })
  assert.equal(result.issues[0]?.storyPoints, 3)

  // каталог полей спрашивается один раз на клиента, а не на каждый поиск
  await fixture.client.search('project = "SPRINT"', { limit: 5 })
  assert.equal(fixture.http.calls.filter((call) => call.url.includes('/rest/api/2/field')).length, 1)
})

test('отказ каталога полей не роняет поиск — задачи приходят без SP', async () => {
  const fixture = client((url) => {
    if (url.pathname === '/rest/api/2/field') return { status: 500, body: { errorMessages: ['упал'] } }
    if (url.pathname === '/rest/api/2/search') return searchReply([issueJson('SPRINT-4', { summary: 'Без оценки' })])
    return undefined
  }, { ...TARGET, storyPointsField: '' })
  const result = await fixture.client.search('project = "SPRINT"', { limit: 5 })
  assert.equal(result.issues[0]?.key, 'SPRINT-4')
  assert.equal(result.issues[0]?.storyPoints, undefined)
})

test('ключ задачи проверяется до похода в сеть', async () => {
  const fixture = client(() => undefined)
  await assert.rejects(fixture.client.issue('не ключ'), (error: unknown) => {
    assert.ok(error instanceof JiraError)
    assert.equal(error.kind, 'query')
    return true
  })
  assert.equal(fixture.http.calls.length, 0)
})

test('одна задача приходит с описанием', async () => {
  const fixture = client((url) => url.pathname === '/rest/api/2/issue/SPRINT-128'
    ? { body: issueJson('SPRINT-128', { summary: 'Кино', description: 'БЫЛО→СТАЛО' }) }
    : undefined)
  const issue = await fixture.client.issue('sprint-128')
  assert.equal(issue.key, 'SPRINT-128')
  assert.equal(issue.description, 'БЫЛО→СТАЛО')
})
