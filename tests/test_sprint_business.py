"""/sprint-business: бизнес-отчёт «ФАКТ | спринт» — отдельный навык на тех же данных.

Проверяется обвязка вокруг агента: business.py check не пускает на страницу чужие
эпики и истории, устаревший хеш, длинный для слайда текст; render собирает
sprint-business.html из того же снимка, что у отчёта PO, и прикладывает блок
только к своим данным. Всё на демо-данных, без сети.
"""
import json
import re
import subprocess
import sys
import unittest

import support
from test_sprint_insights import Workspace

BUSINESS_DIR = support.ROOT / '.claude' / 'skills' / 'sprint-business'
BUSINESS = BUSINESS_DIR / 'business.py'
EXAMPLE = BUSINESS_DIR / 'examples' / 'demo-business.json'

import build as build_mod  # noqa: E402

sys.path.insert(0, str(BUSINESS_DIR))
import business as business_mod  # noqa: E402


class BizWorkspace(Workspace):
    def __init__(self):
        super().__init__()
        self.biz_file = self.dir / 'reports' / 'sprint-business.json'
        self.biz_page = self.dir / 'reports' / 'sprint-business.html'

    def bcli(self, *args):
        return subprocess.run([sys.executable, str(BUSINESS), '--config', str(self.config), *args],
                              capture_output=True, text=True, cwd=str(self.dir), timeout=120)

    def biz_example(self):
        doc = json.loads(EXAMPLE.read_text(encoding='utf-8'))
        by_slug = {t['slug']: t for t in self.teams}
        for slug, entry in doc['teams'].items():
            entry['dataHash'] = build_mod.team_digest(by_slug[slug])
        return doc

    def page_teams_of(self, path):
        html = path.read_text(encoding='utf-8')
        return json.loads(re.search(r'var TEAMS = (\[.*?\]);\n', html, re.S).group(1))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.ws = BizWorkspace()
        self.addCleanup(self.ws.cleanup)
        self.doc = self.ws.biz_example()

    def check(self, doc):
        return business_mod.check(doc, self.ws.teams)

    def test_example_passes_clean(self):
        self.assertEqual(([], []), self.check(self.doc))

    def test_plans_checked(self):
        """«Планы на следующий спринт»: четыре колонки, короткие карточки, ключи — из данных."""
        plans = self.doc['teams']['platform']['plans']
        self.assertEqual(['take', 'finish', 'maybe', 'escalate'], list(plans))
        plans['escalate'][0]['keys'] = ['INIT-55555']
        plans['take'][0]['text'] = 'Очень длинно. ' * 20
        plans['maybe'][0]['keys'] = ['INIT-66666']
        errors, _ = self.check(self.doc)
        self.assertTrue(any('plans.escalate #1: задачи INIT-55555' in e for e in errors), errors)
        self.assertTrue(any('plans.take #1.text: длиннее 160' in e for e in errors), errors)
        self.assertTrue(any('plans.maybe #1: задачи INIT-66666' in e for e in errors), errors)
        plans['later'] = []
        errors, _ = self.check(self.doc)
        self.assertTrue(any(e.startswith('схема:') for e in errors), errors)

    def test_roadmap_checked(self):
        """Роадмап: строка — эпик команды или своя строка с названием; фазы — из словаря, 6 недель."""
        rm = self.doc['teams']['platform']['roadmap']
        self.assertEqual(([], []), self.check(self.doc))
        rm['rows'].append({'epic': 'INIT-55555', 'cells': ['бек']})
        rm['rows'].append({'cells': ['qa']})
        errors, _ = self.check(self.doc)
        self.assertTrue(any('roadmap #5: эпика INIT-55555 нет' in e for e in errors), errors)
        self.assertTrue(any('roadmap #6: нужен epic' in e for e in errors), errors)
        rm['rows'] = [{'epic': 'INIT-101', 'cells': ['бек'] * 7}]
        errors, _ = self.check(self.doc)
        self.assertTrue(any(e.startswith('схема:') for e in errors), errors)
        rm['rows'] = [{'epic': 'INIT-101', 'cells': ['кодинг']}]
        errors, _ = self.check(self.doc)
        self.assertTrue(any(e.startswith('схема:') for e in errors), errors)

    def test_risk_kind_checked(self):
        """«Риски и проблемы»: метка — external / resource / general / deadline, без метки — можно."""
        risks = self.doc['teams']['platform']['risks']
        risks[0]['kind'] = 'внешнее'
        errors, _ = self.check(self.doc)
        self.assertTrue(any(e.startswith('схема:') for e in errors), errors)
        risks[0].pop('kind')
        self.assertEqual(([], []), self.check(self.doc))

    def test_stream_summary_checked(self):
        """Строка = эпик: сводка «итог · блокер · след. шаг» — под длину слайда, ключи из данных."""
        s = self.biz()['streams']['INIT-125']
        s['done'] = 'Очень длинно. ' * 20
        s['blocker'] = 'Ждём INIT-55555 у смежников.'
        errors, _ = self.check(self.doc)
        self.assertTrue(any('streams.INIT-125.done: длиннее 180' in e for e in errors), errors)
        self.assertTrue(any('streams.INIT-125.blocker' in e and 'INIT-55555' in e for e in errors), errors)

    def test_po_readiness(self):
        """Готовность по оценке PO — целое 0..100, только у направления."""
        self.biz()['streams']['INIT-125']['readiness'] = 80
        self.assertEqual(([], []), self.check(self.doc))
        self.biz()['streams']['INIT-125']['readiness'] = 120
        errors, _ = self.check(self.doc)
        self.assertTrue(any(e.startswith('схема:') for e in errors), errors)

    def test_no_epic_row(self):
        """«Вне эпиков» — своя строка со сводкой, но без цели и KR."""
        self.biz()['streams']['no-epic'] = {'done': 'Вне эпиков: мелкие доработки закрыты.', 'next': 'разобрать на планировании'}
        self.assertEqual(([], []), self.check(self.doc))
        self.biz()['streams']['no-epic']['kr'] = 'KR 1.1 — заказы от партнёров без ручного ввода'
        errors, _ = self.check(self.doc)
        self.assertTrue(any('у строки «Вне эпиков» нет цели и KR' in e for e in errors), errors)

    def test_changes_and_demo_still_accepted(self):
        """Слайды «Изменения» и «Демо» убраны, но старые блоки с этими полями проходят проверку."""
        self.biz()['changes'] = [{'affected': 'Нагрузочный прогон', 'before': 'в этом спринте', 'after': 'ждёт стенд'}]
        self.biz()['demo'] = [{'what': 'Дашборд метрик загрузчика'}]
        self.assertEqual(([], []), self.check(self.doc))

    def test_stale_hash_only_warns(self):
        # observe пересобирает снимок несколько раз в день: блок по прошлому снимку не брак,
        # ключи и числа всё равно сверяются с текущим
        self.doc['teams']['platform']['dataHash'] = 'a' * 64
        errors, warnings = self.check(self.doc)
        self.assertEqual([], errors)
        self.assertTrue(any('по прошлому снимку' in w for w in warnings), warnings)

    def biz(self, slug='platform'):
        return self.doc['teams'][slug]

    def test_streams_only_for_team_epics(self):
        self.biz()['streams']['INIT-999'] = {'verdict': 'достигнут'}
        errors, _ = self.check(self.doc)
        self.assertTrue(any('эпика INIT-999 нет в спринте команды' in e for e in errors), errors)

    def test_rows_only_for_sprint_stories(self):
        self.biz()['rows']['INIT-101'] = {'next': 'это эпик, а не история'}
        errors, _ = self.check(self.doc)
        self.assertTrue(any('истории INIT-101 нет в спринте команды' in e for e in errors), errors)

    def test_okr_and_risk_numbers_not_checked(self):
        """Цели OKR, риски и договорённости — из документов PO: их числа с фактами спринта не сверить."""
        self.biz()['streams']['INIT-101']['kr'] = 'KR 7.4 — +15% конверсии партнёрских заказов'
        self.biz()['objectives']['OBJ 1'] = 'Удвоить партнёрские продажи к 2027'
        self.biz()['risks'][0]['text'] = 'Коммитмент на 30 сентября: 15 партнёров на новом API, сдвиг на Q4.'
        errors, warnings = self.check(self.doc)
        self.assertEqual(([], []), (errors, warnings))

    def test_texts_fit_the_slide(self):
        self.biz()['rows']['INIT-132']['next'] = 'Очень длинно. ' * 20
        errors, _ = self.check(self.doc)
        self.assertTrue(any('[platform] rows.INIT-132.next: длиннее 100' in e for e in errors), errors)

    def test_row_numbers_and_keys_checked(self):
        self.biz()['rows']['INIT-136']['done'] = 'Готово 913.4% — выдумка про INIT-55555.'
        errors, warnings = self.check(self.doc)
        self.assertTrue(any('INIT-55555' in e for e in errors), errors)
        self.assertTrue(any('числа 913.4' in w for w in warnings), warnings)

    def test_verdict_is_fixed(self):
        self.biz()['streams']['INIT-125']['verdict'] = 'почти'
        errors, _ = self.check(self.doc)
        self.assertTrue(any(e.startswith('схема:') for e in errors), errors)

    def test_obj_must_be_named(self):
        self.biz()['streams']['INIT-101']['obj'] = 'OBJ 9'
        _, warnings = self.check(self.doc)
        self.assertTrue(any('цели OBJ 9 нет в objectives' in w for w in warnings), warnings)

    def test_old_row_format_rejected(self):
        self.biz()['rows']['INIT-136'] = {'facts': ['старый формат']}
        errors, _ = self.check(self.doc)
        self.assertTrue(any(e.startswith('схема:') for e in errors), errors)

    def test_okr_needs_source(self):
        del self.biz()['goalsSource']
        _, warnings = self.check(self.doc)
        self.assertTrue(any('goalsSource' in w for w in warnings), warnings)

    def test_epic_facts_for_business(self):
        f = business_mod.ins.facts(self.ws.teams, 'platform')['teams'][0]
        team = self.ws.teams[0]
        self.assertEqual([e['epicKey'] for e in team['epics'] if e.get('epicKey')], [e['key'] for e in f['epics']])
        for e, raw in zip(f['epics'], [e for e in team['epics'] if e.get('epicKey')]):
            self.assertEqual(len(raw.get('scope') or []), e['scopeTotal'])



