"""/sprint-status: PDF-лист из снимка actual-sprint. Всё на фикстурах, без сети.

Проверяется: runner пишет снимок вместе со страницей; модель считает те же числа,
что лежат в данных; лист собирается кодом (форма фиксирована); stdout — подпись и
метка MEDIA для Hermes; при отказе сбора — прошлый снимок с причиной, без снимка —
одна понятная строка. Печать в PDF проверяется, если на машине есть Chromium.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support
from test_runner import Project

STATUS_DIR = support.ROOT / '.claude' / 'skills' / 'sprint-status'
STATUS = STATUS_DIR / 'status.py'
DEMO = support.SKILL / 'scripts' / 'demo_data.py'
NOW = '2026-09-15T18:00:00+03:00'

sys.path.insert(0, str(STATUS_DIR))
import model as model_mod  # noqa: E402
import page as page_mod  # noqa: E402
import pdf as pdf_mod  # noqa: E402

BROWSER = pdf_mod.find_browser()


def demo_file():
    out = Path(tempfile.mkdtemp(prefix='sprint-status-')) / 'demo.json'
    proc = subprocess.run([sys.executable, str(DEMO), '--out', str(out)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return out


def run_status(*args, cwd=None, env=None):
    environ = dict(os.environ)
    environ.update(env or {})
    return subprocess.run([sys.executable, str(STATUS), *args], capture_output=True,
                          text=True, cwd=cwd, env=environ, timeout=300)


def media_path(stdout):
    hits = re.findall(r'^MEDIA:(.+)$', stdout, re.M)
    return Path(hits[0]) if hits else None


class ModelTest(unittest.TestCase):
    """Числа листа — ровно те, что в данных; расчёты живут в model.py."""

    @classmethod
    def setUpClass(cls):
        cls.data = demo_file()
        cls.teams = json.loads(cls.data.read_text(encoding='utf-8'))
        cls.models = model_mod.build(cls.teams)

    def test_progress_matches_burndown_and_statuses(self):
        for team, m in zip(self.teams, self.models):
            today = [d for d in team['burndown']['days'] if not d['future']][-1]
            split = team['velocity']['sprints'][-1]['split']
            self.assertEqual(today['closed'], m['pace']['closed'])
            self.assertEqual(today['scope'], m['pace']['scope'])
            self.assertEqual(split, m['split'])
            # демо согласовано: burndown на сегодня сходится со статусами задач
            self.assertEqual(m['pace']['closed'], m['split']['done'])

    def test_gap_adds_up_with_ideal_label(self):
        """Плитка «Темп» и подпись «идеал N» на графике сходятся в уме читателя."""
        for m in self.models:
            p = m['pace']
            self.assertEqual(p['remaining'] - p['ideal'][p['todayIndex']], p['gap'])
            self.assertTrue(all(isinstance(v, int) for v in p['ideal'][p['first']:]))

    def test_ideal_starts_at_first_nonzero_scope(self):
        """Задачи внесли через минуты после старта: первый день с нулём не кладёт прямую на ось."""
        team = json.loads(json.dumps(self.teams[0]))
        team['burndown']['days'][0].update(scope=0, remaining=0, closed=0)
        p = model_mod.build([team])[0]['pace']
        self.assertEqual(1, p['first'])
        self.assertIsNone(p['ideal'][0])
        self.assertEqual(team['burndown']['days'][1]['scope'], p['ideal'][1])
        self.assertLess(p['gap'], p['remaining'])

    def test_no_epic_goes_last(self):
        for m in self.models:
            keys = [ep['key'] for ep in m['epics']]
            if None in keys:
                self.assertIsNone(keys[-1])

    def test_workdays(self):
        p = self.models[0]['pace']
        self.assertEqual((6, 11, 5), (p['workday'], p['workdays'], p['left']))

    def test_attention_order_and_no_duplicates(self):
        for m in self.models:
            kinds = [r['kind'] for r in m['attention']]
            self.assertEqual(kinds, sorted(kinds, key=['blocked', 'stale', 'risk'].index))
            keys = [r['key'] for r in m['attention']]
            self.assertEqual(len(keys), len(set(keys)))
            for r in m['stale']:
                self.assertGreater(r['days'], model_mod.STALE_DAYS)

    def test_person(self):
        self.assertEqual('Иванов И.', model_mod.person('Иванов Иван Иванович'))
        self.assertEqual('Система', model_mod.person('Система'))
        self.assertEqual('без исполнителя', model_mod.person(None))

    def test_jira_offset_without_colon(self):
        self.assertIsNotNone(model_mod.parse_ts('2026-09-15T17:00:00.000+0300'))


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = demo_file()
        cls.teams = json.loads(cls.data.read_text(encoding='utf-8'))

    def render(self, teams, **kw):
        return page_mod.render(model_mod.build(teams), model_mod.parse_ts(NOW), **kw)

    def test_sheet_per_team_plus_summary(self):
        html = self.render(self.teams)
        self.assertEqual(len(self.teams) + 1, html.count('<section class="sheet">'))
        self.assertIn('Команды на 15.09.2026', html)
        self.assertEqual(1, self.render(self.teams[:1]).count('<section class="sheet">'))

    def test_fixed_blocks(self):
        html = self.render(self.teams[:1])
        html = html[html.index('<body>'):]
        order = [html.index(s) for s in ('Платформа', '>Готово<', '>Темп<', '>За сутки<', '>Блокеры<',
                                         '>Без движения<', '>Зона риска<', 'Burndown<', 'Статусы<',
                                         'Внимание<', 'Эпики<', 'Данные JIRA на 15.09.2026 17:00')]
        self.assertEqual(sorted(order), order)

    def test_deterministic(self):
        self.assertEqual(self.render(self.teams), self.render(self.teams))

    def test_self_contained(self):
        """Лист печатается офлайн: ни внешних скриптов, ни шрифтов, ни картинок."""
        html = self.render(self.teams)
        self.assertNotRegex(html, r'(?i)<script|<link|src=|url\(')

    def test_lists_are_capped(self):
        html = self.render(self.teams[:1])
        self.assertLessEqual(html.count('<div class="row">'), page_mod.MAX_ATTENTION)
        self.assertIn('ещё', html)

    def test_titles_are_escaped(self):
        teams = json.loads(json.dumps(self.teams[:1]))
        teams[0]['epics'][0]['stories'][0]['title'] = '<b>x</b> & «y»'
        teams[0]['epics'][0]['stories'][0]['status'] = 'В ожидании'
        self.assertNotIn('<b>x</b>', self.render(teams))

    def test_stale_and_refresh_banners(self):
        html = page_mod.render(model_mod.build(self.teams), model_mod.parse_ts('2026-09-17T18:00:00+03:00'))
        self.assertIn('данные старше 49 ч', html)
        html = self.render(self.teams, refresh_error='JIRA недоступна')
        self.assertIn('⚠ Свежий сбор не удался: JIRA недоступна', html)


class CliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = demo_file()

    def test_html_only(self):
        out = self.data.parent / 'x' / 'status.pdf'
        proc = run_status('--data', str(self.data), '--now', NOW, '--html-only', '--out', str(out))
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertTrue(out.with_suffix('.html').is_file())
        self.assertIn('Статус спринта на 15.09 17:00 — Платформа, Каталог, Мобильное приложение',
                      proc.stdout)

    def test_unknown_team(self):
        proc = run_status('--data', str(self.data), '--team', 'nope')
        self.assertEqual(2, proc.returncode)
        self.assertIn('в снимке нет команды «nope»', proc.stdout)

    def test_no_browser_is_one_line(self):
        proc = run_status('--data', str(self.data), '--chrome', '/nope/chrome')
        self.assertEqual(1, proc.returncode)
        self.assertEqual(1, len(proc.stdout.strip().splitlines()))
        self.assertIn('Статус спринта не собран: PDF', proc.stdout)

    @unittest.skipUnless(BROWSER, 'нет Chrome/Chromium — печать в PDF проверить нечем')
    def test_pdf_with_media_tag(self):
        proc = run_status('--data', str(self.data), '--now', NOW)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        pdf = media_path(proc.stdout)
        self.assertIsNotNone(pdf, proc.stdout)
        self.assertEqual('sprint-status-2026-09-15.pdf', pdf.name)
        body = pdf.read_bytes()
        self.assertEqual(b'%PDF-', body[:5])
        self.assertEqual(4, len(re.findall(rb'/Type\s*/Page\b', body)))
        # лог печати — в stderr, в чат уходят только подпись и метка
        self.assertEqual(2, len(proc.stdout.strip().splitlines()))


class EndToEndTest(unittest.TestCase):
    """Настоящий runner и сборщики на записанных ответах JIRA → снимок → лист."""

    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.snapshot = self.p.dir / 'reports' / 'sprint-report.data.json'
        self.env = {'JIRA_URL': 'https://jira.demo-workspace.local',
                    'JIRA_PERSONAL_TOKEN': support.FAKE_TOKEN}

    def status(self, *args, env=None):
        return run_status('--config', str(self.p.config), '--html-only', *args, cwd=str(self.p.dir),
                          env=self.env if env is None else env)

    def html(self, proc):
        path = re.findall(r'^HTML: (.+)$', proc.stdout, re.M)
        self.assertTrue(path, proc.stdout)
        return Path(path[0]).read_text(encoding='utf-8')

    def test_runner_writes_snapshot_with_page(self):
        self.p.lock_all()
        proc = self.p.run('run')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        teams = json.loads(self.snapshot.read_text(encoding='utf-8'))
        self.assertEqual(['team-a', 'team-b'], [t['slug'] for t in teams])
        self.assertIn(teams[0]['sprintName'], self.p.output.read_text(encoding='utf-8'))

    def test_refresh_then_sheet(self):
        self.p.lock_all()
        proc = self.status('--refresh')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        html = self.html(proc)
        self.assertIn('Команда А', html)
        self.assertIn('B-19', html)
        self.assertNotIn('Свежий сбор не удался', html + proc.stdout)
        self.assertNotIn('запускаю сборщик', proc.stdout)
        self.assertNotIn(support.FAKE_TOKEN, proc.stdout + proc.stderr + html)

    def test_refresh_failure_falls_back_to_snapshot(self):
        """Cron в 9:45 без VPN: приходит вчерашний снимок с причиной, а не тишина."""
        self.p.lock_all()
        self.assertEqual(0, self.p.run('run').returncode)
        env = dict(self.env, JIRA_PERSONAL_TOKEN='')
        proc = self.status('--refresh', env=env)
        self.assertEqual(0, proc.returncode, proc.stdout)
        first = proc.stdout.splitlines()[0]
        self.assertTrue(first.startswith('⚠ Свежий сбор не удался: '), first)
        self.assertIn('JIRA_PERSONAL_TOKEN', first)
        self.assertIn('⚠ Свежий сбор не удался', self.html(proc))

    def test_changed_collector_reason_is_named(self):
        self.p.lock_all()
        self.assertEqual(0, self.p.run('run').returncode)
        with self.p.collector.open('a', encoding='utf-8') as fh:
            fh.write('\n# правка после проверки\n')
        proc = self.status('--refresh')
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertIn('изменён после проверки', proc.stdout.splitlines()[0])
        self.assertIn('/collector-validate team-b', proc.stdout)

    def test_overdue_sprint_and_sprint_only_risks(self):
        """Фикстура: спринт 74 кончился 22.09, но активен; зона риска трёх спринтов шире него."""
        self.p.lock_all()
        self.assertEqual(0, self.p.run('run').returncode)
        a = json.loads(self.snapshot.read_text(encoding='utf-8'))[0]
        m = model_mod.build([a])[0]
        self.assertTrue(m['pace']['overdue'])
        self.assertIn('срок истёк 22.09', self.html(self.status('--team', 'team-a')))
        in_sprint = {st['key'] for e in a['epics'] for st in e['stories']} | \
                    {sub['key'] for e in a['epics'] for st in e['stories'] for sub in st['subtasks']}
        all_risks = {r['key'] for g in ('stories', 'subtasks') for r in a['control'][g]['risks']}
        self.assertTrue(all_risks - in_sprint, 'фикстура должна содержать риски прошлых спринтов')
        self.assertEqual(all_risks & in_sprint, {r['key'] for r in m['risks']})

    def test_never_collected(self):
        proc = self.status('--refresh')
        self.assertEqual(2, proc.returncode, proc.stdout)
        self.assertIn('Статус спринта не собран: снимка данных нет', proc.stdout)

    def test_no_config(self):
        proc = run_status('--config', str(self.p.dir / 'missing.toml'), cwd=str(self.p.dir))
        self.assertEqual(2, proc.returncode)
        self.assertEqual(1, len(proc.stdout.strip().splitlines()))
        self.assertIn('/sprint-setup', proc.stdout)


class SkillHygieneTest(unittest.TestCase):
    def setUp(self):
        self.skill = (STATUS_DIR / 'SKILL.md').read_text(encoding='utf-8')

    def test_no_manual_collection_instructions(self):
        lowered = self.skill.lower()
        for forbidden in ('curl', 'jql', 'rest/api', 'rest/agile', 'customfield'):
            self.assertNotIn(forbidden, lowered)

    def test_states_ai_is_not_a_data_source(self):
        self.assertIn('ИИ не источник данных', self.skill)
        self.assertIn('status.py', self.skill)
        self.assertIn('MEDIA:', self.skill)

    def test_command_and_hermes_script_exist(self):
        self.assertTrue((support.ROOT / '.claude' / 'commands' / 'sprint-status.md').is_file())
        script = STATUS_DIR / 'hermes' / 'sprint-status.sh'
        self.assertTrue(os.access(script, os.X_OK), 'скрипт для Hermes должен быть исполняемым')


if __name__ == '__main__':
    unittest.main()
