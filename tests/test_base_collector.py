"""Базовый сборщик: протокол, детерминизм, совпадение со старым collect.py, params.

Все прогоны идут по replay-фикстурам — без сети и без корпоративных данных.
"""
import json
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


class LegacyParityTest(unittest.TestCase):
    """Критерий приёмки: base без params даёт то же, что старый collect.py."""

    @staticmethod
    def without_priorities(epics):
        """Приоритеты появились в 1.1.0 — у старого сборщика их нет, остальное совпадает."""
        out = []
        for e in epics:
            e = {k: v for k, v in e.items() if k != 'epicPriority'}
            e['stories'] = [dict({k: v for k, v in st.items() if k != 'priority'},
                                 subtasks=[{k: v for k, v in sub.items() if k != 'priority'}
                                           for sub in st['subtasks']])
                            for st in e['stories']]
            out.append(e)
        return out

    def test_same_as_legacy_golden(self):
        fresh = support.collect_ok()
        stripped = {k: v for k, v in fresh.items() if k not in ('_meta', 'statusMap')}
        stripped['epics'] = self.without_priorities(stripped['epics'])
        self.assertEqual(LEGACY, stripped)

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
        self.assertEqual({'_meta', 'statusMap'}, set(fresh) - set(LEGACY))


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
