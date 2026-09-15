import assert from 'node:assert/strict'
import test from 'node:test'
import { renderConnection, renderIssue, renderSearch } from '../src/render.js'

test('пустая выдача сказана словами, а не пустой таблицей', () => {
  const text = renderSearch({ jql: 'project = "SPRINT"', total: 0, issues: [] })
  assert.match(text, /По запросу ничего не найдено/)
})

test('незаполненное поле показывается прочерком, а не выдуманным значением', () => {
  const text = renderSearch({
    jql: 'project = "SPRINT"',
    total: 1,
    issues: [{ key: 'SPRINT-2', summary: 'Без исполнителя', url: 'https://jira.example.com/browse/SPRINT-2' }],
  })
  assert.match(text, /SPRINT-2 \| — \| — \| — \| — \| — \| Без исполнителя/)
})

test('вертикальная черта в заголовке не ломает таблицу', () => {
  const text = renderSearch({
    jql: 'project = "SPRINT"',
    total: 1,
    issues: [{ key: 'SPRINT-3', summary: 'A | B', url: 'https://jira.example.com/browse/SPRINT-3' }],
  })
  assert.match(text, /A \\\| B/)
})

test('одна задача печатается карточкой с описанием', () => {
  const text = renderIssue({
    key: 'SPRINT-1', summary: 'Кино', url: 'https://jira.example.com/browse/SPRINT-1',
    status: 'В работе', storyPoints: 5, description: 'БЫЛО→СТАЛО',
  })
  assert.match(text, /^SPRINT-1 — Кино/)
  assert.match(text, /Ссылка: https:\/\/jira\.example\.com\/browse\/SPRINT-1/)
  assert.match(text, /Описание:\nБЫЛО→СТАЛО/)
})

test('итог проверки подключения — одна строка с учёткой и предупреждением', () => {
  const text = renderConnection({
    baseUrl: 'https://jira.example.com',
    identity: { displayName: 'Иванов И.', name: 'ivanov' },
    warning: 'не задан ключ проекта',
  })
  assert.equal(text, 'Подключение к https://jira.example.com установлено: Иванов И.; не задан ключ проекта')
})
