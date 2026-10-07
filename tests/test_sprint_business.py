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

    def test_stale_hash_rejected(self):
        self.doc['teams']['platform']['dataHash'] = 'a' * 64
        errors, _ = self.check(self.doc)
        self.assertTrue(any('dataHash не совпадает' in e for e in errors), errors)

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
        self.assertIn('блок устарел (данные пересобраны): platform — /sprint-business', proc.stdout)
        teams = {t['slug']: t for t in self.ws.page_teams_of(self.ws.biz_page)}
        self.assertNotIn('business', teams['platform'])
        self.assertIn('business', teams['catalog'])

    def test_apply_refuses_bad_block(self):
        doc = self.ws.biz_example()
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
