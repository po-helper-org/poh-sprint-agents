"""Риски квартала для CPO (/business/risks): прогноз, статусы, эскалации, страница.

Спека — docs/quarter-risks.md, термины — GLOSSARY.md. Ожидаемые числа посчитаны вручную
по правилам спеки, а не тем же кодом. Всё без сети.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import date, timedelta

import support

BUSINESS_DIR = support.ROOT / '.claude' / 'skills' / 'sprint-business'
sys.path.insert(0, str(BUSINESS_DIR))
import forecast as fc  # noqa: E402
import quarter_model as qm  # noqa: E402
import quarter as qr  # noqa: E402

MONDAY = date(2026, 10, 19)
Q_END = date(2026, 12, 31)


class WeeklyThroughputTest(unittest.TestCase):
    def test_counts_closures_per_full_week_and_skips_current_week(self):
        done = [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 13), date(2026, 10, 19)]
        # недели: 28.09–04.10, 05.10–11.10, 12.10–18.10; 19.10 — текущая, не входит
        self.assertEqual([2, 0, 1], fc.weekly_throughput(done, MONDAY, window=3))

    def test_window_starts_no_earlier_than_week_work_began(self):
        done = [date(2026, 10, 13)]
        # работа началась 07.10 — история с недели 05.10, а не за все 12 недель
        self.assertEqual([0, 1], fc.weekly_throughput(done, MONDAY, window=12, since=date(2026, 10, 7)))


class ForecastTest(unittest.TestCase):
    def test_steady_pace_finishes_on_known_sunday(self):
        # 10 задач по 2 в неделю — ровно 5 недель: воскресенье 22.11, к 31.12 — наверняка
        r = fc.forecast(10, [2] * 10, MONDAY, Q_END)
        self.assertEqual('ok', r['status'])
        self.assertEqual(1.0, r['chance'])
        self.assertEqual(date(2026, 11, 22), r['p85'])
        self.assertEqual(date(2026, 11, 22), r['p50'])

    def test_how_many_by_quarter_end_counts_whole_weeks_only(self):
        # до 31.12 (чт) — 10 полных недель, по 2 задачи — 20
        r = fc.forecast(30, [2] * 10, MONDAY, Q_END)
        self.assertEqual(10, r['weeksLeft'])
        self.assertEqual(20, r['howMany85'])
        self.assertEqual(0.0, r['chance'])

    def test_last_monday_to_unblock_keeps_even_chance(self):
        # 5 недель работы из 10 оставшихся: начать можно не позже чем через 5 недель — 23.11
        r = fc.forecast(10, [2] * 10, MONDAY, Q_END)
        self.assertEqual(date(2026, 11, 23), r['okUntil'])

    def test_coin_flip_week_gives_half_chance(self):
        # неделя либо 0, либо 4 задачи поровну; 4 задачи и 1 неделя — шанс 50%
        r = fc.forecast(4, [0, 4] * 5, MONDAY, date(2026, 10, 25))
        self.assertAlmostEqual(0.5, r['chance'], delta=0.03)

    def test_scope_growth_never_raises_the_chance(self):
        base = fc.forecast(20, [0, 2, 3, 1, 4, 2, 0, 3, 2, 1], MONDAY, Q_END, seed=7)
        grown = fc.forecast(20, [0, 2, 3, 1, 4, 2, 0, 3, 2, 1], MONDAY, Q_END, growth=1.0, seed=7)
        self.assertLess(grown['chance'], base['chance'])
        self.assertLessEqual(base['p50'], base['p85'])
        self.assertLessEqual(base['p85'], base['p95'])

    def test_same_seed_same_answer(self):
        a = fc.forecast(20, [0, 2, 3, 1, 4, 2, 0, 3, 2, 1], MONDAY, Q_END, seed=42)
        b = fc.forecast(20, [0, 2, 3, 1, 4, 2, 0, 3, 2, 1], MONDAY, Q_END, seed=42)
        self.assertEqual(a, b)

    def test_short_or_empty_history_gives_no_forecast(self):
        self.assertEqual('no_data', fc.forecast(5, [1] * 6, MONDAY, Q_END)['status'])
        self.assertEqual('no_data', fc.forecast(5, [0] * 12, MONDAY, Q_END)['status'])
        self.assertEqual('thin', fc.forecast(5, [1] * 8, MONDAY, Q_END)['status'])

    def test_nothing_left_is_done(self):
        self.assertEqual('done', fc.forecast(0, [1] * 12, MONDAY, Q_END)['status'])


# ------------------------------------------------------------------ модель квартала

def done_items(prefix, per_week, weeks=12, created='2026-07-01'):
    """Закрытые задачи: per_week штук в каждую из weeks полных недель перед MONDAY (по средам)."""
    out = []
    for w in range(weeks):
        day = MONDAY - timedelta(weeks=weeks - w) + timedelta(days=2)
        out += [{'key': f'{prefix}-D{w}-{i}', 'title': 'сделано', 'status': 'Готово', 'bucket': 'done',
                 'created': created, 'doneAt': day.isoformat(), 'statusChanged': day.isoformat()}
                for i in range(per_week)]
    return out


def open_items(prefix, n, created='2026-07-01', status='В работе', bucket='progress', changed='2026-10-16'):
    return [{'key': f'{prefix}-O{i}', 'title': f'задача {i}', 'status': status, 'bucket': bucket,
             'created': created, 'doneAt': None, 'statusChanged': changed} for i in range(n)]


def epic(key, items, title=None, due=None, status='В работе', bucket='progress'):
    return {'key': key, 'title': title or f'Инициатива {key}', 'status': status, 'bucket': bucket,
            'due': due, 'items': items}


def world(epics, goals_extra=None):
    keys = [e['key'] for e in epics]
    goals = {'gds': {'quarter': '2026Q4', 'objectives': {'OBJ 1': 'Цель один'},
                     'epics': {k: 'OBJ 1' for k in keys}, 'kr': {k: f'KR 1.{i}' for i, k in enumerate(keys, 1)},
                     **(goals_extra or {})}}
    data = {'version': 1, 'quarter': '2026Q4', 'fetchedAt': '2026-10-19T08:40:00+03:00',
            'teams': [{'slug': 'gds', 'name': 'GDS', 'epics': epics}]}
    return goals, data


def row_of(view, key):
    for group in ('teams', 'unconfirmed', 'dropped'):
        rows = [r for t in view[group] for r in t['rows']] if group == 'teams' else view[group]
        for r in rows:
            if r['key'] == key:
                return r
    raise AssertionError(f'нет строки {key}')


class QuarterModelTest(unittest.TestCase):
    def test_initiative_with_steady_pace_is_on_track_by_quarter_end(self):
        goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 6))])
        view = qm.build(goals, data)
        r = row_of(view, 'E-1')
        self.assertEqual('green', r['status'])
        self.assertEqual(1.0, r['chance'])
        self.assertEqual(date(2026, 11, 8), r['p85'])       # 6 задач по 2 — три недели
        self.assertEqual(date(2026, 12, 31), view['deadline'])
        self.assertEqual({'green': 1}, {k: v for k, v in view['counts'].items() if v})

    def test_too_much_left_is_off_track_and_asks_for_scope_decision(self):
        goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 60))])
        view = qm.build(goals, data)
        r = row_of(view, 'E-1')
        self.assertEqual('red', r['status'])
        self.assertEqual(20, r['howMany85'])
        cand = view['candidates'][0]
        self.assertEqual('E-1', cand['key'])
        self.assertEqual('решение по объёму или сроку: к 31.12 с 85% успеем 20 из 60 задач', cand['ask'])
        self.assertEqual(date(2026, 10, 26), cand['by'])
        self.assertEqual('снять 40 из 60 задач из квартала, сдвинуть срок или дать людей', r['path'])
        self.assertEqual([], view['escalations'])

    def test_blocker_age_in_working_days_sets_the_colour(self):
        def status_with(changed):
            items = done_items('E1', 2) + open_items('E1', 5) + \
                open_items('E1B', 1, status='В ожидании', bucket='blocked', changed=changed)
            goals, data = world([epic('E-1', items)])
            return row_of(qm.build(goals, data), 'E-1')
        red = status_with('2026-10-05')       # 05.10–16.10 — 10 рабочих дней
        self.assertEqual(('red', 10), (red['status'], red['blockers'][0]['days']))
        self.assertEqual(('yellow', 4), (status_with('2026-10-13')['status'], status_with('2026-10-13')['blockers'][0]['days']))
        fresh = status_with('2026-10-16')     # 1 рабочий день — ещё не блокатор
        self.assertEqual(('green', []), (fresh['status'], fresh['blockers']))

    def test_blocked_initiative_proposes_unblock_by_last_safe_monday(self):
        items = done_items('E1', 2) + open_items('E1', 5) + \
            open_items('E1B', 1, status='В ожидании', bucket='blocked', changed='2026-10-13')
        goals, data = world([epic('E-1', items)])
        view = qm.build(goals, data)
        cand = view['candidates'][0]
        self.assertEqual('снять блокатор E1B-O0: «В ожидании» 4 раб. дн.', cand['ask'])
        # 6 задач по 2 — 3 недели из 10: начать можно не позже чем через 7 недель — 07.12
        self.assertEqual(date(2026, 12, 7), cand['by'])
        self.assertEqual('снять блокатор до 07.12', row_of(view, 'E-1')['path'])

    def test_approved_candidate_becomes_escalation_until_text_changes(self):
        goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 60))])
        h = qm.build(goals, data)['candidates'][0]['hash']
        view = qm.build(goals, data, approvals={'E-1': h})
        self.assertEqual(['E-1'], [e['key'] for e in view['escalations']])
        self.assertEqual([], view['candidates'])
        block = {'teams': {'gds': {'initiatives': {'E-1': {'escalation': {
            'ask': 'снять 30 задач второй волны', 'who': 'CPO', 'by': '2026-10-26', 'ifNot': 'уйдёт в Q1'}}}}}}
        view = qm.build(goals, data, block=block, approvals={'E-1': h})
        self.assertEqual([], view['escalations'])
        self.assertEqual('снять 30 задач второй волны', view['candidates'][0]['ask'])
        self.assertEqual('agent', view['candidates'][0]['source'])

    def test_only_three_escalations_on_top_soonest_first(self):
        eps = [epic(f'E-{i}', done_items(f'E{i}', 2) + open_items(f'E{i}', 60)) for i in range(1, 5)]
        goals, data = world(eps)
        dates = {'E-1': '2026-11-02', 'E-2': '2026-10-26', 'E-3': '2026-11-09', 'E-4': '2026-10-28'}
        block = {'teams': {'gds': {'initiatives': {k: {'escalation': {'ask': 'решение', 'who': 'CPO', 'by': d,
                                                                       'ifNot': 'не успеем'}} for k, d in dates.items()}}}}
        hashes = {c['key']: c['hash'] for c in qm.build(goals, data, block=block)['candidates']}
        view = qm.build(goals, data, block=block, approvals=hashes)
        self.assertEqual(['E-2', 'E-4', 'E-1'], [e['key'] for e in view['escalations']])
        self.assertEqual(1, view['moreEscalations'])

    def test_young_initiative_borrows_team_pace(self):
        young = epic('E-2', done_items('E2', 1, weeks=2, created='2026-10-05') + open_items('E2', 3, created='2026-10-05'))
        goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 6)), young])
        r = row_of(qm.build(goals, data), 'E-2')
        self.assertEqual('team', r['method'])
        self.assertIn(r['status'], ('green', 'yellow', 'red'))

    def test_initiative_without_tasks_has_no_forecast_and_asks_to_decompose(self):
        goals, data = world([epic('E-1', [])])
        r = row_of(qm.build(goals, data), 'E-1')
        self.assertEqual(('none', 'декомпозировать эпик: задач нет'), (r['status'], r['path']))

    def test_initiative_missing_from_jira_data_is_reported_not_dropped(self):
        goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 6))])
        goals['gds']['epics']['E-9'] = 'OBJ 1'
        r = row_of(qm.build(goals, data), 'E-9')
        self.assertEqual('none', r['status'])
        self.assertEqual('нет данных из Jira', r['note'])

    def test_po_assessment_overrides_status_and_keeps_calculation(self):
        goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 6))])
        block = {'teams': {'gds': {'initiatives': {'E-1': {'override': {'status': 'yellow', 'reason': 'ждём юристов'}}}}}}
        r = row_of(qm.build(goals, data, block=block), 'E-1')
        self.assertEqual(('yellow', 'green', 'ждём юристов'), (r['status'], r['computedStatus'], r['override']))

    def test_unconfirmed_and_dropped_stay_out_of_quarter_counts(self):
        goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 6)),
                             epic('E-2', done_items('E2', 2) + open_items('E2', 60)),
                             epic('E-3', done_items('E3', 2) + open_items('E3', 60))],
                            goals_extra={'unconfirmed': ['E-2'], 'dropped': ['E-3']})
        view = qm.build(goals, data)
        self.assertEqual(1, sum(view['counts'].values()))
        self.assertEqual(['E-2'], [r['key'] for r in view['unconfirmed']])
        self.assertEqual(['E-3'], [r['key'] for r in view['dropped']])
        self.assertEqual([], view['candidates'])

    def test_finished_initiative_is_done(self):
        goals, data = world([epic('E-1', done_items('E1', 2))])
        self.assertEqual('done', row_of(qm.build(goals, data), 'E-1')['status'])

    def test_shift_against_last_week_snapshot(self):
        items = done_items('E1', 2) + open_items('E1', 5) + \
            open_items('E1B', 1, status='В ожидании', bucket='blocked', changed='2026-10-13')
        goals, data = world([epic('E-1', items)])
        prev = {'week': '2026-10-12', 'rows': {'E-1': {'status': 'green', 'p85': '2026-11-01', 'chance': 1.0,
                                                       'blockers': ['E1-OLD']}}}
        view = qm.build(goals, data, history=prev)
        d = row_of(view, 'E-1')['delta']
        self.assertEqual(7, d['p85Days'])                     # 01.11 → 08.11
        self.assertEqual('green', d['statusWas'])
        self.assertEqual(['E1B-O0'], d['newBlockers'])
        self.assertEqual(['E1-OLD'], d['resolvedBlockers'])
        self.assertEqual(1, view['shifted'])
        self.assertEqual({'status': 'yellow', 'p85': '2026-11-08', 'chance': 1.0, 'blockers': ['E1B-O0']},
                         view['snapshot']['rows']['E-1'])


class TeamSummaryAndWordingTest(unittest.TestCase):
    def test_team_summary_forecasts_whole_quarter_scope_even_with_short_history(self):
        young = '2026-10-01'
        goals, data = world([epic('E-1', done_items('E1', 1, weeks=3, created=young) + open_items('E1', 10, created=young)),
                             epic('E-2', open_items('E2', 5, created=young))])
        view = qm.build(goals, data)
        self.assertEqual(['none', 'none'], [r['status'] for r in view['teams'][0]['rows']])
        s = view['teams'][0]['summary']
        # 3 недели по 1 задаче: к 31.12 (10 недель) закроем 10 из 15 — весь объём не успеваем
        self.assertEqual((15, 3, 1.0, 10, 0.0, True), (s['open'], s['points'], s['pace'], s['howMany85'], s['chance'], s['thin']))

    def test_no_pace_at_all_asks_whether_initiative_stays_in_quarter(self):
        items = done_items('E1', 0, weeks=12) + [{'key': 'E1-OLD', 'title': 'давно', 'status': 'Готово', 'bucket': 'done',
                                                  'created': '2026-07-01', 'doneAt': '2026-08-05', 'statusChanged': '2026-08-05'}]
        goals, data = world([epic('E-1', items + open_items('E1', 13))])
        r = row_of(qm.build(goals, data), 'E-1')
        self.assertEqual((0, 'red'), (r['howMany85'], r['status']))
        self.assertEqual('по нынешнему темпу к 31.12 не закроется ни одной задачи — решить, остаётся ли в квартале', r['path'])

    def test_cpo_text_names_kr_once_and_says_why_red(self):
        items = done_items('E1', 2) + open_items('E1', 5) + \
            open_items('E1B', 1, status='В ожидании', bucket='blocked', changed='2026-10-05')
        goals, data = world([epic('E-1', items)])
        text = qr.cpo_text(qm.build(goals, data))
        self.assertIn('- GDS · KR 1.1 — Не успевает (блокатор 10 раб. дн.), шанс 100%, путь в зелёный: снять блокатор до 07.12', text)
        self.assertIn('GDS: открыто 6 из 30 задач · темп 2 в нед. · к 31.12 с 85% закроем 6 из 6', text)


# ------------------------------------------------------------------ сбор из Jira

def raw_issue(key, epic_key, status, category, created, resolved=None, changes=(), assignee='Иван Тестов'):
    return {'key': key, 'fields': {
        'summary': f'Задача {key}', 'status': {'name': status, 'statusCategory': {'name': category}},
        'issuetype': {'name': 'История', 'subtask': False}, 'assignee': {'displayName': assignee},
        'created': created, 'resolutiondate': resolved, 'customfield_10006': epic_key},
        'changelog': {'histories': [{'created': at, 'items': [{'field': 'status', 'fromString': a, 'toString': b}]}
                                    for at, a, b in changes]}}


class FakeJira:
    """Jira на два эпика: E-1 виден, E-2 не отдаётся по правам. Страницы поиска — по 1 задаче."""

    def __init__(self):
        self.calls = []
        self.scope = [
            raw_issue('T-1', 'E-1', 'В ожидании', 'В работе', '2026-07-01T10:00:00.000+0300',
                      changes=[('2026-10-01T09:00:00.000+0300', 'Открыт', 'В работе'),
                               ('2026-10-13T11:00:00.000+0300', 'В работе', 'В ожидании')]),
            raw_issue('T-2', 'E-1', 'Готово', 'Выполнено', '2026-07-01T10:00:00.000+0300',
                      resolved='2026-10-07T18:00:00.000+0300'),
        ]

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == '/rest/api/2/field':
            return [{'id': 'customfield_10006', 'name': 'Epic Link'}, {'id': 'customfield_10925', 'name': 'Target end'}]
        jql = params['jql']
        if jql.startswith('key in'):
            return {'total': 1, 'issues': [{'key': 'E-1', 'fields': {
                'summary': 'Витрина без БАЗИС', 'status': {'name': 'В работе', 'statusCategory': {'name': 'В работе'}},
                'customfield_10925': '2026-11-15T00:00:00.000+0300', 'duedate': None}}]}
        start = int(params.get('startAt', 0))
        return {'total': len(self.scope), 'issues': self.scope[start:start + 1]}


class FetchTest(unittest.TestCase):
    def fetch(self):
        goals = {'gds': {'quarter': '2026Q4', 'epics': {'E-1': 'OBJ 1', 'E-2': 'OBJ 1'}}}
        teams = [{'slug': 'gds', 'name': 'GDS', 'params': {}}]
        return qr.fetch(FakeJira(), teams, goals, '2026-10-19T08:40:00+03:00', page=1)

    def test_quarter_epics_come_with_all_their_tasks_and_status_history(self):
        data = self.fetch()
        self.assertEqual('2026Q4', data['quarter'])
        epic = data['teams'][0]['epics'][0]
        self.assertEqual(('E-1', 'Витрина без БАЗИС', '2026-11-15', 'progress'),
                         (epic['key'], epic['title'], epic['due'], epic['bucket']))
        by_key = {it['key']: it for it in epic['items']}
        self.assertEqual({'status': 'В ожидании', 'bucket': 'blocked', 'created': '2026-07-01', 'doneAt': None,
                          'statusChanged': '2026-10-13', 'assignee': 'Иван Тестов'},
                         {k: by_key['T-1'][k] for k in ('status', 'bucket', 'created', 'doneAt', 'statusChanged', 'assignee')})
        self.assertEqual(('done', '2026-10-07'), (by_key['T-2']['bucket'], by_key['T-2']['doneAt']))

    def test_epic_jira_did_not_return_is_a_warning_not_a_silent_gap(self):
        team = self.fetch()['teams'][0]
        self.assertEqual(['E-1'], [e['key'] for e in team['epics']])
        self.assertIn('E-2', ' '.join(team['warnings']))


# ------------------------------------------------------------------ страница и текст

def approved_view(title='Инициатива E-1'):
    goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 60), title=title),
                         epic('E-2', done_items('E2', 2) + open_items('E2', 6))])
    h = qm.build(goals, data)['candidates'][0]['hash']
    return qm.build(goals, data, approvals={'E-1': h})


class PageTest(unittest.TestCase):
    def test_page_leads_with_decisions_then_all_initiatives(self):
        html = qr.render_html(approved_view())
        self.assertIn('Нужно решение', html)
        self.assertIn('решение по объёму или сроку: к 31.12 с 85% успеем 20 из 60 задач', html)
        self.assertLess(html.index('Нужно решение'), html.index('Инициатива E-2'))
        self.assertIn('<details', html)
        self.assertIn('/jira/?key=E1-O0', html)
        # на телефоне шапки таблицы нет — у каждой ячейки своя подпись
        self.assertIn('data-l="Шанс к 31.12"', html)

    def test_page_has_no_inline_scripts_and_escapes_jira_text(self):
        html = qr.render_html(approved_view(title='<img src=x onerror=alert(1)>'))
        self.assertNotIn('<img src=x', html)
        self.assertEqual([], re.findall(r'<script(?![^>]*\bsrc=)[^>]*>', html))

    def test_text_for_cpo_lists_decisions_with_ask_owner_and_date(self):
        text = qr.cpo_text(approved_view())
        lines = text.splitlines()
        self.assertEqual('Риски квартала 2026Q4 · 19.10 · до конца квартала 10 нед.', lines[0])
        self.assertIn('Нужно решение:', text)
        self.assertIn('1. GDS · KR 1.1 «Инициатива E-1» — шанс к 31.12: 0%', text)
        self.assertIn('Прошу: решение по объёму или сроку: к 31.12 с 85% успеем 20 из 60 задач · у кого: CPO · до 26.10', text)

    def test_text_without_approved_escalations_says_so(self):
        goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 6))])
        self.assertIn('Нужно решение: нет', qr.cpo_text(qm.build(goals, data)))


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        goals, data = world([epic('E-1', done_items('E1', 2) + open_items('E1', 5) +
                                  open_items('E1B', 1, status='В ожидании', bucket='blocked', changed='2026-10-13'))])
        (self.dir / 'sprint-goals.json').write_text(json.dumps({'version': 1, 'teams': goals}), encoding='utf-8')
        (self.dir / 'quarter-risks.data.json').write_text(json.dumps(data), encoding='utf-8')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir)

    def run_cli(self, *args):
        return qr.main([*args, '--reports', str(self.dir)])

    def test_render_writes_page_text_and_week_snapshot_then_shows_shift_next_week(self):
        self.assertEqual(0, self.run_cli('render', '--today', '2026-10-19'))
        for name in ('quarter-risks.html', 'quarter-risks.txt', 'quarter-risks.history/2026-10-19.json'):
            self.assertTrue((self.dir / name).is_file(), name)
        self.assertEqual(0, self.run_cli('render', '--today', '2026-10-26'))
        self.assertIn('к прошлому понедельнику', (self.dir / 'quarter-risks.html').read_text(encoding='utf-8'))

    def test_check_rejects_unknown_initiative_and_override_without_reason(self):
        bad = {'version': 1, 'generatedAt': '2026-10-19T09:00', 'teams': {'gds': {'initiatives': {
            'X-404': {'note': 'чужой эпик'}, 'E-1': {'override': {'status': 'green'}}}}}}
        (self.dir / 'quarter-risks.json').write_text(json.dumps(bad), encoding='utf-8')
        self.assertEqual(1, self.run_cli('check'))
        good = {'version': 1, 'generatedAt': '2026-10-19T09:00', 'teams': {'gds': {'initiatives': {
            'E-1': {'risks': [{'title': 'Отпуск аналитика', 'roam': 'Owned', 'owner': 'Тимлид'}]}}}}}
        (self.dir / 'quarter-risks.json').write_text(json.dumps(good), encoding='utf-8')
        self.assertEqual(0, self.run_cli('check'))


if __name__ == '__main__':
    unittest.main()
