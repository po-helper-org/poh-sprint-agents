"""Базовый сборщик: протокол, детерминизм, совпадение со старым collect.py, params.

Все прогоны идут по replay-фикстурам — без сети и без корпоративных данных.
"""
import json
import os
import sys
import unittest

import support

import validate as validate_mod

LEGACY = json.loads(support.LEGACY_GOLDEN.read_text(encoding='utf-8'))


class ProtocolTest(unittest.TestCase):
    def test_happy_path(self):
        proc = support.run_collector()
        self.assertEqual(0, proc.returncode, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual('team-a', data['slug'])
        self.assertEqual(1, data['_meta']['protocol'])
        self.assertEqual(support.NOW, data['_meta']['collectedAt'])
        self.assertGreater(data['_meta']['requests'], 0)
        self.assertEqual([], validate_mod.check(data).schema_errors)

    def test_stdout_is_exactly_one_json_object(self):
        """Логи идут в stderr: иначе runner не разберёт stdout."""
        proc = support.run_collector()
        self.assertTrue(proc.stdout.strip().startswith('{'))
        self.assertEqual(1, proc.stdout.strip().count('\n') + 1 - proc.stdout.strip().count('\n'))
        json.loads(proc.stdout)
        self.assertIn('эпиков', proc.stderr)

    def test_empty_stdin_is_config_error(self):
        import subprocess
        import sys
        proc = subprocess.run([sys.executable, str(support.BASE_COLLECTOR)], input='',
                              capture_output=True, text=True)
        self.assertEqual(2, proc.returncode)

    def test_protocol_mismatch_is_config_error(self):
        req = support.request()
        req['protocol'] = 99
        proc = support.run_collector(req=req)
        self.assertEqual(2, proc.returncode)
        self.assertIn('protocol', proc.stderr)

    def test_missing_replay_answer_is_jira_error(self):
        """Код 3 — «JIRA недоступна»: на replay это отсутствующий ответ."""
        proc = support.run_collector(replay=support.HERE / 'fixtures' / 'нет-такого-каталога')
        self.assertEqual(3, proc.returncode)
        self.assertIn('replay', proc.stderr.lower())

    def test_replay_never_touches_network(self):
        """URL заведомо несуществующий: если бы сборщик пошёл в сеть, был бы код 3."""
        req = support.request(url='https://jira.invalid.example')
        proc = support.run_collector(req=req)
        self.assertEqual(0, proc.returncode, proc.stderr)


class DeterminismTest(unittest.TestCase):
    def test_byte_identical_between_runs(self):
        """НФТ-1: одни и те же replay-данные и один now → побайтово одинаковый stdout."""
        first = support.run_collector().stdout
        second = support.run_collector().stdout
        self.assertEqual(first, second)
        self.assertEqual(0, json.loads(first)['_meta']['durationMs'],
                         'на replay длительность не измеряется — иначе байты разойдутся')

    def test_now_comes_from_request_only(self):
        """Сдвинули now — сдвинулись производные от «сейчас», а не всё подряд."""
        base = support.collect_ok()
        later = support.collect_ok(req=support.request(now='2026-09-16T17:00:00.000+0300'))
        self.assertEqual(base['epics'], later['epics'])
        self.assertNotEqual(base['control']['stories']['today'],
                            later['control']['stories']['today'])
        self.assertEqual('2026-09-16T17:00:00.000+0300', later['_meta']['collectedAt'])


def collect_in_process(dataset=None, params=None):
    """Базовый сборщик по изменённому синтетическому набору, без replay-фикстур."""
    sys.path.insert(0, str(support.HERE))
    import fake_jira
    mod = support.load_module(support.BASE_COLLECTOR, 'base_collector_inproc')
    api, _ = fake_jira.make_api(dataset)

    class Fake(mod.Jira):
        def api(self, path, **params):
            self.requests += 1
            return api(path, **params)

    req = support.request(board=fake_jira.BOARD_ID, url=fake_jira.BASE, params=params)
    collector = mod.Collector(Fake(fake_jira.BASE, 'x'), req, mod.load_rules({}))
    data = collector.collect()
    data['_meta'] = {'warnings': collector.warnings}
    return data


class LegacyParityTest(unittest.TestCase):
    """Критерий приёмки: base без params даёт то же, что старый collect.py."""

    @staticmethod
    def without_priorities(epics):
        """Приоритеты (1.1.0), объём эпика (1.2.0), дедлайн эпика (1.4.0) — новые поля; остальное как у старого сборщика."""
        out = []
        for e in epics:
            e = {k: v for k, v in e.items() if k not in ('epicPriority', 'scope', 'epicDue')}
            e['stories'] = [dict({k: v for k, v in st.items() if k not in ('priority', 'events')},
                                 subtasks=[{k: v for k, v in sub.items() if k != 'priority'}
                                           for sub in st['subtasks']])
                            for st in e['stories']]
            out.append(e)
        return out

    def test_same_as_legacy_golden(self):
        # старый сборщик считал ленту за 7 дней; с 1.5.0 по умолчанию — период спринта
        fresh = support.collect_ok(req=support.request(params={'activity_days': 7}))
        stripped = {k: v for k, v in fresh.items() if k not in ('_meta', 'statusMap', 'output')}
        stripped['logs'] = {k: v for k, v in stripped['logs'].items() if k != 'since'}
        stripped['epics'] = self.without_priorities(stripped['epics'])
        self.assertEqual(LEGACY, stripped)

    def test_epic_scope_beyond_sprint(self):
        """Весь эпик: задачи прошлых спринтов и вне спринтов, у каждой — где она была."""
        data = support.collect_ok()
        epics = [e for e in data['epics'] if e['epicKey']]
        self.assertTrue(epics and all('scope' in e for e in epics))
        in_sprint = {st['key'] for e in epics for st in e['stories']}
        for e in epics:
            keys = [i['key'] for i in e['scope']]
            self.assertEqual(len(keys), len(set(keys)), 'задача эпика дважды')
            self.assertTrue({st['key'] for st in e['stories']} <= set(keys),
                            'истории спринта входят в объём эпика')
        scope = [i for e in epics for i in e['scope']]
        self.assertTrue(any(i['sprint'] is None for i in scope), 'есть задачи вне спринтов отчёта')
        self.assertTrue(any(i['sprint'] and not i['inSprint'] for i in scope), 'есть задачи прошлых спринтов')
        for i in scope:
            self.assertEqual(i['key'] in in_sprint, i['inSprint'])
        self.assertTrue(any(i['subtasks'] for i in scope))
        # статусы объёма тоже раскладываются по бакетам — страница берёт их из statusMap
        self.assertTrue({i['status'] for i in scope} <= set(data['statusMap']))

    def test_epic_scope_can_be_switched_off(self):
        data = support.collect_ok(req=support.request(params={'epic_scope': False}))
        self.assertFalse(any('scope' in e for e in data['epics']))

    def test_priorities_on_every_level(self):
        epics = support.collect_ok()['epics']
        self.assertTrue(all(e['epicPriority'] for e in epics if e['epicKey']))
        items = [st for e in epics for st in e['stories']]
        items += [sub for st in items for sub in st['subtasks']]
        self.assertTrue(items)
        self.assertTrue(all(it['priority'] for it in items), 'у задачи нет приоритета')
        self.assertGreater(len({it['priority'] for it in items}), 2)

    def test_new_fields_are_the_only_addition(self):
        fresh = support.collect_ok()
        self.assertEqual({'_meta', 'statusMap', 'output'}, set(fresh) - set(LEGACY))

    def test_member_output_in_story_points(self):
        """Выработка участников (1.3.0): SP и задачи по статусу на конец спринта, без подзадач."""
        data = support.collect_ok()
        out = data['output']
        self.assertEqual(('SP', 'customfield_10106'), (out['unit'], out['field']))
        self.assertEqual([s['name'] for s in data['metrics']['sprints']], [s['name'] for s in out['sprints']])
        self.assertEqual([False, False, True], [s['current'] for s in out['sprints']])
        for s, vel in zip(out['sprints'], data['velocity']['sprints']):
            tasks = sum(n for m in s['members'] for n, _ in m['split'].values())
            subtasks = sum(1 for e in data['epics'] for st in e['stories'] for _ in st['subtasks']) if s['current'] else None
            self.assertLess(tasks, vel['planned'], 'подзадачи в выработку не входят')
            if subtasks is not None:
                self.assertEqual(vel['planned'] - subtasks, tasks)
            for m in s['members']:
                self.assertEqual({'open', 'blocked', 'progress', 'testing', 'review', 'done'}, set(m['split']))
        done_sp = sum(m['split']['done'][1] for m in out['sprints'][0]['members'])
        self.assertGreater(done_sp, 0)
        for who, lead in out['lead'].items():
            self.assertGreater(lead['count'], 0)

    def test_member_output_uses_status_at_sprint_end(self):
        """Задачу закрыли уже после конца спринта — в его выработке она не «готово»."""
        sys.path.insert(0, str(support.HERE))
        import fake_jira
        ds = fake_jira.Dataset()
        sprint = ds.sprints[0]
        end = sprint['endDate']
        story = next(i for i in ds.issues[sprint['id']]
                     if not i['fields']['issuetype']['subtask'] and i['fields']['status']['name'] == 'Закрыт')
        hist = story['changelog']['histories']
        last = [h for h in hist if h['items'][0]['field'] == 'status'][-1]
        late = fake_jira.datetime.fromisoformat(end) + fake_jira.timedelta(days=2)
        last['created'] = fake_jira.iso(late)
        hist.append(ds._history(99999, fake_jira.datetime.fromisoformat(end) - fake_jira.timedelta(days=1),
                                'assignee', story['fields']['assignee']['displayName'], 'Участник Ю', author='x'))
        data = collect_in_process(ds)
        members = {m['name']: m for m in data['output']['sprints'][0]['members']}
        self.assertIn('Участник Ю', members, 'исполнитель — на конец спринта')
        split = members['Участник Ю']['split']
        self.assertEqual(0, split['done'][0], 'закрыта после конца спринта — не в выработке')
        self.assertEqual(1, sum(n for n, _ in split.values()))

    def test_member_items_and_sprint_dates(self):
        """1.4.0: у участника — его задачи спринта с SP, движением статусов и комментариями."""
        data = support.collect_ok()
        out = data['output']
        for s in out['sprints']:
            self.assertRegex(s['start'], r'^\d{4}-\d{2}-\d{2}$')
            for m in s['members']:
                self.assertEqual(sum(n for n, _ in m['split'].values()), len(m['items']))
                self.assertEqual(m['split']['done'][1], sum(i['sp'] for i in m['items'] if i['bucket'] == 'done'))
        items = [i for s in out['sprints'] for m in s['members'] for i in m['items']]
        self.assertTrue(any(i['history'] for i in items))
        self.assertTrue(any(i['comments'] for i in items), 'комментарии из второго прохода по спринту')
        h = next(i['history'] for i in items if i['history'])[0]
        self.assertEqual({'at', 'from', 'to', 'by'}, set(h))

    def test_epic_due_and_scope_dates(self):
        """1.4.0: дедлайн эпика и даты задач объёма — для графика сгорания эпика."""
        data = support.collect_ok()
        epics = {e['epicKey']: e for e in data['epics'] if e['epicKey']}
        self.assertEqual('2026-10-15', epics['INIT-900']['epicDue'])
        scope = [i for e in epics.values() for i in e['scope']]
        self.assertTrue(all(i['created'] for i in scope))
        done = [i for i in scope if i['status'] == 'Закрыт']
        self.assertTrue(done and all(i['doneAt'] for i in done))
        self.assertTrue(all(i['doneAt'] is None for i in scope if i['status'] == 'Бэклог'))
        # 1.6.0: оценка задачи и даты подзадач — для сгорания по SP и по подзадачам
        self.assertTrue(any(i['sp'] for i in scope))
        subs = [sub for i in scope for sub in i['subtasks']]
        self.assertTrue(subs and all(sub['created'] for sub in subs))
        self.assertTrue(any(sub['doneAt'] for sub in subs))

    def test_no_story_points_field_counts_tasks(self):
        data = collect_in_process(params={'sp_names': ['нет такого поля']})
        self.assertEqual(('задач', None), (data['output']['unit'], data['output']['field']))
        self.assertTrue(any('Story Points не найдено' in w for w in data['_meta']['warnings']))


class ParamsTest(unittest.TestCase):
    def test_story_types_filter_table(self):
        """ФТ-15: что считать историей — настройка, а не константа в коде."""
        narrow = support.collect_ok(req=support.request(params={'story_types': ['Задача']}))
        wide = support.collect_ok()
        narrow_keys = {s['key'] for e in narrow['epics'] for s in e['stories']}
        wide_keys = {s['key'] for e in wide['epics'] for s in e['stories']}
        self.assertTrue(narrow_keys)
        self.assertFalse(narrow_keys & wide_keys)

    def test_sprints_back_changes_depth(self):
        two = support.collect_ok(req=support.request(params={'sprints_back': 2}))
        self.assertEqual(2, len(two['metrics']['sprints']))
        self.assertEqual(3, len(support.collect_ok()['metrics']['sprints']))

    def test_story_events_all_time(self):
        """1.7.0: у истории — хронология за всё время: она и её подзадачи, по времени."""
        data = support.collect_ok()
        stories = [st for e in data['epics'] for st in e['stories']]
        self.assertTrue(all(st['events'] and st['events'][0]['kind'] == 'created' for st in stories))
        for st in stories:
            at = [ev['at'] for ev in st['events']]
            self.assertEqual(sorted(at), at)
            keys = {st['key']} | {sub['key'] for sub in st['subtasks']}
            self.assertTrue({ev['key'] for ev in st['events']} <= keys)
        evs = [ev for st in stories for ev in st['events']]
        self.assertTrue(any(ev['kind'] == 'comment' for ev in evs))
        self.assertTrue(any(ev['kind'] == 'status' and ev['done'] and ev['key'] != st['key'] for st in stories for ev in st['events']),
                        'есть закрытые подзадачи')
        # окно ленты — спринт, а хронология истории — с её создания
        start = data['logs']['since']
        self.assertTrue(any(ev['at'][:10] < start for ev in evs))

    def test_activity_window_is_sprint_by_default(self):
        """1.5.0: без activity_days лента — с начала текущего спринта."""
        data = support.collect_ok()
        start = next(s['start'] for s in data['output']['sprints'] if s['current'])
        self.assertEqual(start, data['logs']['since'])
        self.assertTrue(all(e['at'][:10] >= start for e in data['logs']['events']))
        for s in data['output']['sprints']:
            for m in s['members']:
                for it in m['items']:
                    self.assertTrue(all(s['start'] <= h['at'][:10] for h in it['history']), 'история — в границах спринта')

    def test_activity_days_changes_window(self):
        wide = support.collect_ok(req=support.request(params={'activity_days': 30}))
        base = support.collect_ok()
        self.assertEqual(30, wide['logs']['days'])
        self.assertGreater(len(wide['logs']['events']), len(base['logs']['events']))

    def test_status_buckets_override(self):
        """Своя раскладка статуса попадает в statusMap и в разбивку velocity."""
        data = support.collect_ok(req=support.request(
            params={'status_buckets': {'Тестирование': 'blocked'}}))
        self.assertEqual('blocked', data['statusMap']['Тестирование'])
        base = support.collect_ok()
        self.assertEqual('testing', base['statusMap']['Тестирование'])
        moved = sum(s['split']['blocked'] for s in data['velocity']['sprints'])
        origin = sum(s['split']['blocked'] for s in base['velocity']['sprints'])
        self.assertGreater(moved, origin)

    def test_bad_bucket_in_params_is_config_error(self):
        proc = support.run_collector(req=support.request(
            params={'status_buckets': {'Ревью': 'кажется-ревью'}}))
        self.assertEqual(2, proc.returncode)
        self.assertIn('status_buckets', proc.stderr)

    def test_explicit_epic_link_field(self):
        data = support.collect_ok(req=support.request(
            params={'epic_link_field': 'customfield_10101'}))
        self.assertEqual(support.collect_ok()['epics'], data['epics'])

    def test_unknown_epic_link_field_asks_jira_for_it(self):
        """Поле из params идёт в запрос как есть: на фикстурах такого ответа нет."""
        proc = support.run_collector(req=support.request(
            params={'epic_link_field': 'customfield_99999'}))
        self.assertEqual(3, proc.returncode)
        self.assertIn('customfield_99999', proc.stderr)


class StatusMapTest(unittest.TestCase):
    def test_covers_every_status_in_data(self):
        """ФТ-18: раскладка считается один раз и приезжает вместе с данными."""
        data = support.collect_ok()
        statuses = {u['status'] for e in data['epics'] for s in e['stories']
                    for u in [s] + list(s['subtasks'])}
        self.assertTrue(statuses)
        self.assertTrue(statuses <= set(data['statusMap']))

    def test_velocity_split_agrees_with_status_map(self):
        data = support.collect_ok()
        for sprint in data['velocity']['sprints']:
            self.assertEqual(sprint['planned'], sum(sprint['split'].values()))

    def test_workflow_drift_warning(self):
        """Критерий приёмки: новый статус не уезжает молча в «В работе»."""
        data = support.collect_ok()
        warnings = ' | '.join(data['_meta']['warnings'])
        self.assertIn('Дизайн', warnings)
        self.assertIn('progress', warnings)

    def test_declaring_status_silences_drift(self):
        data = support.collect_ok(req=support.request(
            params={'status_buckets': {'Дизайн': 'progress'}}))
        self.assertNotIn('Дизайн', ' | '.join(data['_meta']['warnings']))


class TokenSafetyTest(unittest.TestCase):
    def test_token_absent_from_output(self):
        """НФТ-2: токена нет ни в stdout, ни в stderr."""
        proc = support.run_collector(env={'JIRA_PERSONAL_TOKEN': support.FAKE_TOKEN})
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertNotIn(support.FAKE_TOKEN, proc.stdout)
        self.assertNotIn(support.FAKE_TOKEN, proc.stderr)

    def test_token_absent_from_record_dump(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            # record при replay: дампы пишутся из воспроизведённых ответов
            proc = support.run_collector(args=('--record', tmp))
            self.assertEqual(0, proc.returncode, proc.stderr)
            dumps = list(Path(tmp).glob('*.json'))
            for path in dumps:
                self.assertNotIn(support.FAKE_TOKEN, path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
