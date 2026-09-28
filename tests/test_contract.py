"""Контракт: схема — источник истины по форме объекта команды (ФТ-1, ФТ-3, НФТ-7)."""
import copy
import json
import unittest

import support

import schema as schema_mod
import validate as validate_mod

SCHEMA = schema_mod.load_schema(support.CONTRACT / 'team.schema.json')


def load_example():
    return json.loads((support.SKILL / 'examples' / 'example_team.json').read_text(encoding='utf-8'))


class SchemaTest(unittest.TestCase):
    def test_example_passes(self):
        """НФТ-7: старый образец проходит схему — форма данных не сломана рефакторингом."""
        self.assertEqual([], schema_mod.validate(load_example(), SCHEMA))

    def test_example_has_no_status_map(self):
        """Объект без statusMap допустим: страница падает в classifyBucket, как раньше."""
        self.assertNotIn('statusMap', load_example())

    def test_missing_required_field_names_path(self):
        """ФТ-11: ошибка указывает JSON-путь поля, а не «данные невалидны»."""
        broken = load_example()
        del broken['metrics']['overall']['lead']
        errors = schema_mod.validate(broken, SCHEMA)
        self.assertEqual(1, len(errors))
        self.assertEqual('metrics.overall.lead', errors[0].path)
        self.assertIn('обязательное поле', errors[0].message)

    def test_wrong_type_named(self):
        broken = load_example()
        broken['epics'][0]['stories'][0]['subtasks'] = 'нет'
        errors = schema_mod.validate(broken, SCHEMA)
        self.assertTrue(any(e.path == 'epics[0].stories[0].subtasks' for e in errors), errors)

    def test_bucket_enum_enforced(self):
        broken = load_example()
        broken['statusMap'] = {'Ревью': 'не-бакет'}
        errors = schema_mod.validate(broken, SCHEMA)
        self.assertTrue(any('statusMap' in e.path for e in errors), errors)

    def test_status_rules_cover_documented_mapping(self):
        """Правила из contract/status_rules.json — те же, что описаны в status_mapping.md."""
        import buckets
        rules = buckets.load()
        cases = [('Бэклог', 'К выполнению', 'open'), ('Открыто', 'К выполнению', 'open'),
                 ('В работе', 'В работе', 'progress'), ('Дизайн', 'В работе', 'progress'),
                 ('Анализ', 'В работе', 'progress'), ('В ожидании', 'В работе', 'blocked'),
                 ('Тестирование', 'В работе', 'testing'), ('Ревью', 'В работе', 'review'),
                 ('Готово к проверке', 'К выполнению', 'review'), ('Закрыт', 'Выполнено', 'done'),
                 # ловушки подстрочного поиска из status_mapping.md
                 ('Ожидает решения КЦ', 'В работе', 'blocked'),
                 ('Аналитика завершена', 'В работе', 'progress'),
                 ('Готово к закрытию', 'В работе', 'progress')]
        for status, category, want in cases:
            with self.subTest(status=status):
                self.assertEqual(want, rules.bucket(status, category))


