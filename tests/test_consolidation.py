"""Консолидация: сайдкар команды после run и подкоманда merge.

Проверяются критерии приёмки SPEC /sprint §1 (см. ~/.scratch/sprint-command):
после run данные команды лежат в reports/teams/<slug>.json; merge двух
сайдкаров из разных workspace'ов рендерит один HTML с двумя вкладками;
протухший/невалидный сайдкар не попадает на страницу молча.
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


class Project:
    """Проект пользователя во временном каталоге: конфиг, сборщик, заметки."""

    def __init__(self, slug='team-a', name='Команда А', board=101):
        self.dir = Path(tempfile.mkdtemp(prefix='sprint-cons-'))
        self.slug = slug
        self.config = self.dir / 'sprint-report.config.toml'
        self.config.write_text(CONFIG.format(
            slug=slug, name=name, board=board, replay=support.REPLAY), encoding='utf-8')
        self.output = self.dir / 'reports' / 'sprint-report.html'
        self.lock = self.dir / 'sprint-report.lock.json'

    def run(self, *args, cmd=None):
        env = dict(os.environ)
        env.update({'JIRA_URL': 'https://jira.demo-workspace.local',
                    'JIRA_PERSONAL_TOKEN': support.FAKE_TOKEN})
        argv = [sys.executable, str(cmd or RUN), '--config', str(self.config), *args]
        proc = subprocess.run(argv, capture_output=True, text=True, env=env,
                              cwd=str(self.dir), timeout=300)
        return proc

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


CONFIG = '''version = 1
output = "./reports/sprint-report.html"
notes  = "./reports/sprint-report-notes.json"
strict = true

[jira]
url_env   = "JIRA_URL"
token_env = "JIRA_PERSONAL_TOKEN"

[[teams]]
slug  = "{slug}"
name  = "{name}"
board = {board}
collector = "base"
[teams.params]
story_types  = ["История", "История Enabler", "Story"]
sprints_back = 3
replay = "{replay}"
'''


class SidecarTest(unittest.TestCase):
    """run пишет сайдкар команды после успешной валидации."""

    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def run_all(self):
        self.assertEqual(0, self.p.run('lock', self.p.slug).returncode)
        return self.p.run('run')

    def test_sidecar_written(self):
        proc = self.run_all()
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        sidecar = self.p.dir / 'reports' / 'teams' / f'{self.p.slug}.json'
        self.assertTrue(sidecar.is_file(),
                        'сайдкар reports/teams/<slug>.json не написан')
        data = json.loads(sidecar.read_text(encoding='utf-8'))
        self.assertEqual(self.p.slug, data['slug'])
        self.assertIn('sha', data.get('_meta', {}))
        self.assertIn('epics', data)
        self.assertIn('metrics', data)

    def test_sidecar_not_written_on_failure(self):
        """strict-отказ: сборщик не проверен → HTML нет и сайдкара нет."""
        proc = self.p.run('run')  # без lock
        self.assertNotEqual(0, proc.returncode)
        sidecar = self.p.dir / 'reports' / 'teams' / f'{self.p.slug}.json'
        self.assertFalse(sidecar.is_file())


class MergeTest(unittest.TestCase):
    """merge собирает один HTML из сайдкаров разных workspace'ов."""

    def setUp(self):
        # replay-фикстуры ключуются по URL доски: берём ту же 101, slug другой
        self.ws_a = Project(slug='team-a', name='Команда А', board=101)
        self.ws_b = Project(slug='live-paas', name='Live.PaaS', board=101)
        for p in (self.ws_a, self.ws_b):
            self.addCleanup(p.cleanup)
        for p in (self.ws_a, self.ws_b):
            proc = p.run('lock', p.slug)
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            proc = p.run('run')
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)

    def merge(self, *args, **kw):
        """merge запускаем из ws_a с явными путями конфига output не зависит."""
        env = dict(os.environ)
        return self.ws_a.run('merge', *args, **kw)

    def test_merge_two_sidecars(self):
        out = self.ws_a.dir / 'reports' / 'merged.html'
        proc = self.ws_a.run('merge', 'team-a', 'live-paas',
                             '--workspace', str(self.ws_b.dir),
                             '--output', str(out))
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertTrue(out.is_file())
        html = out.read_text(encoding='utf-8')
        self.assertNotIn('{{TEAMS_JSON}}', html)
        self.assertIn('"team-a"', html)
        self.assertIn('"live-paas"', html)

    def test_merge_missing_sidecar_fails(self):
        out = self.ws_a.dir / 'reports' / 'merged.html'
        proc = self.ws_a.run('merge', 'team-a', 'ghost-team',
                             '--workspace', str(self.ws_b.dir),
                             '--output', str(out))
        self.assertEqual(2, proc.returncode, proc.stdout + proc.stderr)
        self.assertFalse(out.is_file())

    def test_merge_stale_sidecar(self):
        """Сайдкар старше порога — отказ без --stale-ok, пропуск с ним."""
        sidecar = self.ws_b.dir / 'reports' / 'teams' / 'live-paas.json'
        old = time_mtime_minus_hours(sidecar, 8)
        os.utime(sidecar, (old, old))
        out = self.ws_a.dir / 'reports' / 'merged.html'
        proc = self.ws_a.run('merge', 'team-a', 'live-paas',
                             '--workspace', str(self.ws_b.dir),
                             '--output', str(out))
        self.assertEqual(2, proc.returncode, proc.stdout + proc.stderr)
        self.assertFalse(out.is_file())
        self.assertIn('протух', proc.stdout.lower())
        # со stale-ok проходит
        proc = self.ws_a.run('merge', 'team-a', 'live-paas',
                             '--workspace', str(self.ws_b.dir),
                             '--output', str(out), '--stale-ok')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertTrue(out.is_file())


def time_mtime_minus_hours(path, hours):
    import time as _t
    return _t.time() - hours * 3600


if __name__ == '__main__':
    unittest.main()
