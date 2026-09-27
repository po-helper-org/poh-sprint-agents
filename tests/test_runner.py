"""Runner: конфиг → сборщики → валидация → HTML. Всё на фикстурах, без сети.

Проверяются критерии приёмки: две команды в одном файле, strict по хешу,
отказ писать HTML при ошибке, код 3 без обходных путей.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support

RUN = support.RUNNER / 'run.py'

CONFIG = '''version = 1
output = "./reports/sprint-report.html"
notes  = "./reports/sprint-report-notes.json"
strict = {strict}

[jira]
url_env   = "JIRA_URL"
token_env = "JIRA_PERSONAL_TOKEN"

[[teams]]
slug  = "team-a"
name  = "Команда А"
board = 101
collector = "base"
[teams.params]
story_types  = ["История", "История Enabler", "Story"]
sprints_back = 3
replay = "{replay}"

[[teams]]
slug  = "team-b"
name  = "Команда B"
board = 202
[teams.collector]
cmd     = ["python3", "collector.py"]
cwd     = "./collectors/team-b"
timeout = 60
[teams.params]
{team_b_params}
'''


class Project:
    """Проект пользователя во временном каталоге: конфиг, сборщик команды B, заметки."""

    def __init__(self, strict='true', team_b_params=''):
        self.dir = Path(tempfile.mkdtemp(prefix='actual-sprint-'))
        self.config = self.dir / 'sprint-report.config.toml'
        self.write_config(strict=strict, team_b_params=team_b_params)
        dest = self.dir / 'collectors' / 'team-b'
        dest.mkdir(parents=True)
        shutil.copy2(support.CUSTOM_COLLECTOR / 'collector.py', dest / 'collector.py')
        self.collector = dest / 'collector.py'
        self.output = self.dir / 'reports' / 'sprint-report.html'
        self.lock = self.dir / 'sprint-report.lock.json'

    def write_config(self, strict='true', team_b_params=''):
        self.config.write_text(CONFIG.format(strict=strict, replay=support.REPLAY,
                                             team_b_params=team_b_params), encoding='utf-8')

    def run(self, *args):
        env = dict(os.environ)
        env.update({'JIRA_URL': 'https://jira.demo-workspace.local',
                    'JIRA_PERSONAL_TOKEN': support.FAKE_TOKEN})
        proc = subprocess.run([sys.executable, str(RUN), '--config', str(self.config), *args],
                              capture_output=True, text=True, env=env, cwd=str(self.dir),
                              timeout=300)
        return proc

    def lock_all(self):
        for slug in ('team-a', 'team-b'):
            proc = self.run('lock', slug)
            assert proc.returncode == 0, proc.stdout + proc.stderr

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    # ------------------------------------------------------------- счастливый путь

    def test_two_teams_one_page(self):
        """Критерий приёмки: base с params и свой сборщик дают один HTML с двумя вкладками."""
        self.p.lock_all()
        proc = self.p.run('run')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertTrue(self.p.output.is_file())
        html = self.p.output.read_text(encoding='utf-8')
        self.assertNotIn('{{TEAMS_JSON}}', html)
        self.assertIn('"team-a"', html)
        self.assertIn('"team-b"', html)
        self.assertIn('доска «Scrum Board Платформа» (#101)', proc.stdout)
        self.assertIn('инварианты 24/24', proc.stdout)
        self.assertIn('→', proc.stdout)

    def test_summary_names_every_team(self):
        """ФТ-10: по каждой команде — доска, спринт, эпики, закрыто/всего, события, запросы."""
        self.p.lock_all()
        out = self.p.run('run').stdout
        for fragment in ('[team-a] доска', '[team-b] доска', 'спринт «Спринт 74»',
                         'спринт «B-19»', 'эпиков', 'закрыто', 'событий', 'запросов'):
            self.assertIn(fragment, out)

    def test_token_never_reaches_output(self):
        """НФТ-2: grep по выходным файлам на значение токена — ноль совпадений."""
        self.p.lock_all()
        self.p.run('run')
        for path in self.p.dir.rglob('*'):
            if path.is_file():
                text = path.read_text(encoding='utf-8', errors='ignore')
                self.assertNotIn(support.FAKE_TOKEN, text, f'токен нашёлся в {path.name}')

    def test_notes_are_carried_over(self):
        """Заметки прошлого запуска попадают в объект команды (ФТ-7)."""
        notes = self.p.dir / 'reports' / 'sprint-report-notes.json'
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text(json.dumps({'team-b': {'B-900': 'Ждём смежников', '__metrics__': 'на ретро'}},
                                    ensure_ascii=False), encoding='utf-8')
        self.p.lock_all()
        proc = self.p.run('run')
        self.assertIn('заметок подхвачено 2', proc.stdout)
        self.assertIn('Ждём смежников', self.p.output.read_text(encoding='utf-8'))

    def test_only_filter(self):
        self.p.lock_all()
        proc = self.p.run('run', '--only', 'team-b')
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertIn('[team-b]', proc.stdout)
        self.assertNotIn('[team-a] доска', proc.stdout)

    def test_provenance_data_in_page(self):
        """ФТ-25: по странице видно, чем и когда собраны данные (sha дописывает runner)."""
        self.p.lock_all()
        self.p.run('run')
        html = self.p.output.read_text(encoding='utf-8')
        self.assertIn('"sha"', html)
        self.assertIn('"collectedAt"', html)
        self.assertIn('renderProvenance', html)

    # ------------------------------------------------------------- strict и lock

    def test_unvalidated_collector_refused(self):
        """ФТ-8: без записи в lock-файле сборщик не запускается."""
        proc = self.p.run('run')
        self.assertEqual(2, proc.returncode)
        self.assertIn('не проверен', proc.stdout)
        self.assertIn('/collector-validate team-a', proc.stdout)
        self.assertFalse(self.p.output.exists())

    def test_changed_collector_refused_and_named(self):
        """Критерий приёмки: изменение одного байта — отказ с именем команды."""
        self.p.lock_all()
        self.assertEqual(0, self.p.run('run').returncode)
        self.p.collector.write_text(
            self.p.collector.read_text(encoding='utf-8') + '\n# один добавленный байт\n',
            encoding='utf-8')
        proc = self.p.run('run')
        self.assertEqual(2, proc.returncode)
        self.assertIn('[team-b]', proc.stdout)
        self.assertIn('изменён после проверки', proc.stdout)
        self.assertIn('/collector-validate team-b', proc.stdout)

    def test_strict_off_only_warns(self):
        self.p.write_config(strict='false')
        proc = self.p.run('run')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertIn('не проверен (strict выключен)', proc.stdout)

    def test_lock_file_written_by_runner_only(self):
        """ФТ-6: хеш пишется в lock-файл, а конфиг человека runner не трогает."""
        before = self.p.config.read_text(encoding='utf-8')
        proc = self.p.run('lock', 'team-a')
        self.assertEqual(0, proc.returncode, proc.stdout)
        data = json.loads(self.p.lock.read_text(encoding='utf-8'))
        self.assertIn('team-a', data['collectors'])
        self.assertEqual(64, len(data['collectors']['team-a']['sha256']))
        self.assertEqual(before, self.p.config.read_text(encoding='utf-8'))

    # ------------------------------------------------------------- отказы

    def test_missing_field_stops_build_and_keeps_previous_page(self):
        """Критерий приёмки: validate называет команду и путь, прошлый файл цел."""
        self.p.lock_all()
        self.assertEqual(0, self.p.run('run').returncode)
        good = self.p.output.read_text(encoding='utf-8')
        self.p.write_config(team_b_params='drop_field = true')
        self.p.lock_all()
        proc = self.p.run('run')
        self.assertEqual(1, proc.returncode)
        self.assertIn('[team-b] metrics.overall.lead', proc.stdout)
        self.assertIn('HTML не сгенерирован', proc.stdout)
        self.assertEqual(good, self.p.output.read_text(encoding='utf-8'))

    def test_jira_unavailable_is_code_3(self):
        """Критерий приёмки: код 3 → «проверьте VPN/токен», без обходных путей."""
        self.p.write_config(team_b_params='fail_jira = true')
        self.p.lock_all()
        proc = self.p.run('run')
        self.assertEqual(3, proc.returncode)
        self.assertIn('JIRA недоступна', proc.stdout)
        self.assertIn('VPN', proc.stdout)
        self.assertFalse(self.p.output.exists())

    def test_config_errors_name_team_and_field(self):
        """ФТ-5: ошибки конфига называют команду и поле, до любого запуска."""
        cases = [
            ('slug = "team-a"\nname = "Дубль"\nboard = 5\ncollector = "base"\n', 'повторяется'),
            ('slug = "Команда"\nname = "x"\nboard = 5\ncollector = "base"\n', 'небезопасен'),
            ('slug = "team-c"\nname = "x"\nboard = "сто один"\ncollector = "base"\n', 'board'),
        ]
        for extra, expect in cases:
            with self.subTest(expect=expect):
                text = self.p.config.read_text(encoding='utf-8') + '\n[[teams]]\n' + extra
                self.p.config.write_text(text, encoding='utf-8')
                proc = self.p.run('run')
                self.assertEqual(2, proc.returncode, proc.stdout)
                self.assertIn(expect, proc.stdout)
                self.p.write_config()

    def test_missing_token_env_is_config_error(self):
        env_less = subprocess.run(
            [sys.executable, str(RUN), '--config', str(self.p.config), 'run'],
            capture_output=True, text=True, cwd=str(self.p.dir),
            env={k: v for k, v in os.environ.items()
                 if k not in ('JIRA_PERSONAL_TOKEN', 'JIRA_URL')})
        self.assertEqual(2, env_less.returncode)
        self.assertIn('JIRA_URL', env_less.stdout)

    def test_timeout_kills_collector(self):
        slow = self.p.dir / 'collectors' / 'team-b' / 'collector.py'
        slow.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
        text = self.p.config.read_text(encoding='utf-8').replace('timeout = 60', 'timeout = 2')
        self.p.config.write_text(text, encoding='utf-8')
        self.p.lock_all()
        proc = self.p.run('run', '--only', 'team-b')
        self.assertEqual(1, proc.returncode)
        self.assertIn('timeout', proc.stdout)

    # ------------------------------------------------------------- validate и new

    def test_validate_prints_sample(self):
        """ФТ-13: выборка задач для сверки с JIRA, повторяемая по seed."""
        proc = self.p.run('validate', 'team-a', '--sample', '4')
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertIn('схема          ✓', proc.stdout)
        self.assertIn('инварианты     12/12 ✓', proc.stdout)
        self.assertIn('выборка для сверки с JIRA', proc.stdout)
        self.assertEqual(4, proc.stdout.count('status=«'))
        again = self.p.run('validate', 'team-a', '--sample', '4').stdout
        self.assertEqual([l for l in proc.stdout.splitlines() if 'status=«' in l],
                         [l for l in again.splitlines() if 'status=«' in l])

    def test_validate_with_lock_writes_lock(self):
        proc = self.p.run('validate', 'team-b', '--sample', '2', '--lock')
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertIn('lock записан', proc.stdout)
        self.assertIn('team-b', json.loads(self.p.lock.read_text(encoding='utf-8'))['collectors'])

    def test_validate_reports_broken_collector(self):
        self.p.write_config(team_b_params='drop_field = true')
        proc = self.p.run('validate', 'team-b')
        self.assertEqual(1, proc.returncode)
        self.assertIn('metrics.overall.lead', proc.stdout)
        self.assertNotIn('выборка для сверки', proc.stdout)

    def test_new_copies_template(self):
        """ФТ-20: свой сборщик начинается с копии базового шаблона."""
        proc = self.p.run('new', 'team-c')
        self.assertEqual(0, proc.returncode, proc.stdout)
        created = self.p.dir / 'collectors' / 'team-c' / 'collector.py'
        self.assertTrue(created.is_file())
        self.assertIn('TEAM RULE', created.read_text(encoding='utf-8'))
        self.assertIn('validate team-c', proc.stdout)


if __name__ == '__main__':
    unittest.main()