class LocalisedWorkflowTest(unittest.TestCase):
    """Категории «выполнено» и «в работе» — данные правил, а не строки в коде.

    На англоязычном инстансе захардкоженные «Выполнено»/«В работе» дали бы
    lead = None у всех задач: закрыто 0, пустые графики — и все инварианты при
    этом проходят, потому что нули согласованы между собой.
    """

    @staticmethod
    def issue(created, moved, closed):
        return {'key': 'EN-1', 'fields': {'created': created, 'status': {'id': '9'}},
                'changelog': {'histories': [
                    {'created': moved, 'items': [{'field': 'status', 'to': '4'}]},
                    {'created': closed, 'items': [{'field': 'status', 'to': '9'}]}]}}

    def setUp(self):
        self.collector = support.load_module(support.BASE_COLLECTOR, 'collector_for_rules')
        self.issue_data = self.issue('2026-09-01T10:00:00+03:00',
                                     '2026-09-03T10:00:00+03:00',
                                     '2026-09-05T10:00:00+03:00')

    def test_english_categories(self):
        import buckets
        rules = buckets.load()
        cats = {'4': 'In Progress', '9': 'Done'}
        lead, cycle, done_at = self.collector.lead_cycle(self.issue_data, cats, rules)
        self.assertEqual(4.0, lead)
        self.assertEqual(2.0, cycle)
        self.assertIsNotNone(done_at)

    def test_russian_categories(self):
        import buckets
        rules = buckets.load()
        cats = {'4': 'В работе', '9': 'Выполнено'}
        lead, cycle, _ = self.collector.lead_cycle(self.issue_data, cats, rules)
        self.assertEqual((4.0, 2.0), (lead, cycle))

    def test_params_can_rename_categories(self):
        """Команда со своим workflow задаёт категории в params, а не форкает сборщик."""
        import buckets
        rules = buckets.load(done_categories=['Ready for release'],
                             progress_categories=['Doing'])
        cats = {'4': 'Doing', '9': 'Ready for release'}
        lead, cycle, _ = self.collector.lead_cycle(self.issue_data, cats, rules)
        self.assertEqual((4.0, 2.0), (lead, cycle))


class DriftDetectorTest(unittest.TestCase):
    """ФТ-12.12: предупреждение на статус, не покрытый ни картой, ни правилами."""

    def team(self, collector, status, status_map):
        return {'slug': 'team-x', '_meta': {'collector': collector},
                'statusMap': status_map,
                'epics': [{'rowId': 'no-epic', 'epicKey': None, 'epicTitle': 'Без эпика',
                           'stories': [{'key': 'X-1', 'title': 'x', 'status': status,
                                        'category': 'В работе', 'subtasks': []}]}]}

    def test_base_collector_map_does_not_silence(self):
        """Карта базового сборщика выведена из тех же правил — она не аргумент."""
        warnings = validate_mod.drift_warnings(
            self.team('base', 'Дизайн', {'Дизайн': 'progress'}))
        self.assertTrue(any('Дизайн' in w for w in warnings), warnings)

    def test_custom_collector_map_silences(self):
        """Свой сборщик решает за свой workflow сам — это и есть «покрыт картой»."""
        warnings = validate_mod.drift_warnings(
            self.team('team-x', 'Дизайн', {'Дизайн': 'progress'}))
        self.assertEqual([], warnings)

    def test_custom_collector_still_warns_on_uncovered(self):
        warnings = validate_mod.drift_warnings(
            self.team('team-x', 'Дизайн', {'Другой статус': 'progress'}))
        self.assertTrue(any('Дизайн' in w for w in warnings), warnings)


