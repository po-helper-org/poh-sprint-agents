import assert from 'node:assert/strict'
import test from 'node:test'
import { descriptionOf, normalizeIssue, sprintNameOf, storyPointsOf } from '../src/jira/normalize.js'

const BASE = 'https://jira.example.com'

test('задача Server/DC приводится к нашей форме', () => {
  const issue = normalizeIssue({
    key: 'SPRINT-128',
    fields: {
      summary: 'Витрина кино с фильтрацией',
      issuetype: { name: 'История' },
      status: { name: 'В работе' },
      assignee: { displayName: 'Иванов И.', name: 'ivanov' },
      priority: { name: 'Must' },
      labels: ['carryover'],
      updated: '2026-07-20T10:00:00.000+0300',
      parent: { key: 'SPRINT-100' },
      customfield_10004: 5,
      customfield_10007: ['com.atlassian.greenhopper.service.sprint.Sprint@1a[id=42,name=2026Q3-S7,state=ACTIVE]'],
    },
  }, { baseUrl: BASE, storyPointsField: 'customfield_10004' })

  assert.deepEqual(issue, {
    key: 'SPRINT-128',
    summary: 'Витрина кино с фильтрацией',
    url: `${BASE}/browse/SPRINT-128`,
    type: 'История',
    status: 'В работе',
    assignee: 'Иванов И.',
    priority: 'Must',
    storyPoints: 5,
    sprint: '2026Q3-S7',
    parent: 'SPRINT-100',
    labels: ['carryover'],
    updated: '2026-07-20T10:00:00.000+0300',
  })
})

test('чего нет в ответе — того нет в результате (никаких подставленных значений)', () => {
  const issue = normalizeIssue({ key: 'SPRINT-1', fields: { summary: 'Без полей' } }, { baseUrl: BASE })
  assert.deepEqual(issue, { key: 'SPRINT-1', summary: 'Без полей', url: `${BASE}/browse/SPRINT-1` })
})

test('запись без ключа задачей не считается', () => {
  assert.equal(normalizeIssue({ fields: {} }, { baseUrl: BASE }), undefined)
  assert.equal(normalizeIssue('нет', { baseUrl: BASE }), undefined)
})

test('активный спринт выигрывает у закрытого', () => {
  const name = sprintNameOf({
    customfield_10007: [
      'com.atlassian.greenhopper.service.sprint.Sprint@1[id=41,name=2026Q3-S6,state=CLOSED]',
      'com.atlassian.greenhopper.service.sprint.Sprint@2[id=42,name=2026Q3-S7,state=ACTIVE]',
    ],
  })
  assert.equal(name, '2026Q3-S7')
})

test('спринт в облачной форме — объектом', () => {
  assert.equal(sprintNameOf({ sprint: { id: 42, name: 'Sprint 7', state: 'active' } }), 'Sprint 7')
  assert.equal(sprintNameOf({ customfield_10020: [{ name: 'Sprint 6', state: 'closed' }] }), 'Sprint 6')
})

test('оценка читается только из названного поля и только числом', () => {
  assert.equal(storyPointsOf({ customfield_10004: 8 }, 'customfield_10004'), 8)
  assert.equal(storyPointsOf({ customfield_10004: '8' }, 'customfield_10004'), undefined)
  assert.equal(storyPointsOf({ customfield_10004: 8 }, undefined), undefined)
})

test('описание: строка Server/DC и документ ADF облака', () => {
  assert.equal(descriptionOf('Текст описания'), 'Текст описания')
  const adf = {
    type: 'doc',
    content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'Первый абзац' }] },
      { type: 'paragraph', content: [{ type: 'text', text: 'Второй абзац' }] },
    ],
  }
  assert.equal(descriptionOf(adf), 'Первый абзац\nВторой абзац')
  assert.equal(descriptionOf(undefined), undefined)
})
