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

    def test_7_last_sprint_is_active(self):
        def mutate(d):
            d['velocity']['sprints'].reverse()
        self.assertTrue(any(n == 7 for n, _, _ in self.check(mutate).failed))

    def test_10_points_ordered_and_with_stats(self):
        def unordered(d):
            d['control']['stories']['points'].reverse()
        self.assertTrue(any(n == 10 for n, _, _ in self.check(unordered).failed))

        def no_limit(d):
            del d['control']['stories']['limit']
        self.assertTrue(any(n == 10 and 'limit' in t for n, _, t in self.check(no_limit).failed))

    def test_13_split_matches_items(self):
        def mutate(d):
            member = next(m for s in d['output']['sprints'] for m in s['members'] if m['items'])
            member['items'].pop()
        self.assertTrue(any(n == 13 for n, _, _ in self.check(mutate).failed))

    def test_13_unit_agrees_with_field(self):
        def mutate(d):
            d['output']['field'] = None
        self.assertTrue(any(n == 13 and 'unit' in t for n, _, t in self.check(mutate).failed))

    def test_13_active_sprint_is_last(self):
        def mutate(d):
            d['output']['sprints'].reverse()
        self.assertTrue(any(n == 13 for n, _, _ in self.check(mutate).failed))

    def test_14_events_order_and_owner(self):
        def unordered(d):
            st = next(st for e in d['epics'] for st in e['stories'] if len(st.get('events') or []) > 1)
            st['events'].reverse()
        self.assertTrue(any(n == 14 for n, _, _ in self.check(unordered).failed))

        def alien(d):
            st = next(st for e in d['epics'] for st in e['stories'] if st.get('events'))
            st['events'][-1]['key'] = 'ЧУЖАЯ-1'
        self.assertTrue(any(n == 14 and 'чужих' in t for n, _, t in self.check(alien).failed))

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


# ------------------------------------------------------------- согласованность контракта

DATA_SKILL = support.ROOT / '.claude' / 'skills' / 'sprint-data'
OVERLAYS = {'notes', 'insights', 'business', '_comment'}
FULL_EXAMPLE = support.SKILL / 'examples' / 'example_team_full.json'


def schema_paths(node=None, prefix='', root=None):
    """Пути всех полей схемы: «a.b», «a[].b». stats — одна запись (поля описаны отдельно),
    карты (additionalProperties) — до самой карты."""
    root = root or SCHEMA
    node = node if node is not None else SCHEMA
    if '$ref' in node:
        if node['$ref'] == '#/definitions/stats':
            return
        node = schema_mod._resolve(node['$ref'], root)
    for name, sub in (node.get('properties') or {}).items():
        path = f'{prefix}.{name}' if prefix else name
        yield path
        target = schema_mod._resolve(sub['$ref'], root) if '$ref' in sub else sub
        if target.get('type') == 'array' or 'items' in target:
            items = target.get('items') or {}
            if isinstance(items, dict) and (items.get('properties') or '$ref' in items):
                yield from schema_paths(items, path + '[]', root)
        elif sub.get('$ref') != '#/definitions/stats':
            yield from schema_paths(sub, path, root)


def data_paths(node, prefix=''):
    """Пути всех полей, которые реально есть в данных (карты-словари — до самой карты)."""
    if isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                yield from data_paths(item, prefix + '[]')
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        path = f'{prefix}.{key}' if prefix else key
        yield path
        if isinstance(value, (dict, list)):
            yield from data_paths(value, path)


def declared(path, known):
    """Путь объявлен в схеме: сам или внутри объявленной карты (statusMap, split, lead, stats…)."""
    path = path[:-2] if path.endswith('[]') else path
    path = path[:-2] if path.endswith('.*') else path
    return path in known or any(path.startswith(m + '.') for m in MAPS if m in known)


MAPS = {'statusMap', 'logs.kinds', 'velocity.sprints[].split', 'output.lead',
        'output.sprints[].members[].split', 'output.sprints[].timeInStatus', 'metrics.sprints[].lead',
        'metrics.sprints[].cycle', 'metrics.sprints[].leadStory', 'metrics.sprints[].leadTask',
        'metrics.overall.lead', 'metrics.overall.cycle', 'metrics.overall.leadStory', 'metrics.overall.leadTask'}


