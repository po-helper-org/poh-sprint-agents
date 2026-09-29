"""/sprint-status: текст из снимка actual-sprint. Всё на фикстурах, без сети.

Проверяется: runner пишет снимок вместе со страницей, текст собирается из него
кодом (форма фиксирована), при отказе сбора приходит прошлый снимок с пометкой,
а без снимка — одна понятная строка вместо трейсбека.
"""
import json
import os
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

status_mod = support.load_module(STATUS, 'sprint_status')


def demo_teams():
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


class DemoRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = demo_teams()
        cls.teams = json.loads(cls.data.read_text(encoding='utf-8'))

    def render(self, *args):
        proc = run_status('--data', str(self.data), '--now', NOW, *args)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        return proc.stdout

    def test_fixed_form(self):
        """Порядок блоков один и тот же — ради этого текст и собирает код."""
        out = self.render('--team', 'platform')
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith('Платформа · Спринт 74 — день 6 из 11, до 22.09'))
        self.assertTrue(lines[1].startswith('Готово '))
        self.assertTrue(lines[2].startswith('За сутки: '))
        self.assertTrue(lines[3].startswith('Статусы: открыто '))
        order = [out.index(s) for s in ('Внимание:', 'Зона риска:', 'Эпики (готово/всего):',
                                        'Данные JIRA на 15.09 17:00')]
        self.assertEqual(sorted(order), order)

    def test_deterministic(self):
        self.assertEqual(self.render(), self.render())

    def test_numbers_match_data(self):
        """«Готово X из Y» и строка статусов — из тех же данных, что и страница."""
        team = self.teams[0]
        today = [d for d in team['burndown']['days'] if not d['future']][-1]
        split = team['velocity']['sprints'][-1]['split']
        out = self.render('--team', team['slug'])
        self.assertIn(f'Готово {today["closed"]} из {today["scope"]}', out)
        self.assertIn(f'готово {split["done"]}', out)
        # демо согласовано: burndown на сегодня сходится со статусами задач
        self.assertEqual(today['closed'], split['done'])

    def test_short(self):
        """Краткость — часть контракта: списки свёрнуты, остальное числом."""
        out = self.render('--team', 'platform')
        attention = [l for l in out.splitlines() if l.startswith('· блок:') or l.startswith('· стоит')]
        self.assertLessEqual(len(attention), status_mod.MAX_ATTENTION)
        self.assertLessEqual(len(out.splitlines()), 25)

    def test_all_teams_in_config_order(self):
        out = self.render()
        heads = [out.index(t['team'] + ' · ') for t in self.teams]
        self.assertEqual(sorted(heads), heads)

    def test_stale_snapshot_flagged(self):
        out = run_status('--data', str(self.data), '--now', '2026-09-17T18:00:00+03:00').stdout
        self.assertIn('⚠ Данные JIRA на 15.09 17:00', out)
        self.assertIn('старше 49 ч', out)

    def test_unknown_team(self):
        proc = run_status('--data', str(self.data), '--team', 'nope')
        self.assertEqual(2, proc.returncode)
        self.assertIn('в снимке нет команды «nope»', proc.stdout)


class HelpersTest(unittest.TestCase):
    def test_person(self):
        self.assertEqual('Иванов И.', status_mod.person('Иванов Иван Иванович'))
        self.assertEqual('Система', status_mod.person('Система'))
        self.assertEqual('без исполнителя', status_mod.person(None))

    def test_days_word(self):
        self.assertEqual('меньше дня', status_mod.days_word(0))
        self.assertEqual('1 день', status_mod.days_word(1))
        self.assertEqual('3 дня', status_mod.days_word(3))
        self.assertEqual('12 дней', status_mod.days_word(12))
        self.assertEqual('21 день', status_mod.days_word(21))

    def test_jira_offset_without_colon(self):
        self.assertIsNotNone(status_mod.parse_ts('2026-09-15T17:00:00.000+0300'))


