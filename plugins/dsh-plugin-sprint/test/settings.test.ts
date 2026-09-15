import assert from 'node:assert/strict'
import test from 'node:test'
import {
  DEFAULT_JIRA, isConfigured, normalizeBaseUrl, problemOf, resolveSprintSettings, resolveToken,
} from '../src/settings.js'

test('снимок документа приводится к форме, чего нет — умолчание', () => {
  assert.deepEqual(resolveSprintSettings(undefined), { jira: DEFAULT_JIRA })
  assert.deepEqual(resolveSprintSettings({ jira: { baseUrl: 'https://jira.example.com', token: 42 } }), {
    jira: { ...DEFAULT_JIRA, baseUrl: 'https://jira.example.com' },
  })
})

test('адрес нормализуется, хвостовая косая снимается', () => {
  assert.deepEqual(normalizeBaseUrl(' https://jira.example.com/ '), { url: 'https://jira.example.com' })
  assert.deepEqual(normalizeBaseUrl('https://intranet.example.com/jira/'), { url: 'https://intranet.example.com/jira' })
})

test('негодный адрес называет причину', () => {
  assert.ok('problem' in normalizeBaseUrl(''))
  assert.ok('problem' in normalizeBaseUrl('jira.example.com'))
  const scheme = normalizeBaseUrl('ftp://jira.example.com')
  assert.ok('problem' in scheme)
  assert.match(scheme.problem, /https:\/\//)
})

test('пустой коннектор — это «не настроен», а не ошибка сохранения', () => {
  assert.equal(problemOf({ jira: DEFAULT_JIRA }), null)
})

test('заполненный коннектор проверяется: адрес и ключ проекта', () => {
  const base = { ...DEFAULT_JIRA, token: 'secret' }
  assert.match(problemOf({ jira: { ...base, baseUrl: 'jira' } }) ?? '', /не разбирается/)
  assert.equal(problemOf({ jira: { ...base, baseUrl: 'https://jira.example.com', projectKey: 'SPRINT' } }), null)
  assert.match(
    problemOf({ jira: { ...base, baseUrl: 'https://jira.example.com', projectKey: 'SPRINT-1' } }) ?? '',
    /ключ проекта/,
  )
})

test('токен берётся из окружения, когда поле настроек пусто', () => {
  assert.equal(resolveToken(DEFAULT_JIRA, { JIRA_TOKEN: ' env-token ' }), 'env-token')
  assert.equal(resolveToken({ ...DEFAULT_JIRA, token: 'own' }, { JIRA_TOKEN: 'env-token' }), 'own')
  assert.equal(resolveToken(DEFAULT_JIRA, {}), '')
})

test('настроенным считается коннектор с адресом и токеном', () => {
  assert.equal(isConfigured(DEFAULT_JIRA, {}), false)
  assert.equal(isConfigured({ ...DEFAULT_JIRA, baseUrl: 'https://jira.example.com' }, {}), false)
  assert.equal(isConfigured({ ...DEFAULT_JIRA, baseUrl: 'https://jira.example.com' }, { JIRA_TOKEN: 't' }), true)
})