class InvariantTest(unittest.TestCase):
    """ФТ-12: каждый инвариант ловит свою поломку и называет команду."""

    @classmethod
    def setUpClass(cls):
        cls.team = support.collect_ok()

    def check(self, mutate):
        data = copy.deepcopy(self.team)
        mutate(data)
        return validate_mod.check(data)

    def test_clean_data_passes_all(self):
        report = validate_mod.check(copy.deepcopy(self.team))
        self.assertTrue(report.ok, report.lines())
        self.assertEqual(validate_mod.INVARIANTS, report.passed)

    def test_2_duplicate_row_id(self):
        def mutate(d):
            d['epics'].append(dict(d['epics'][0]))
        self.assertTrue(any(n == 2 for n, _, _ in self.check(mutate).failed))

    def test_3_duplicate_issue_key(self):
        def mutate(d):
            first = d['epics'][0]['stories'][0]
            d['epics'][0]['stories'].append(dict(first))
        failed = self.check(mutate).failed
        self.assertTrue(any(n == 3 for n, _, _ in failed), failed)

    def test_4_unknown_category(self):
        def mutate(d):
            d['epics'][0]['stories'][0]['category'] = 'Неведомая'
        self.assertTrue(any(n == 4 for n, _, _ in self.check(mutate).failed))

    def test_5_status_changed_after_collected_at(self):
        def mutate(d):
            d['epics'][0]['stories'][0]['statusChanged'] = '2030-01-01T00:00:00+03:00'
        self.assertTrue(any(n == 5 for n, _, _ in self.check(mutate).failed))

    def test_6_burndown_arithmetic(self):
        def mutate(d):
            d['burndown']['days'][3]['remaining'] += 5
        self.assertTrue(any(n == 6 for n, _, _ in self.check(mutate).failed))

    def test_6_burndown_gap(self):
        def mutate(d):
            del d['burndown']['days'][2]
        self.assertTrue(any(n == 6 for n, _, _ in self.check(mutate).failed))

    def test_7_velocity_split_sum(self):
        def mutate(d):
            d['velocity']['sprints'][0]['split']['open'] += 3
        self.assertTrue(any(n == 7 for n, _, _ in self.check(mutate).failed))

    def test_8_metrics_total(self):
        def mutate(d):
            d['metrics']['overall']['total'] += 1
        self.assertTrue(any(n == 8 for n, _, _ in self.check(mutate).failed))

    def test_9_stats_out_of_range(self):
        def mutate(d):
            sprint = next(s for s in d['metrics']['sprints'] if s['points'])
            sprint['lead']['mean'] = max(sprint['points']) + 100
        self.assertTrue(any(n == 9 for n, _, _ in self.check(mutate).failed))

    def test_10_outlier_flag(self):
        def mutate(d):
            point = d['control']['stories']['points'][0]
            point['outlier'] = not point['outlier']
        self.assertTrue(any(n == 10 for n, _, _ in self.check(mutate).failed))

    def test_11_logs_order(self):
        def mutate(d):
            d['logs']['events'].reverse()
        self.assertTrue(any(n == 11 for n, _, _ in self.check(mutate).failed))

    def test_11_logs_counters(self):
        def mutate(d):
            d['logs']['kinds']['status'] = 999
        self.assertTrue(any(n == 11 for n, _, _ in self.check(mutate).failed))

    def test_12_status_map_value(self):
        """Бакет вне шести не проходит: сначала enum схемы, дальше инвариант 12."""
        def mutate(d):
            d['statusMap']['Ревью'] = 'progress-ish'
        report = self.check(mutate)
        self.assertFalse(report.ok)
        self.assertTrue(any('statusMap' in e for e in report.schema_errors), report.schema_errors)
        # тот же случай, но мимо схемы — ловит инвариант
        data = copy.deepcopy(self.team)
        data['statusMap']['Ревью'] = 'progress-ish'
        failed = validate_mod._inv_status_map(data)
        self.assertTrue(failed, 'инвариант 12 должен ругаться на бакет вне шести')

    def test_12_status_map_coverage(self):
        def mutate(d):
            d['statusMap'].pop(d['epics'][0]['stories'][0]['status'], None)
        self.assertTrue(any(n == 12 for n, _, _ in self.check(mutate).failed))

    def test_1_config_mismatch(self):
        class FakeTeam:
            slug, name, board, params = 'team-a', 'Другое название', 101, {}
        report = validate_mod.check(copy.deepcopy(self.team), cfg_team=FakeTeam())
        self.assertTrue(any(n == 1 for n, _, _ in report.failed), report.failed)

    def test_sample_is_reproducible(self):
        """ФТ-13: выборка затравлена — та же команда даёт ту же выборку."""
        first, seed = validate_mod.sample(self.team, 5)
        second, seed2 = validate_mod.sample(self.team, 5)
        self.assertEqual(seed, seed2)
        self.assertEqual([r['key'] for r in first], [r['key'] for r in second])
        self.assertEqual(5, len(first))
        text = '\n'.join(validate_mod.format_sample(first))
        self.assertIn('status=', text)


if __name__ == '__main__':
    unittest.main()