class PageTest(unittest.TestCase):
    def setUp(self):
        self.ws = BizWorkspace()
        self.addCleanup(self.ws.cleanup)

    def test_apply_writes_business_page_from_same_snapshot(self):
        self.ws.biz_file.write_text(json.dumps(self.ws.biz_example(), ensure_ascii=False), encoding='utf-8')
        proc = self.ws.bcli('apply')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn('цели и формулировки агента: platform, catalog', proc.stdout)
        self.assertFalse(self.ws.page.exists(), 'отчёт PO не трогается: генерация раздельная')
        teams = {t['slug']: t for t in self.ws.page_teams_of(self.ws.biz_page)}
        self.assertEqual('OBJ 1', teams['platform']['business']['streams']['INIT-101']['obj'])
        self.assertNotIn('dataHash', teams['platform']['business'])
        self.assertNotIn('business', teams['mobile'])
        for slug, t in teams.items():
            self.assertEqual(build_mod.team_digest(next(x for x in self.ws.teams if x['slug'] == slug)),
                             build_mod.team_digest(t), 'данные те же, что в снимке')
        html = self.ws.biz_page.read_text(encoding='utf-8')
        self.assertIn('id="techBtn"', html)
        self.assertNotIn('id="tableBody"', html)

    def test_render_without_block_and_with_stale_block(self):
        proc = self.ws.bcli('render')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn('блока агента нет', proc.stdout)
        doc = self.ws.biz_example()
        doc['teams']['platform']['dataHash'] = 'b' * 64
        self.ws.biz_file.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
        proc = self.ws.bcli('render')
        self.assertIn('тексты по прошлому снимку: platform — /sprint-business освежит', proc.stdout)
        teams = {t['slug']: t for t in self.ws.page_teams_of(self.ws.biz_page)}
        # пересбор данных не стирает цели, KR и формулировки: колода не «теряет» направления
        self.assertEqual(doc['teams']['platform']['objectives'], teams['platform']['business']['objectives'])
        self.assertEqual('OBJ 1', teams['platform']['business']['streams']['INIT-101']['obj'])
        self.assertIn('objectives', teams['catalog']['business'])

    def test_roster_survives_stale_block(self):
        # состав команды, скрытые ключи и эскалация от снимка не зависят: блок устарел
        # (observe пересобрал данные) — [EXT] на «Участниках» всё равно размечен
        doc = self.ws.biz_example()
        doc['teams']['platform'].update(dataHash='b' * 64, members=['Иванов Иван'], hide=['INIT-1'], escalation='Петров')
        doc['jiraNative'] = '/jira/?key={key}'
        self.ws.biz_file.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
        # кэш целей рядом с блоком: команды без блока берут состав оттуда
        (self.ws.biz_file.parent / 'sprint-goals.json').write_text(json.dumps(
            {'version': 1, 'teams': {'mobile': {'members': ['Сидоров Сидор']}}}, ensure_ascii=False), encoding='utf-8')
        proc = self.ws.bcli('render')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn('тексты по прошлому снимку: platform', proc.stdout)
        teams = {t['slug']: t for t in self.ws.page_teams_of(self.ws.biz_page)}
        biz = teams['platform']['business']
        self.assertEqual((['Иванов Иван'], 'Петров', '/jira/?key={key}'), (biz['members'], biz['escalation'], biz['jiraNative']))
        self.assertEqual([], biz['hide'], 'INIT-1 нет в спринте — из hide отсеян')
        self.assertIn('objectives', biz)
        self.assertEqual({'members': ['Сидоров Сидор'], 'jiraNative': '/jira/?key={key}'}, teams['mobile']['business'])
        self.assertIn('objectives', teams['catalog']['business'], 'свежий блок — целиком')
        for slug, t in teams.items():
            self.assertEqual(build_mod.team_digest(next(x for x in self.ws.teams if x['slug'] == slug)),
                             build_mod.team_digest(t), 'данные те же, что в снимке')

    def test_apply_refuses_bad_block(self):
        self.ws.biz_file.write_text(json.dumps(self.ws.biz_example(), ensure_ascii=False), encoding='utf-8')
        self.assertEqual(0, self.ws.bcli('apply').returncode)
        self.ws.biz_page.unlink()
        doc = json.loads(self.ws.biz_file.read_text(encoding='utf-8'))
        doc['teams']['platform']['rows']['INIT-99999'] = {'next': 'выдумка'}
        self.ws.biz_file.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
        proc = self.ws.bcli('apply')
        self.assertEqual(1, proc.returncode)
        self.assertIn('бизнес-блок не принят', proc.stdout)
        self.assertFalse(self.ws.biz_page.exists())

    def test_facts_are_the_shared_facts(self):
        proc = self.ws.bcli('facts')
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual(self.ws.facts()['teams'][0]['dataHash'], json.loads(proc.stdout)['teams'][0]['dataHash'])

    def test_insights_no_longer_carry_business(self):
        schema = json.loads((support.CONTRACT / 'insights.schema.json').read_text(encoding='utf-8'))
        self.assertNotIn('business', schema['definitions']['team']['properties'])
        demo = json.loads((support.ROOT / '.claude' / 'skills' / 'sprint-insights' / 'examples' / 'demo-insights.json')
                          .read_text(encoding='utf-8'))
        self.assertFalse(any('business' in t for t in demo['teams'].values()))

    def test_skill_and_command(self):
        skill = (BUSINESS_DIR / 'SKILL.md').read_text(encoding='utf-8')
        self.assertTrue(skill.startswith('---\nname: sprint-business\n'))
        for step in ('business.py facts', 'business.py apply', 'sprint-report.data.json', 'Для техлидов', 'goalsSource'):
            self.assertIn(step, skill)
        cmd = (support.ROOT / '.claude' / 'commands' / 'sprint-business.md').read_text(encoding='utf-8')
        self.assertIn('business.py apply', cmd)


