import assert from 'node:assert/strict'
import test from 'node:test'
import { buildStoriesJql, quoteJql, splitOrderBy } from '../src/jira/jql.js'

test('кавычки экранируются, а не вырезаются', () => {
  assert.equal(quoteJql('SPRINT'), '"SPRINT"')
  assert.equal(quoteJql('он сказал "да"'), '"он сказал \\"да\\""')
  assert.equal(quoteJql('путь\\к'), '"путь\\\\к"')
})

test('ORDER BY отделяется от условий', () => {
  assert.deepEqual(splitOrderBy('project = "A" ORDER BY rank'), { where: 'project = "A"', order: 'ORDER BY rank' })
  assert.deepEqual(splitOrderBy('project = "A"'), { where: 'project = "A"', order: '' })
  // регистр и перенос строки не должны мешать
  assert.deepEqual(splitOrderBy('project = "A"\norder by\n updated DESC'), {
    where: 'project = "A"', order: 'order by\n updated DESC',
  })
})

test('запрос историй строится из ключа проекта и открытых спринтов', () => {
  const built = buildStoriesJql({ projectKey: 'SPRINT', storiesJql: '' })
  assert.deepEqual(built, { jql: 'project = "SPRINT" AND sprint in openSprints() ORDER BY updated DESC' })
})

test('sprint=any снимает фильтр по спринту', () => {
  const built = buildStoriesJql({ projectKey: 'SPRINT', storiesJql: '', sprint: 'any' })
  assert.deepEqual(built, { jql: 'project = "SPRINT" ORDER BY updated DESC' })
})

test('фильтры инструмента дописываются к условиям', () => {
  const built = buildStoriesJql({
    projectKey: 'SPRINT', storiesJql: '', assignee: 'ivanov', status: 'In Progress', issueType: 'История',
  })
  assert.deepEqual(built, {
    jql: 'project = "SPRINT" AND sprint in openSprints() AND assignee = "ivanov" '
      + 'AND status = "In Progress" AND issuetype = "История" ORDER BY updated DESC',
  })
})

test('свой JQL побеждает ключ проекта, фильтры встают ПЕРЕД ORDER BY', () => {
  const built = buildStoriesJql({
    projectKey: 'SPRINT',
    storiesJql: 'project in (A, B) AND sprint in openSprints() ORDER BY rank',
    assignee: 'petrov',
  })
  assert.deepEqual(built, {
    jql: 'project in (A, B) AND sprint in openSprints() AND (assignee = "petrov") ORDER BY rank',
  })
})

test('без проекта и без своего JQL — названная причина, а не пустой запрос', () => {
  const built = buildStoriesJql({ projectKey: '  ', storiesJql: '' })
  assert.ok('problem' in built)
  assert.match(built.problem, /ключ проекта/)
})