def doc_paths(text):
    """Пути полей, названные в справочнике: полные `a.b[].c` и относительные `.d` в той же
    строке («`x.y.a` / `.b`» — это x.y.a и x.y.b)."""
    import re
    out = set()
    for line in text.splitlines():
        last = None
        for tok in re.findall(r'`([^`]+)`', line):
            if re.fullmatch(r'\.[A-Za-z_]+', tok) and last:
                out.add(last.rsplit('.', 1)[0] + tok)
            elif re.fullmatch(r'[A-Za-z_]+(\[\])?(\.[A-Za-z_*]+(\[\])?)*', tok):
                out.add(tok)
                last = tok
    return out


class ContractConsistencyTest(unittest.TestCase):
    """Схема, справочник полей, образец, демо и базовый сборщик описывают одно и то же."""

    @classmethod
    def setUpClass(cls):
        cls.known = set(schema_paths())
        cls.full = {k: v for k, v in json.loads(FULL_EXAMPLE.read_text(encoding='utf-8')).items()
                    if k not in OVERLAYS}
        cls.fields = (DATA_SKILL / 'reference' / 'fields.md').read_text(encoding='utf-8')

    def undeclared(self, team):
        return sorted({p for p in data_paths({k: v for k, v in team.items() if k not in OVERLAYS})
                       if not declared(p, self.known)})

    def test_full_example_passes_schema_and_invariants(self):
        report = validate_mod.check(copy.deepcopy(self.full))
        self.assertTrue(report.ok, report.lines())

    def test_full_example_covers_every_screen(self):
        gaps = [r for r in validate_mod.coverage(self.full) if r[2] != 'есть']
        self.assertEqual([], gaps)

    def test_full_example_has_every_schema_field(self):
        """Полный образец — правда полный: в нём есть каждое поле схемы."""
        given = set(data_paths(self.full))
        missing = sorted(p for p in self.known if p not in given and p != '_meta.sha' and p not in OVERLAYS)
        self.assertEqual([], missing)

    def test_every_emitted_field_is_declared(self):
        """Всё, что отдают базовый сборщик, демо-данные и образец, объявлено в схеме:
        страница не читает полей, которых нет в контракте."""
        demo = support.load_module(support.SKILL / 'scripts' / 'demo_data.py', 'demo_data_contract')
        import random
        teams = [demo.build_team(spec, random.Random(demo.SEED), demo.Keys()) for spec in demo.TEAMS[:1]]
        for name, team in (('образец', self.full), ('демо', teams[0]), ('базовый сборщик', support.collect_ok())):
            with self.subTest(name):
                self.assertEqual([], self.undeclared(team))

    def test_reference_describes_every_schema_field(self):
        """Каждое поле схемы описано в sprint-data/reference/fields.md."""
        named = {p.replace('control.subtasks.', 'control.stories.') for p in doc_paths(self.fields)}
        # контейнер описан своими полями: «epics[].rowId» описывает и сам epics
        described = lambda p: p in named or any(n.startswith(p + '.') or n.startswith(p + '[]') for n in named)  # noqa: E731
        missing = sorted(p for p in self.known
                         if not described(p.replace('control.subtasks.', 'control.stories.')))
        self.assertEqual([], missing)

    def test_reference_names_only_real_fields(self):
        """И наоборот: справочник не описывает полей, которых нет в схеме (опечатки, старьё)."""
        tops = {p.split('.')[0].split('[')[0] for p in self.known} - OVERLAYS
        named = [p for p in doc_paths(self.fields) if p.split('.')[0].split('[')[0] in tops]
        stray = sorted(p for p in named if not declared(p, self.known))
        self.assertEqual([], stray)

    def test_render_map_names_every_covered_screen(self):
        """Покрытие экранов (validate.COVERAGE) и render.md говорят об одних экранах."""
        render = (DATA_SKILL / 'reference' / 'render.md').read_text(encoding='utf-8')
        missing = [screen for _, screen, _, _ in validate_mod.COVERAGE if screen not in render]
        self.assertEqual([], missing)
        for _, _, paths, _ in validate_mod.COVERAGE:
            for path in paths:
                with self.subTest(path):
                    self.assertTrue(declared(path, self.known), path)

    def test_example_is_generated(self):
        """Образец собирается из демо-данных: правка демо без перегенерации образца — ошибка."""
        demo = support.load_module(support.SKILL / 'scripts' / 'demo_data.py', 'demo_data_example')
        import random
        rnd = random.Random(demo.SEED)
        keys = demo.Keys()
        teams = [demo.build_team(spec, rnd, keys) for spec in demo.TEAMS]
        want = json.loads(json.dumps(demo.example_team(teams[0]), ensure_ascii=False))
        got = json.loads(FULL_EXAMPLE.read_text(encoding='utf-8'))
        self.assertEqual(want, got, 'перегенерируйте: demo_data.py --example examples/example_team_full.json')
