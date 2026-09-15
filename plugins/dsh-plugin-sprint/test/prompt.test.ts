import assert from 'node:assert/strict'
import test from 'node:test'
import { jiraPromptText } from '../src/prompt.js'
import { DEFAULT_JIRA, type SprintSettings } from '../src/settings.js'

const CONFIGURED: SprintSettings = {
  jira: {
    ...DEFAULT_JIRA,
    baseUrl: 'https://jira.example.com/',
    token: 'pat',
    projectKey: 'SPRINT',
    prompt: 'Историей считаем задачу типа «История»; статус «Готово» — это принято PO.',
  },
}

test('без настроенного коннектора секция пуста — пустая секция в промт не попадает', () => {
  assert.equal(jiraPromptText({ jira: DEFAULT_JIRA }, {}), '')
  assert.equal(jiraPromptText({ jira: { ...DEFAULT_JIRA, baseUrl: 'https://jira.example.com' } }, {}), '')
})

test('секция называет контур, проект и инструменты', () => {
  const text = jiraPromptText(CONFIGURED, {})
  assert.match(text, /Контур: https:\/\/jira\.example\.com\./)
  assert.match(text, /Проект команды: SPRINT\./)
  assert.match(text, /jira_current_stories/)
  assert.match(text, /jira_search/)
  assert.match(text, /jira_issue/)
  assert.match(text, /https:\/\/jira\.example\.com\/browse\/КЛЮЧ/)
})

test('промт подключения уезжает в секцию как есть', () => {
  const text = jiraPromptText(CONFIGURED, {})
  assert.match(text, /Промт подключения от владельца контура:/)
  assert.ok(text.includes('Историей считаем задачу типа «История»; статус «Готово» — это принято PO.'))
})

test('пустой промт подключения не оставляет пустого заголовка', () => {
  const text = jiraPromptText({ jira: { ...CONFIGURED.jira, prompt: '   ' } }, {})
  assert.doesNotMatch(text, /Промт подключения/)
})

test('токен из окружения включает секцию так же, как поле карточки', () => {
  const settings: SprintSettings = { jira: { ...DEFAULT_JIRA, baseUrl: 'https://jira.example.com' } }
  assert.notEqual(jiraPromptText(settings, { JIRA_TOKEN: 'env' }), '')
})
