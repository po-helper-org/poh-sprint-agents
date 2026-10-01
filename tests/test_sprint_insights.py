"""/sprint-insights: интерпретация графиков от ИИ — отдельный конвейер поверх снимка данных.

Проверяется детерминированная обвязка вокруг агента: facts считает те же числа, что
лежат в данных; check не пускает на страницу чужие ключи задач, устаревший хеш и
сломанную форму, а выдуманные числа помечает; render встраивает только инсайды,
написанные по этим же данным. Всё на демо-данных, без сети.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support

INSIGHTS_DIR = support.ROOT / '.claude' / 'skills' / 'sprint-insights'
INSIGHTS = INSIGHTS_DIR / 'insights.py'
EXAMPLE = INSIGHTS_DIR / 'examples' / 'demo-insights.json'
DEMO = support.SKILL / 'scripts' / 'demo_data.py'
RUN = support.RUNNER / 'run.py'

import build as build_mod  # noqa: E402

sys.path.insert(0, str(INSIGHTS_DIR))
import insights as insights_mod  # noqa: E402


class Workspace:
    """Проект без JIRA: снимок из демо-генератора и конфиг на базовом сборщике."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix='sprint-insights-'))
        reports = self.dir / 'reports'
        reports.mkdir()
        self.data = reports / 'sprint-report.data.json'
        proc = subprocess.run([sys.executable, str(DEMO), '--out', str(self.data)],
                              capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        self.teams = json.loads(self.data.read_text(encoding='utf-8'))
        cfg = 'version = 1\noutput = "./reports/sprint-report.html"\n'
        for t in self.teams:
            cfg += (f'\n[[teams]]\nslug = "{t["slug"]}"\nname = "{t["team"]}"\n'
                    f'board = {t["boardId"]}\ncollector = "base"\n')
        self.config = self.dir / 'sprint-report.config.toml'
        self.config.write_text(cfg, encoding='utf-8')
        self.insights = reports / 'sprint-insights.json'
        self.page = reports / 'sprint-report.html'

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(INSIGHTS), '--config', str(self.config), *args],
                              capture_output=True, text=True, cwd=str(self.dir), timeout=120)

    def facts(self, *args):
        proc = self.cli('facts', *args)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return json.loads(proc.stdout)

    def example(self):
        """Пример из навыка с хешем по этим данным — как его записал бы агент."""
        doc = json.loads(EXAMPLE.read_text(encoding='utf-8'))
        by_slug = {t['slug']: t for t in self.teams}
        for slug, entry in doc['teams'].items():
            entry['dataHash'] = build_mod.team_digest(by_slug[slug])
        return doc

    def write(self, doc):
        self.insights.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')

    def page_teams(self):
        html = self.page.read_text(encoding='utf-8')
        m = re.search(r'var TEAMS = (\[.*?\]);\n', html, re.S)
        return json.loads(m.group(1))


class FactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = Workspace()
        cls.facts = cls.ws.facts()

    @classmethod
    def tearDownClass(cls):
        cls.ws.cleanup()

    def test_one_entry_per_team_with_data_hash(self):
        self.assertEqual([t['slug'] for t in self.ws.teams], [t['slug'] for t in self.facts['teams']])
        for team, f in zip(self.ws.teams, self.facts['teams']):
            self.assertEqual(build_mod.team_digest(team), f['dataHash'])
            self.assertEqual({'burndown', 'velocity', 'controlStories', 'controlSubtasks'}, set(f['charts']))

    def test_numbers_come_from_data(self):
        for team, f in zip(self.ws.teams, self.facts['teams']):
            bd = f['charts']['burndown']
            today = [d for d in team['burndown']['days'] if not d['future']][-1]
            self.assertEqual((today['closed'], today['remaining'], today['scope']),
                             (bd['closed'], bd['remaining'], bd['scopeNow']))
            self.assertEqual(bd['remaining'] - bd['idealRemainingToday'], bd['gapToIdeal'])
            ctl = f['charts']['controlStories']
            chart = team['control']['stories']
            self.assertEqual(chart['outliers'], ctl['outlierCount'])
            self.assertEqual(len(chart['risks']), len(ctl['risks']))
            self.assertEqual(chart['median'], ctl['median'])
            vel = f['charts']['velocity']
            self.assertEqual([s['done'] for s in team['velocity']['sprints']], [s['done'] for s in vel['sprints']])
            self.assertTrue(vel['sprints'][-1]['current'])

    def test_notes_do_not_change_hash(self):
        """Заметки и сами инсайды — наложения runner'а: от них хеш данных не меняется."""
        team = dict(self.ws.teams[0])
        base = build_mod.team_digest(team)
        team['notes'] = {'x': 'заметка'}
        team['insights'] = {'charts': {}}
        self.assertEqual(base, build_mod.team_digest(team))
        team['sprintName'] = 'Другой спринт'
        self.assertNotEqual(base, build_mod.team_digest(team))

    def test_one_team(self):
        slug = self.ws.teams[1]['slug']
        self.assertEqual([slug], [t['slug'] for t in self.ws.facts('--team', slug)['teams']])
        proc = self.ws.cli('facts', '--team', 'nope')
        self.assertEqual(2, proc.returncode)
        self.assertIn('команды nope нет в снимке', proc.stdout)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        self.addCleanup(self.ws.cleanup)
        self.doc = self.ws.example()

    def check(self, doc):
        return insights_mod.check(doc, self.ws.teams)

    def test_example_passes_clean(self):
        errors, warnings = self.check(self.doc)
        self.assertEqual([], errors)
        self.assertEqual([], warnings, 'в примере каждое число — из фактов')

    def test_unknown_task_key_rejected(self):
        self.doc['teams']['platform']['charts']['burndown'][0]['keys'] = ['INIT-99999']
        errors, _ = self.check(self.doc)
        self.assertTrue(any('INIT-99999 нет в данных' in e for e in errors), errors)

    def test_key_in_text_checked_too(self):
        self.doc['teams']['platform']['charts']['velocity'][0]['text'] += ' Пример: ZZZ-1.'
        errors, _ = self.check(self.doc)
        self.assertTrue(any('ZZZ-1' in e for e in errors), errors)

    def test_stale_hash_rejected(self):
        self.doc['teams']['platform']['dataHash'] = 'a' * 64
        errors, _ = self.check(self.doc)
        self.assertTrue(any('dataHash не совпадает' in e for e in errors), errors)

    def test_schema_and_limits(self):
        item = self.doc['teams']['platform']['charts']['burndown'][0]
        item['level'] = 'panic'
        errors, _ = self.check(self.doc)
        self.assertTrue(any(e.startswith('схема:') for e in errors), errors)
        item['level'] = 'risk'
        item['text'] = 'очень длинно ' * 40
        errors, _ = self.check(self.doc)
        self.assertTrue(any('длиннее 280' in e for e in errors), errors)

    def test_unknown_team_rejected(self):
        self.doc['teams']['ghost'] = self.doc['teams']['platform']
        errors, _ = self.check(self.doc)
        self.assertTrue(any('[ghost] такой команды нет' in e for e in errors), errors)

    def test_invented_number_flagged(self):
        self.doc['teams']['platform']['charts']['burndown'][0]['text'] = 'Команда закроет 813.7 задачи к пятнице.'
        errors, warnings = self.check(self.doc)
        self.assertEqual([], errors)
        self.assertTrue(any('числа 813.7 нет в фактах' in w for w in warnings), warnings)

    def test_small_counts_and_dates_not_flagged(self):
        self.doc['teams']['platform']['charts']['burndown'][0]['text'] = \
            'За 2 дня до 2026-09-22 закрыто 5 из 48: держим INIT-132 под контролем.'
        _, warnings = self.check(self.doc)
        self.assertEqual([], warnings)


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        self.addCleanup(self.ws.cleanup)

    def test_apply_embeds_insights_into_page(self):
        self.ws.write(self.ws.example())
        proc = self.ws.cli('apply')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn('инсайды ИИ: platform', proc.stdout)
        teams = {t['slug']: t for t in self.ws.page_teams()}
        ins = teams['platform']['insights']
        self.assertEqual('PO-агент (пример)', ins['author'])
        self.assertTrue(ins['charts']['burndown'])
        self.assertNotIn('insights', teams['catalog'], 'у команды без инсайдов поля нет')

    def test_apply_refuses_bad_file_and_keeps_page(self):
        doc = self.ws.example()
        doc['teams']['platform']['charts']['burndown'][0]['keys'] = ['INIT-99999']
        self.ws.write(doc)
        proc = self.ws.cli('apply')
        self.assertEqual(1, proc.returncode)
        self.assertIn('инсайды не приняты', proc.stdout)
        self.assertFalse(self.ws.page.exists(), 'страница не пересобиралась')

    def test_render_drops_stale_insights(self):
        """Данные пересобраны после инсайдов: страница без них, runner говорит, что делать."""
        self.ws.write(self.ws.example())
        teams = json.loads(self.ws.data.read_text(encoding='utf-8'))
        teams[0]['boardName'] = 'Другая доска'
        self.ws.data.write_text(json.dumps(teams, ensure_ascii=False), encoding='utf-8')
        proc = subprocess.run([sys.executable, str(RUN), '--config', str(self.ws.config), 'render'],
                              capture_output=True, text=True, cwd=str(self.ws.dir), timeout=120)
        self.assertEqual(1, proc.returncode, proc.stdout)
        self.assertIn('инсайды устарели (данные пересобраны): platform — /sprint-insights', proc.stdout)
        self.assertNotIn('insights', self.ws.page_teams()[0])

    def test_render_without_insights_file(self):
        proc = subprocess.run([sys.executable, str(RUN), '--config', str(self.ws.config), 'render'],
                              capture_output=True, text=True, cwd=str(self.ws.dir), timeout=120)
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertIn('инсайдов нет', proc.stdout)
        self.assertEqual(len(self.ws.teams), len(self.ws.page_teams()))

    def test_render_rejects_edited_snapshot(self):
        teams = json.loads(self.ws.data.read_text(encoding='utf-8'))
        del teams[0]['metrics']['overall']['lead']
        self.ws.data.write_text(json.dumps(teams, ensure_ascii=False), encoding='utf-8')
        proc = subprocess.run([sys.executable, str(RUN), '--config', str(self.ws.config), 'render'],
                              capture_output=True, text=True, cwd=str(self.ws.dir), timeout=120)
        self.assertEqual(1, proc.returncode)
        self.assertIn('снимок не прошёл валидацию', proc.stdout)
        self.assertFalse(self.ws.page.exists())


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (support.SKILL / 'resources' / 'report_template.html').read_text(encoding='utf-8')

    def test_tooltip_reads_ai_insights_not_static_advice(self):
        for part in ('function insightsHtml(', 'team.insights', "'controlStories'", "'controlSubtasks'",
                     '/sprint-insights', 'Интерпретация, не данные'):
            self.assertIn(part, self.html)
        self.assertNotIn('insight: [', self.html, 'советов «на все случаи» в шаблоне больше нет')

    def test_skill_and_command_present(self):
        skill = (INSIGHTS_DIR / 'SKILL.md').read_text(encoding='utf-8')
        self.assertTrue(skill.startswith('---\nname: sprint-insights\n'))
        for step in ('insights.py facts', 'insights.py apply', 'dataHash'):
            self.assertIn(step, skill)
        self.assertTrue((support.ROOT / '.claude' / 'commands' / 'sprint-insights.md').is_file())


if __name__ == '__main__':
    unittest.main()