if __name__ == '__main__':
    unittest.main()


class RiskNotesTest(unittest.TestCase):
    """«Риски и проблемы»: строки — из данных, комментарий агента — risk-put, привязан к состоянию задачи."""

    def setUp(self):
        self.ws = BizWorkspace()
        self.addCleanup(self.ws.cleanup)
        self.notes = self.ws.dir / 'reports' / 'sprint-risk-notes.json'

    def todo(self, *args):
        p = self.ws.bcli('risk-todo', *args)
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        return json.loads(p.stdout)['teams']

    def put(self, slug, draft):
        f = self.ws.dir / 'draft.json'
        f.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
        return self.ws.bcli('risk-put', '--team', slug, '--author', 'po-test', '--file', str(f))

    def blocked_row(self):
        for slug, rows in self.todo().items():
            for r in rows:
                if r['kind'] == 'blocked':
                    return slug, r
        self.fail('в демо-данных нет заблокированной истории')

    def test_todo_lists_blocked_stories_and_dated_epics(self):
        rows = [r for rs in self.todo().values() for r in rs]
        self.assertTrue(any(r['kind'] == 'blocked' and r['sig'].startswith(r['status'] + '@') for r in rows))
        self.assertTrue(all(r['note'] is None for r in rows))

    def test_put_then_render_attaches_notes(self):
        slug, row = self.blocked_row()
        p = self.put(slug, {row['key']: 'Ждём доступ от смежной команды. Нужно согласовать до пятницы.'})
        self.assertEqual(0, p.returncode, p.stdout)
        doc = json.loads(self.notes.read_text(encoding='utf-8'))
        self.assertEqual(row['sig'], doc['teams'][slug]['notes'][row['key']]['sig'])
        self.assertNotIn(row['key'], [r['key'] for r in self.todo('--team', slug)[slug]])
        self.assertEqual(0, self.ws.bcli('render').returncode)
        team = next(t for t in self.ws.page_teams_of(self.ws.biz_page) if t['slug'] == slug)
        self.assertEqual('po-test', team['business']['riskNotesBy'])
        self.assertIn(row['key'], team['business']['riskNotes'])

    def test_put_rejects_long_text_extra_sentences_and_foreign_keys(self):
        slug, row = self.blocked_row()
        for draft in ({row['key']: 'а' * 241}, {row['key']: 'Раз. Два. Три. Четыре.'}, {'NOPE-1': 'Ждём.'}):
            p = self.put(slug, draft)
            self.assertEqual(1, p.returncode, p.stdout)
            self.assertIn('не приняты', p.stdout)
        self.assertFalse(self.notes.exists())