class EndToEndTest(unittest.TestCase):
    """Настоящий runner и сборщики на записанных ответах JIRA → снимок → текст."""

    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.snapshot = self.p.dir / 'reports' / 'sprint-report.data.json'
        self.env = {'JIRA_URL': 'https://jira.demo-workspace.local',
                    'JIRA_PERSONAL_TOKEN': support.FAKE_TOKEN}

    def status(self, *args, env=None):
        return run_status('--config', str(self.p.config), *args, cwd=str(self.p.dir),
                          env=self.env if env is None else env)

    def test_runner_writes_snapshot_with_page(self):
        self.p.lock_all()
        proc = self.p.run('run')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        teams = json.loads(self.snapshot.read_text(encoding='utf-8'))
        self.assertEqual(['team-a', 'team-b'], [t['slug'] for t in teams])
        html = self.p.output.read_text(encoding='utf-8')
        self.assertIn(teams[0]['sprintName'], html)

    def test_refresh_then_text(self):
        self.p.lock_all()
        proc = self.status('--refresh')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        out = proc.stdout
        self.assertIn('Команда А · Спринт 74', out)
        self.assertIn('Команда B · B-19', out)
        self.assertNotIn('⚠ Свежий сбор', out)
        # лог runner — в stderr, в чат не попадает
        self.assertNotIn('запускаю сборщик', out)
        self.assertNotIn(support.FAKE_TOKEN, out + proc.stderr)

    def test_refresh_failure_falls_back_to_snapshot(self):
        """Cron в 9:45 без VPN: приходит вчерашний снимок с причиной, а не тишина."""
        self.p.lock_all()
        self.assertEqual(0, self.p.run('run').returncode)
        env = dict(self.env)
        env['JIRA_PERSONAL_TOKEN'] = ''
        proc = self.status('--refresh', env=env)
        self.assertEqual(0, proc.returncode, proc.stdout)
        first = proc.stdout.splitlines()[0]
        self.assertTrue(first.startswith('⚠ Свежий сбор не удался: '), first)
        self.assertIn('JIRA_PERSONAL_TOKEN', first)
        self.assertIn('Команда А · Спринт 74', proc.stdout)

    def test_changed_collector_reason_is_named(self):
        """Сборщик правили после проверки: strict не пускает, причина — в первой строке."""
        self.p.lock_all()
        self.assertEqual(0, self.p.run('run').returncode)
        with self.p.collector.open('a', encoding='utf-8') as fh:
            fh.write('\n# правка после проверки\n')
        proc = self.status('--refresh')
        self.assertEqual(0, proc.returncode, proc.stdout)
        first = proc.stdout.splitlines()[0]
        self.assertIn('изменён после проверки', first)
        self.assertIn('/collector-validate team-b', proc.stdout)

    def test_overdue_sprint_and_sprint_only_risks(self):
        """Фикстура: спринт 74 кончился 22.09, но активен; зона риска трёх спринтов шире него."""
        self.p.lock_all()
        self.assertEqual(0, self.p.run('run').returncode)
        teams = json.loads(self.snapshot.read_text(encoding='utf-8'))
        a = teams[0]
        out = self.status('--team', 'team-a').stdout
        self.assertIn('Команда А · Спринт 74 — срок истёк 22.09, в JIRA спринт не закрыт', out)
        in_sprint = {st['key'] for e in a['epics'] for st in e['stories']} | \
                    {sub['key'] for e in a['epics'] for st in e['stories'] for sub in st['subtasks']}
        all_risks = {r['key'] for g in ('stories', 'subtasks') for r in a['control'][g]['risks']}
        self.assertTrue(all_risks - in_sprint, 'фикстура должна содержать риски прошлых спринтов')
        risk_line = next(l for l in out.splitlines() if l.startswith('Зона риска:'))
        count = int(risk_line.split()[2])
        self.assertEqual(len(all_risks & in_sprint), count)

    def test_never_collected(self):
        """Первый запуск без проверки сборщиков: снимка нет — одна строка, код 2."""
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

    def test_command_and_hermes_script_exist(self):
        self.assertTrue((support.ROOT / '.claude' / 'commands' / 'sprint-status.md').is_file())
        script = STATUS_DIR / 'hermes' / 'sprint-status.sh'
        self.assertTrue(os.access(script, os.X_OK), 'скрипт для Hermes должен быть исполняемым')


if __name__ == '__main__':
    unittest.main()
