"""Отчёт по блокерам команды (sprint-blockers): где и почему команда ждала других.

Ожидаемые числа взяты из эталона — отчёта «Простои из-за внешних зависимостей»
(III квартал 2026): июль–сентябрь — 66 рабочих дней, 1–14 октября — 10,
ожидание 17.08–17.09 — 23 рабочих дня, «с 23.09» на 14.10 — 16.
Команды, задачи и люди в тестах вымышленные.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support

BLOCKERS = support.ROOT / '.claude' / 'skills' / 'sprint-blockers'
waits = support.load_module(BLOCKERS / 'waits.py', 'blockers_waits')
source = support.load_module(BLOCKERS / 'source.py', 'blockers_source')
report = support.load_module(BLOCKERS / 'report.py', 'blockers_report')
FAKE_MCP = support.HERE / 'fixtures' / 'fake_mcp_jira.py'
TEAM = {'slug': 'team-a', 'name': 'Команда А'}


def issue(key, log, status=None, created='2026-06-01T10:00:00+03:00', **extra):
    """Задача снимка: log — [(момент, из, в)]."""
    data = {'key': key, 'summary': f'Задача {key}', 'type': 'История', 'subtask': False,
            'status': status or (log[-1][2] if log else 'Открыто'), 'assignee': 'Участник А',
            'parent': None, 'created': created, 'resolved': None,
            'statusLog': [{'at': at, 'from': a, 'to': b, 'author': 'Участник А'} for at, a, b in log],
            'comments': [], 'links': []}
    data.update(extra)
    return data


def snapshot(*issues):
    return {'version': 1, 'team': {'slug': 'team-a', 'name': 'Команда А'}, 'jql': 'project = DEMO',
            'fetchedAt': '2026-10-14T18:00:00+03:00', 'transport': 'test', 'issues': list(issues)}


class PeriodTest(unittest.TestCase):
    def test_quarter_and_tail_month_windows(self):
        period = waits.period('2026Q3', to='2026-10-14')
        self.assertEqual([('2026-07-01', '2026-09-30', 66), ('2026-10-01', '2026-10-14', 10)],
                         [(w['from'], w['to'], w['workdays']) for w in period['windows']])

    def test_quarter_in_progress_has_one_window(self):
        period = waits.period('2026Q4', to='2026-10-14')
        self.assertEqual([('2026-10-01', '2026-10-14', 10)],
                         [(w['from'], w['to'], w['workdays']) for w in period['windows']])

    def test_holidays_are_not_workdays(self):
        period = waits.period('2026Q4', to='2026-11-06', holidays=['2026-11-04'])
        # будних дней 1.10–6.11: 22 в октябре + 5 в ноябре; 4.11 — праздник
        self.assertEqual(27 - 1, period['windows'][0]['workdays'])


class WaitDaysTest(unittest.TestCase):
    def facts(self, *issues, **params):
        return waits.facts(snapshot(*issues), waits.period('2026Q3', to='2026-10-14'), params)

    def test_closed_wait_counts_workdays_from_start_to_end(self):
        f = self.facts(issue('DEMO-1', [('2026-08-17T11:00:00+03:00', 'In progress', 'On Hold'),
                                        ('2026-09-17T15:00:00+03:00', 'On Hold', 'In progress')]))
        (w,) = f['waits']
        self.assertEqual(('hold', '2026-08-17', '2026-09-17', False, 23),
                         (w['stage'], w['from'], w['to'], w['open'], w['days']['total']))

    def test_open_wait_counts_through_report_date(self):
        f = self.facts(issue('DEMO-2', [('2026-09-23T10:00:00+03:00', 'In progress', 'On Hold')],
                             status='В ожидании'))
        (w,) = f['waits']
        self.assertEqual((True, None, 16), (w['open'], w['to'], w['days']['total']))
        self.assertEqual({'q': 6, 'm': 10}, {k: v for k, v in w['days'].items() if k != 'total'})

    def test_wait_started_before_quarter_counts_only_period_days(self):
        f = self.facts(issue('DEMO-10', [('2026-03-17T10:00:00+03:00', 'In progress', 'On Hold')],
                             status='В ожидании'))
        (w,) = f['waits']
        self.assertEqual(('2026-03-17', 66 + 10, 66, 10),
                         (w['from'], w['days']['total'], w['days']['q'], w['days']['m']))

    def test_english_name_of_ready_to_check_is_review(self):
        f = self.facts(issue('DEMO-11', [('2026-07-06T10:00:00+03:00', 'In progress', 'Ready to Check'),
                                         ('2026-07-20T10:00:00+03:00', 'Ready to Check', 'Closed')]))
        self.assertEqual([('review', 10)], [(w['stage'], w['days']['total']) for w in f['waits']])


class StagesTest(unittest.TestCase):
    def facts(self, *issues, **params):
        return waits.facts(snapshot(*issues), waits.period('2026Q3', to='2026-10-14'), params)

    def stage(self, f, sid):
        return next(st for st in f['stages'] if st['id'] == sid)

    def test_short_review_is_process_not_case_but_counts_in_stage(self):
        f = self.facts(issue('DEMO-3', [('2026-07-06T10:00:00+03:00', 'In progress', 'Review'),
                                        ('2026-07-08T10:00:00+03:00', 'Review', 'Closed')]))
        self.assertEqual([], f['waits'])
        self.assertEqual({'days': 2, 'taskDays': 2, 'tasks': 1, 'medianDays': 2, 'longestDays': 2},
                         self.stage(f, 'review')['windows']['q'])

    def test_long_review_is_a_case(self):
        f = self.facts(issue('DEMO-4', [('2026-07-28T10:00:00+03:00', 'In progress', 'Ревью'),
                                        ('2026-08-24T10:00:00+03:00', 'Ревью', 'Закрыт')]))
        self.assertEqual([('review', 19)], [(w['stage'], w['days']['total']) for w in f['waits']])

    def test_concurrent_waits_do_not_add_up_in_days(self):
        log = [('2026-07-06T10:00:00+03:00', 'In progress', 'On Hold'),
               ('2026-07-10T10:00:00+03:00', 'On Hold', 'In progress')]
        f = self.facts(issue('DEMO-5', log), issue('DEMO-6', log))
        q = self.stage(f, 'hold')['windows']['q']
        self.assertEqual((4, 8, 2), (q['days'], q['taskDays'], q['tasks']))

    def test_skipped_status_is_not_counted(self):
        f = self.facts(issue('DEMO-7', [('2026-07-06T10:00:00+03:00', 'In progress', 'Ready to Install'),
                                        ('2026-09-10T10:00:00+03:00', 'Ready to Install', 'Closed')]),
                       skip=['Ready to Install', 'Готово к установке'])
        self.assertEqual(([], 0), (f['waits'], self.stage(f, 'deploy')['windows']['q']['days']))

    def test_waits_outside_period_are_ignored(self):
        f = self.facts(issue('DEMO-8', [('2026-05-04T10:00:00+03:00', 'In progress', 'On Hold'),
                                        ('2026-06-15T10:00:00+03:00', 'On Hold', 'In progress')]))
        self.assertEqual([], f['waits'])

    def test_team_can_rename_statuses_of_a_stage(self):
        f = self.facts(issue('DEMO-9', [('2026-07-06T10:00:00+03:00', 'In progress', 'Пауза'),
                                        ('2026-07-13T10:00:00+03:00', 'Пауза', 'In progress')]),
                       hold=['Пауза'])
        self.assertEqual([('hold', 5)], [(w['stage'], w['days']['total']) for w in f['waits']])

    def test_same_status_in_two_stages_is_a_config_error(self):
        with self.assertRaises(waits.FactsError):
            self.facts(issue('DEMO-1', []), hold=['Ревью'])


class EvidenceTest(unittest.TestCase):
    def facts(self, *issues):
        return waits.facts(snapshot(*issues), waits.period('2026Q3', to='2026-10-14'), {})

    def test_comments_near_the_wait_and_blocking_links_are_evidence(self):
        parent = issue('DEMO-20', [], status='В работе',
                       links=[{'label': 'depends on', 'key': 'OTHER-5', 'summary': 'Права на базу',
                               'status': 'Открыто'}])
        sub = issue('DEMO-21', [('2026-09-07T10:38:00+03:00', 'In progress', 'On Hold'),
                                ('2026-09-15T19:00:00+03:00', 'On Hold', 'In progress')],
                    parent='DEMO-20', subtask=True,
                    comments=[{'at': '2026-09-07T10:38:56.487+0300', 'author': 'Участник А',
                               'body': 'Ожидает задач OTHER-5'},
                              {'at': '2026-07-01T10:00:00+03:00', 'author': 'Участник Б', 'body': 'давно'}],
                    links=[{'label': 'relates to', 'key': 'DEMO-30', 'summary': 'x', 'status': 'Закрыт'}])
        (w,) = self.facts(parent, sub)['waits']
        self.assertEqual(['Ожидает задач OTHER-5'], [c['text'] for c in w['evidence']['comments']])
        self.assertNotIn('assignee', w)
        self.assertEqual([('OTHER-5', 'DEMO-20')], [(l['key'], l['from']) for l in w['evidence']['links']])

    def test_comment_at_wait_start_comes_first_and_long_ones_are_trimmed(self):
        comments = [{'at': f'2026-09-{d:02d}T12:00:00+03:00', 'author': 'Участник А', 'body': f'заметка {d} ' + 'x' * 400}
                    for d in (14, 12, 10, 9)]
        comments.append({'at': '2026-09-07T10:39:00+03:00', 'author': 'Участник А',
                         'body': 'Ждём права от админов: ' + 'подробности ' * 25 + 'хвост причины'})
        it = issue('DEMO-24', [('2026-09-07T10:38:00+03:00', 'In progress', 'On Hold'),
                               ('2026-09-15T10:00:00+03:00', 'On Hold', 'In progress')], comments=comments)
        (w,) = self.facts(it)['waits']
        texts = [c['text'] for c in w['evidence']['comments']]
        self.assertEqual(4, len(texts))
        self.assertTrue(texts[0].startswith('Ждём права от админов') and texts[0].endswith('хвост причины'), texts[0])
        self.assertTrue(all(len(t) <= 200 for t in texts[1:]))

    def test_wait_words_without_wait_status_are_weak_signals(self):
        it = issue('DEMO-22', [], status='В работе',
                   comments=[{'at': '2026-08-03 12:00:00 MSK', 'author': 'Участник В',
                              'body': 'Ждём доступ к стенду от админов'},
                             {'at': '2026-08-04 12:00:00 MSK', 'author': 'Участник В', 'body': 'Сделал'}])
        f = self.facts(it)
        self.assertEqual([('DEMO-22', 'Ждём доступ к стенду от админов')],
                         [(s['key'], s['text']) for s in f['signals']])

    def test_same_snapshot_gives_same_hash(self):
        it = issue('DEMO-23', [('2026-07-06T10:00:00+03:00', 'In progress', 'On Hold')])
        self.assertEqual(self.facts(it)['factsHash'], self.facts(it)['factsHash'])


class McpSourceTest(unittest.TestCase):
    """Скрипт сам говорит с MCP-сервером: агент данные не возит."""

    def fetch(self, env=None):
        os.environ.update(env or {})
        try:
            with source.McpTransport([sys.executable, str(FAKE_MCP)], timeout=20) as tr:
                return source.fetch(tr, 'project = DEMO', '2026-07-01', '2026-10-14', TEAM,
                                    '2026-10-14T18:00:00+03:00')
        finally:
            for k in (env or {}):
                os.environ.pop(k, None)

    def test_all_pages_are_fetched_and_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'calls.jsonl'
            snap = self.fetch({'FAKE_MCP_LOG': str(log)})
            calls = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(['DEMO-1', 'DEMO-2', 'DEMO-3'], [i['key'] for i in snap['issues']])
        self.assertEqual([0, 2], [c['start_at'] for c in calls])
        self.assertIn('(project = DEMO) AND updated >= "2026-07-01"', calls[0]['jql'])
        self.assertEqual('changelog', calls[0]['expand'])
        first = snap['issues'][0]
        self.assertEqual([{'at': '2026-09-23T10:00:00.000000+03:00', 'from': 'In progress',
                           'to': 'On Hold', 'author': 'Участник А'}], first['statusLog'])
        self.assertEqual([{'label': 'is blocked by', 'key': 'OTHER-7', 'summary': 'Стенд партнёра',
                           'status': 'Открыто'}], first['links'])
        self.assertEqual(('DEMO-1', True), (snap['issues'][2]['parent'], snap['issues'][2]['subtask']))
        self.assertEqual('mcp', snap['transport'])

    def test_snapshot_feeds_facts(self):
        f = waits.facts(self.fetch(), waits.period('2026Q3', to='2026-10-14'), {})
        (w,) = f['waits']
        self.assertEqual(('DEMO-1', 16, ['Ждём данные от партнёра'], ['OTHER-7']),
                         (w['key'], w['days']['total'], [c['text'] for c in w['evidence']['comments']],
                          [l['key'] for l in w['evidence']['links']]))

    def test_tool_error_is_reported(self):
        with self.assertRaises(source.SourceError) as ctx:
            self.fetch({'FAKE_MCP_FAIL': '1'})
        self.assertIn('Unauthorized', str(ctx.exception))

    def test_missing_server_is_reported(self):
        with self.assertRaises(source.SourceError):
            with source.McpTransport(['/nonexistent/mcp-atlassian']):
                pass


class RestSourceTest(unittest.TestCase):
    RAW = {'key': 'DEMO-40', 'fields': {
        'summary': 'Приём заказов', 'status': {'name': 'В ожидании'},
        'issuetype': {'name': 'Подзадача', 'subtask': True}, 'parent': {'key': 'DEMO-39'},
        'assignee': {'displayName': 'Участник Г'}, 'created': '2026-07-01T10:00:00.000+0300',
        'resolutiondate': None,
        'comment': {'comments': [{'created': '2026-08-17T11:05:00.000+0300',
                                  'author': {'displayName': 'Участник Г'}, 'body': 'Нет доступа к базе'}]},
        'issuelinks': [{'type': {'inward': 'is blocked by', 'outward': 'blocks'},
                        'outwardIssue': {'key': 'OTHER-1', 'fields': {'summary': 's', 'status': {'name': 'x'}}}},
                       {'type': {'inward': 'depends on', 'outward': 'supports'},
                        'inwardIssue': {'key': 'OTHER-2', 'fields': {'summary': 'База', 'status': {'name': 'Открыто'}}}}]},
        'changelog': {'histories': [{'created': '2026-08-17T11:00:00.000+0300',
                                     'author': {'displayName': 'Участник Г'},
                                     'items': [{'field': 'assignee', 'toString': 'x'},
                                               {'field': 'status', 'fromString': 'In progress',
                                                'toString': 'On Hold'}]}]}}

    def test_rest_issue_is_normalized_like_mcp(self):
        it = source.from_rest_issue(self.RAW)
        self.assertEqual(('Подзадача', True, 'DEMO-39', 'Участник Г'),
                         (it['type'], it['subtask'], it['parent'], it['assignee']))
        self.assertEqual([('In progress', 'On Hold')], [(e['from'], e['to']) for e in it['statusLog']])
        self.assertEqual([('blocks', 'OTHER-1'), ('depends on', 'OTHER-2')],
                         [(l['label'], l['key']) for l in it['links']])
        self.assertEqual(['Нет доступа к базе'], [c['body'] for c in it['comments']])

    def test_rest_pages_come_from_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            jql = source.period_jql('project = DEMO', '2026-07-01', '2026-10-14')
            key, _ = source.RestTransport.replay_key('/rest/api/2/search', {
                'jql': jql, 'fields': source.FIELDS, 'expand': 'changelog', 'startAt': 0,
                'maxResults': source.PAGE})
            Path(tmp, f'{key}.json').write_text(json.dumps({'total': 1, 'issues': [self.RAW]}),
                                                encoding='utf-8')
            with source.RestTransport('https://jira.demo-workspace.local', support.FAKE_TOKEN,
                                      replay=tmp) as tr:
                snap = source.fetch(tr, 'project = DEMO', '2026-07-01', '2026-10-14', TEAM, 'now')
        self.assertEqual((['DEMO-40'], 'rest'), ([i['key'] for i in snap['issues']], snap['transport']))
        self.assertNotIn(support.FAKE_TOKEN, json.dumps(snap))


def two_waits():
    """Две задачи: приостановка из-за команды БД и долгое ревью своей командой."""
    hold = issue('DEMO-50', [('2026-08-17T11:00:00+03:00', 'In progress', 'On Hold'),
                             ('2026-09-17T15:00:00+03:00', 'On Hold', 'In progress')],
                 comments=[{'at': '2026-08-17T11:01:00+03:00', 'author': 'Участник А',
                            'body': 'Ждём справочник от команды БД, OTHER-9'}])
    review = issue('DEMO-51', [('2026-09-23T10:00:00+03:00', 'In progress', 'Ревью')], status='Ревью')
    return waits.facts(snapshot(hold, review), waits.period('2026Q3', to='2026-10-14'), {})


def doc_for(f, **over):
    doc = {'version': 1, 'factsHash': f['factsHash'],
           'lead': ['Дольше всего команда ждала справочник от команды БД и ревью готового кода.'],
           'sections': {'sides': 'Больше всего дней — команда БД.'},
           'sides': [{'id': 'dba', 'name': 'Команда БД', 'what': 'Справочников и прав доступа'},
                     {'id': 'review', 'name': 'Ревью своей команды', 'what': 'Проверки кода', 'internal': True}],
           'cases': [{'waits': ['w1'], 'side': 'dba', 'what': 'Не заполнен справочник на стенде',
                      'evidence': 'strong', 'basis': '«Ждём справочник от команды БД, OTHER-9»'},
                     {'waits': ['w2'], 'side': 'review', 'what': 'Ревью готовой задачи',
                      'evidence': 'weak', 'basis': 'Статус «Ревью» без комментариев'}],
           'notBlockers': []}
    doc.update(over)
    return doc


class CheckTest(unittest.TestCase):
    def test_valid_doc_builds_tables_from_facts(self):
        f = two_waits()
        errors, warnings, view = report.check(doc_for(f), f)
        self.assertEqual([], errors)
        self.assertEqual([('Команда БД', 23, {'q': 23, 'm': 0}, 'done'),
                          ('Ревью своей команды', 16, {'q': 6, 'm': 10}, 'open')],
                         [(c['side'], c['days'], c['win'], c['state']) for c in view['cases']])
        self.assertEqual({'q': {'any': 29, 'external': 23, 'taskDays': 29, 'externalTaskDays': 23, 'workdays': 66},
                          'm': {'any': 10, 'external': 0, 'taskDays': 10, 'externalTaskDays': 0, 'workdays': 10}},
                         view['kpi'])

    def test_side_task_days_add_up_across_tasks(self):
        log = [('2026-07-06T10:00:00+03:00', 'In progress', 'On Hold'),
               ('2026-07-10T10:00:00+03:00', 'On Hold', 'In progress')]
        f = waits.facts(snapshot(issue('DEMO-60', log), issue('DEMO-61', log)),
                        waits.period('2026Q3', to='2026-10-14'), {})
        doc = doc_for(f, sides=[{'id': 'ops', 'name': 'DevOps', 'what': 'Настроек'}],
                      cases=[{'waits': ['w1'], 'side': 'ops', 'what': 'Ключи', 'evidence': 'weak', 'basis': 'статус'},
                             {'waits': ['w2'], 'side': 'ops', 'what': 'Kafka', 'evidence': 'weak', 'basis': 'статус'}])
        _, _, view = report.check(doc, f)
        (side,) = view['sides']
        self.assertEqual(({'q': 4, 'm': 0}, {'q': 8, 'm': 0}), (side['win'], side['taskDays']))

    def test_case_started_before_quarter_counts_only_period_days(self):
        old = issue('DEMO-70', [('2026-03-02T10:00:00+03:00', 'In progress', 'On Hold'),
                                ('2026-07-15T10:00:00+03:00', 'On Hold', 'In progress')])
        f = waits.facts(snapshot(old), waits.period('2026Q3', to='2026-10-14'), {})
        doc = doc_for(f, sides=[{'id': 'ops', 'name': 'DevOps', 'what': 'Стенда'}],
                      cases=[{'waits': ['w1'], 'side': 'ops', 'what': 'Стенд', 'evidence': 'weak', 'basis': 'статус'}])
        _, _, view = report.check(doc, f)
        (case,) = view['cases']
        self.assertEqual((f['waits'][0]['days']['total'], 10, '02.03–15.07'),
                         (case['days'], case['win']['q'], case['when']))

    def test_every_wait_must_be_decided(self):
        f = two_waits()
        doc = doc_for(f)
        doc['cases'].pop()
        errors, _, view = report.check(doc, f)
        self.assertIsNone(view)
        self.assertTrue(any('w2' in e and 'не разобрано' in e for e in errors), errors)

    def test_wait_cannot_be_in_two_cases(self):
        f = two_waits()
        doc = doc_for(f, notBlockers=[{'waits': ['w1'], 'why': 'пауза по приоритету'}])
        errors, _, _ = report.check(doc, f)
        self.assertTrue(any('уже разобрано' in e for e in errors), errors)

    def test_stale_facts_hash_is_rejected(self):
        f = two_waits()
        errors, _, _ = report.check(doc_for(f, factsHash='0' * 16), f)
        self.assertTrue(any('factsHash' in e for e in errors), errors)

    def test_unknown_issue_key_in_text_is_an_error(self):
        f = two_waits()
        doc = doc_for(f, lead=['Команда ждала задачу NOPE-1 дольше всего, это главное узкое место.'])
        errors, _, _ = report.check(doc, f)
        self.assertTrue(any('NOPE-1' in e for e in errors), errors)

    def test_invented_number_is_a_warning(self):
        f = two_waits()
        doc = doc_for(f, lead=['Из-за команды БД задачи стояли 41 рабочий день — больше всех.'])
        errors, warnings, _ = report.check(doc, f)
        self.assertEqual([], errors)
        self.assertTrue(any('41' in w for w in warnings), warnings)

    def test_number_from_tables_is_fine(self):
        f = two_waits()
        doc = doc_for(f, lead=['Из-за команды БД задачи стояли 23 рабочих дня из 66 — больше всех.'])
        self.assertEqual([], report.check(doc, f)[1])


class PageTest(unittest.TestCase):
    def page(self, f, doc):
        _, _, view = report.check(doc, f)
        return report.render(view, '2026-10-14T18:00')

    def test_page_has_sections_and_numbers(self):
        f = two_waits()
        html = self.page(f, doc_for(f))
        for text in ('Блокеры: Команда А, III квартал 2026', 'Кого ждали', 'Где стояли задачи',
                     'Главные случаи', 'Источники и ограничения', 'Июль–сентябрь, раб. дней из 66',
                     '1–14 октября, раб. дней из 10', '17.08–17.09', 'с 23.09', 'решено', 'открыто',
                     'слабое подтверждение', 'Часы работы не измеряются'):
            self.assertIn(text, html)

    def test_jira_text_is_escaped(self):
        f = two_waits()
        doc = doc_for(f)
        doc['cases'][0]['basis'] = '<img src=x onerror=alert(1)></script>'
        html = self.page(f, doc)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;img src=x', html)


class CliTest(unittest.TestCase):
    """Сквозной прогон: конфиг → fetch через MCP → facts → файл агента → apply."""

    def run_cli(self, ws, *args):
        proc = subprocess.run([sys.executable, str(BLOCKERS / 'blockers.py'), '--config',
                               str(ws / 'sprint-report.config.toml'), *args, '--team', 'team-a',
                               '--quarter', '2026Q3', '--to', '2026-10-14', '--now', '2026-10-14T18:00'],
                              capture_output=True, text=True, timeout=60)
        return proc.returncode, proc.stdout + proc.stderr

    def test_full_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            mcp = json.dumps([sys.executable, str(FAKE_MCP)])
            (ws / 'sprint-report.config.toml').write_text(
                'version = 1\n[[teams]]\nslug = "team-a"\nname = "Команда А"\nboard = 101\n'
                '[teams.params.blockers]\njql = "project = DEMO"\n'
                f'mcp = {mcp}\n', encoding='utf-8')
            code, out = self.run_cli(ws, 'fetch')
            self.assertEqual(0, code, out)
            code, out = self.run_cli(ws, 'facts')
            self.assertEqual(0, code, out)
            facts = json.loads(out)
            self.assertEqual(['DEMO-1'], [w['key'] for w in facts['waits']])
            code, out = self.run_cli(ws, 'apply')
            self.assertEqual(2, code, out)
            self.assertIn('файла разбора нет', out)
            doc = {'version': 1, 'factsHash': facts['factsHash'],
                   'lead': ['Команда с 23.09 ждёт данные от партнёра для проверки — случай открыт.'],
                   'sides': [{'id': 'partner', 'name': 'Партнёр', 'what': 'Данных для проверки'}],
                   'cases': [{'waits': ['w1'], 'side': 'partner', 'what': 'Данные для проверки',
                              'evidence': 'strong', 'basis': '«Ждём данные от партнёра»'}],
                   'notBlockers': []}
            (ws / 'reports' / 'blockers' / 'team-a-2026Q3.json').write_text(
                json.dumps(doc, ensure_ascii=False), encoding='utf-8')
            code, out = self.run_cli(ws, 'apply')
            self.assertEqual(0, code, out)
            page = (ws / 'reports' / 'blockers-team-a-2026Q3.html').read_text(encoding='utf-8')
            self.assertIn('https://jira.demo-workspace.local/browse/DEMO-1', page)

    def test_missing_jql_is_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / 'sprint-report.config.toml').write_text(
                'version = 1\n[[teams]]\nslug = "team-a"\nname = "Команда А"\nboard = 101\n',
                encoding='utf-8')
            code, out = self.run_cli(ws, 'fetch')
            self.assertEqual((2, True), (code, 'params.blockers.jql' in out), out)


class DefaultQuarterTest(unittest.TestCase):
    def test_first_month_reports_previous_quarter(self):
        bl = support.load_module(BLOCKERS / 'blockers.py', 'blockers_cli')
        from datetime import date
        self.assertEqual(['2026Q3', '2026Q4', '2025Q4'],
                         [bl.default_quarter(date(2026, 10, 14)), bl.default_quarter(date(2026, 11, 2)),
                          bl.default_quarter(date(2026, 1, 20))])


class DemoTest(unittest.TestCase):
    """Пример в examples/ проходит проверку: по нему учатся и агент, и человек."""

    def test_demo_example_is_accepted(self):
        ex = BLOCKERS / 'examples'
        snap = json.loads((ex / 'demo-snapshot.json').read_text(encoding='utf-8'))
        doc = json.loads((ex / 'demo-blockers.json').read_text(encoding='utf-8'))
        f = waits.facts(snap, waits.period('2026Q3', to='2026-10-14'), {})
        errors, warnings, view = report.check(doc, f)
        self.assertEqual(([], []), (errors, warnings),
                         f'пример устарел: factsHash сейчас {f["factsHash"]}')
        self.assertEqual(('Команда БД', 23), (view['cases'][1]['side'], view['cases'][1]['days']))


class SkillDocTest(unittest.TestCase):
    def test_skill_and_command(self):
        skill = (BLOCKERS / 'SKILL.md').read_text(encoding='utf-8')
        self.assertIn('ИИ не источник данных', skill)
        self.assertIn('blockers.py apply', skill)
        self.assertTrue((support.ROOT / '.claude' / 'commands' / 'sprint-blockers.md').is_file())
        self.assertIn('sprint-blockers', (support.ROOT / 'install.sh').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