class LayersTest(unittest.TestCase):
    """Версии блока: запись агента — слой с тем, что он поменял; итог — наложение по хронологии."""

    def setUp(self):
        self.ws = BizWorkspace()
        self.addCleanup(self.ws.cleanup)

    def write(self, doc):
        self.ws.biz_file.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')

    def read(self):
        return json.loads(self.ws.biz_file.read_text(encoding='utf-8'))

    def apply(self, doc):
        self.write(doc)
        proc = self.ws.bcli('apply')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        return proc

    def page_biz(self, slug='platform'):
        return {t['slug']: t for t in self.ws.page_teams_of(self.ws.biz_page)}[slug]['business']

    def test_first_apply_is_v1_and_block_carries_revision(self):
        proc = self.apply(self.ws.biz_example())
        self.assertIn('версия v0001', proc.stdout)
        self.assertEqual(1, self.read()['revision'])
        self.assertTrue((self.ws.biz_file.parent / 'sprint-business.versions' / 'v0001.json').is_file())

    def test_concurrent_writers_do_not_clobber(self):
        # оба прочитали v1; первый поправил итог INIT-101, второй — следующий шаг INIT-111
        self.apply(self.ws.biz_example())
        base = self.read()
        a, b = json.loads(json.dumps(base)), json.loads(json.dumps(base))
        a['teams']['platform']['streams']['INIT-101']['done'] = 'Правка PO: итог для комитета.'
        a['author'] = 'PO'
        b['teams']['platform']['streams']['INIT-111']['next'] = 'выпуск в четверг'
        b['author'] = 'PO-агент'
        self.apply(a)
        proc = self.apply(b)
        self.assertNotIn('перекрыта', proc.stdout, 'поля разные — конфликта нет')
        streams = self.page_biz()['streams']
        self.assertEqual('Правка PO: итог для комитета.', streams['INIT-101']['done'], 'вторая запись не затёрла первую')
        self.assertEqual('выпуск в четверг', streams['INIT-111']['next'])
        self.assertEqual(3, self.read()['revision'])

    def test_same_field_later_wins_with_warning(self):
        self.apply(self.ws.biz_example())
        base = self.read()
        a, b = json.loads(json.dumps(base)), json.loads(json.dumps(base))
        a['teams']['platform']['streams']['INIT-101']['done'] = 'Версия A.'
        a['author'] = 'PO'
        b['teams']['platform']['streams']['INIT-101']['done'] = 'Версия B.'
        self.apply(a)
        proc = self.apply(b)
        self.assertIn('перекрыта правка v2 (PO)', proc.stdout)
        self.assertEqual('Версия B.', self.page_biz()['streams']['INIT-101']['done'])

    def test_removal_needs_known_base(self):
        self.apply(self.ws.biz_example())
        doc = self.read()
        del doc['teams']['platform']['streams']['INIT-101']['shown']
        self.apply(doc)
        self.assertNotIn('shown', self.page_biz()['streams']['INIT-101'], 'с revision удаление — правка')
        partial = {'version': 1, 'generatedAt': '2026-11-04T21:00:00+03:00', 'author': 'агент команды',
                   'teams': {'catalog': {'dataHash': self.read()['teams']['catalog']['dataHash'],
                                         'objectives': {'OBJ 9': 'Новая цель каталога'}}}}
        proc = self.apply(partial)
        self.assertIn('нет revision', proc.stdout)
        self.assertIn('objectives', self.page_biz('platform'), 'запись без базы чужое не стирает')
        self.assertEqual('Новая цель каталога', self.page_biz('catalog')['objectives']['OBJ 9'])
        self.assertIn('INIT-208', self.page_biz('catalog')['streams'], 'и своё не стирает')

    def test_refused_write_leaves_history_and_deck(self):
        self.apply(self.ws.biz_example())
        doc = self.read()
        doc['teams']['platform']['rows']['INIT-99999'] = {'next': 'выдумка'}
        doc['teams']['platform']['streams']['INIT-101']['done'] = 'не должно попасть'
        self.write(doc)
        proc = self.ws.bcli('apply')
        self.assertEqual(1, proc.returncode)
        self.assertNotIn('не должно попасть', json.dumps(self.page_biz(), ensure_ascii=False))
        self.ws.bcli('render')   # пересборка на «свежих» читает историю, а не черновик в файле
        self.assertNotIn('не должно попасть', json.dumps(self.page_biz(), ensure_ascii=False))

    def test_apply_draft_layers_onto_main_block(self):
        """Правка PO из виджета: запись — в черновике, версия и итог — у основного блока; автор — из черновика."""
        self.apply(self.ws.biz_example())
        draft = json.loads(json.dumps(self.read()))
        draft['teams']['platform']['streams']['INIT-101']['done'] = 'Правка PO на слайде.'
        draft['author'] = 'PO'
        draft_file = self.ws.dir / 'own' / 'po-edit.json'
        draft_file.parent.mkdir()
        draft_file.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
        before = draft_file.read_text(encoding='utf-8')
        proc = self.ws.bcli('check', '--draft', str(draft_file))
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn('полей изменено 1', proc.stdout)
        proc = self.ws.bcli('apply', '--draft', str(draft_file))
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn('версия v0002: полей изменено 1', proc.stdout)
        v2 = json.loads((self.ws.biz_file.parent / 'sprint-business.versions' / 'v0002.json').read_text(encoding='utf-8'))
        self.assertEqual('PO', v2['author'])
        self.assertEqual([[['teams', 'platform', 'streams', 'INIT-101', 'done'], 'Правка PO на слайде.']], v2['patch'])
        block = self.read()
        self.assertEqual((2, 'PO'), (block['revision'], block['author']), 'итог пересобран в основном файле')
        self.assertEqual('Правка PO на слайде.', block['teams']['platform']['streams']['INIT-101']['done'])
        self.assertEqual('Правка PO на слайде.', self.page_biz()['streams']['INIT-101']['done'])
        self.assertEqual(before, draft_file.read_text(encoding='utf-8'), 'черновик не тронут')
        self.assertFalse((draft_file.parent / 'po-edit.versions').exists(), 'истории у черновика нет')

    def test_history_lists_versions(self):
        self.apply(self.ws.biz_example())
        proc = self.ws.bcli('history')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertRegex(proc.stdout, r'v0001 .* база v0000 .*platform')

    def test_layers_unit(self):
        import layers
        flat = layers.flatten({'jiraNative': 'x{key}', 'teams': {'t': {'objectives': {'OBJ 1': 'a'},
                               'streams': {'E-1': {'done': 'd', 'obj': 'OBJ 1'}}, 'hide': ['E-2']}}})
        self.assertEqual('d', flat[('teams', 't', 'streams', 'E-1', 'done')])
        self.assertEqual(['E-2'], flat[('teams', 't', 'hide')])
        self.assertEqual(flat, layers.flatten(layers.unflatten(flat)))

    def test_first_apply_drops_rows_of_past_sprints(self):
        # блок до версий ссылается на эпики и истории прошлого спринта — первая запись не отказывает
        doc = self.ws.biz_example()
        doc['teams']['platform']['rows']['INIT-99999'] = {'next': 'из прошлого спринта'}
        doc['teams']['platform']['plans']['take'][0]['keys'] = ['INIT-99997']
        doc['teams']['platform']['roadmap']['rows'].append({'epic': 'INIT-99996', 'cells': ['бек', 'бек', 'бек', 'qa', 'приёмка', '']})
        proc = self.apply(doc)
        self.assertIn('на колоду не идут: platform:INIT-99999', proc.stdout)
        self.assertNotIn('INIT-99999', self.page_biz()['rows'])
        doc = self.read()
        doc['teams']['platform']['rows']['INIT-99998'] = {'next': 'выдумка'}
        self.write(doc)
        self.assertEqual(1, self.ws.bcli('apply').returncode, 'дальше — ошибка, как раньше')
