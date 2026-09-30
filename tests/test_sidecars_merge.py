"""Сайдкары команд и `run.py merge`: страница из последних валидных сборов, без JIRA.

Сайдкар — `<workspace>/reports/teams/<slug>.json`, пишется после успешной команды.
merge склеивает HTML из сайдкаров: перевалидирует каждый, отвергает протухшие
(если не --stale-ok) и не пишет HTML, если хоть одна команда не принята.
"""
import json
import os
import subprocess
import sys
import time
import unittest

import support
from test_runner import Project, RUN


class SidecarTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.lock_all()

    def sidecar(self, slug):
        return self.p.dir / 'reports' / 'teams' / f'{slug}.json'

    def test_run_writes_sidecar_per_team(self):
        proc = self.p.run('run')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        for slug in ('team-a', 'team-b'):
            data = json.loads(self.sidecar(slug).read_text(encoding='utf-8'))
            self.assertEqual(slug, data['slug'])
            self.assertEqual(64, len(data['_meta']['sha']), 'в сайдкаре — хеш кода сборщика')
            self.assertIn(f'[{slug}] сайдкар → reports/teams/{slug}.json', proc.stdout)

    def test_failed_team_keeps_previous_sidecar_others_refresh(self):
        """Упала одна команда: её прошлый сайдкар цел, у соседки — свежий, HTML не пишется."""
        self.assertEqual(0, self.p.run('run').returncode)
        old_b = self.sidecar('team-b').read_text(encoding='utf-8')
        page = self.p.output.read_text(encoding='utf-8')
        os.utime(self.sidecar('team-a'), (1, 1))
        self.p.write_config(team_b_params='drop_field = true')
        self.p.lock_all()
        proc = self.p.run('run')
        self.assertEqual(1, proc.returncode)
        self.assertEqual(old_b, self.sidecar('team-b').read_text(encoding='utf-8'))
        self.assertGreater(self.sidecar('team-a').stat().st_mtime, 1, 'team-a собрана заново')
        self.assertEqual(page, self.p.output.read_text(encoding='utf-8'))

    def test_only_refreshes_just_that_team(self):
        self.assertEqual(0, self.p.run('run').returncode)
        os.utime(self.sidecar('team-a'), (1, 1))
        self.assertEqual(0, self.p.run('run', '--only', 'team-b').returncode)
        self.assertEqual(1, self.sidecar('team-a').stat().st_mtime, 'team-a не трогали')


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.lock_all()
        proc = self.p.run('run')
        assert proc.returncode == 0, proc.stdout + proc.stderr
        self.p.output.unlink()
        self.teams = self.p.dir / 'reports' / 'teams'

    def merge(self, *args):
        """merge без JIRA: переменных окружения с адресом и токеном нет вовсе."""
        env = {k: v for k, v in os.environ.items() if not k.startswith('JIRA')}
        return subprocess.run([sys.executable, str(RUN), '--config', str(self.p.config), 'merge', *args],
                              capture_output=True, text=True, env=env, cwd=str(self.p.dir), timeout=120)

    def page_slugs(self):
        html = self.p.output.read_text(encoding='utf-8')
        return [s for s in ('team-a', 'team-b') if f'"{s}"' in html]

    def test_merge_builds_page_from_sidecars_without_jira(self):
        proc = self.merge('team-b', 'team-a')
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        self.assertEqual(['team-a', 'team-b'], self.page_slugs())
        html = self.p.output.read_text(encoding='utf-8')
        self.assertLess(html.index('"slug": "team-b"'), html.index('"slug": "team-a"'),
                        'порядок вкладок — как в аргументах')

    def test_stale_sidecar_refused_unless_stale_ok(self):
        old = time.time() - 7 * 3600
        os.utime(self.teams / 'team-a.json', (old, old))
        proc = self.merge('team-a', 'team-b')
        self.assertNotEqual(0, proc.returncode)
        self.assertIn('[team-a] ✗ сайдкар протух', proc.stdout)
        self.assertFalse(self.p.output.exists())
        proc = self.merge('team-a', 'team-b', '--stale-ok')
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertIn('⚠ данные 7.0 ч назад', proc.stdout)
        self.assertEqual(['team-a', 'team-b'], self.page_slugs())

    def test_stale_hours_threshold(self):
        old = time.time() - 2 * 3600
        os.utime(self.teams / 'team-a.json', (old, old))
        self.assertNotEqual(0, self.merge('team-a', '--stale-hours', '1').returncode)
        self.assertEqual(0, self.merge('team-a', '--stale-hours', '3').returncode)

    def test_missing_sidecar_refused(self):
        (self.teams / 'team-b.json').unlink()
        proc = self.merge('team-a', 'team-b')
        self.assertNotEqual(0, proc.returncode)
        self.assertIn('[team-b] ✗ сайдкар не найден', proc.stdout)
        self.assertFalse(self.p.output.exists())

    def test_invalid_sidecar_refused(self):
        path = self.teams / 'team-b.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        del data['metrics']['overall']['lead']
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        proc = self.merge('team-a', 'team-b')
        self.assertNotEqual(0, proc.returncode)
        self.assertIn('[team-b] ✗ сайдкар не прошёл валидацию', proc.stdout)
        self.assertFalse(self.p.output.exists())

    def test_broken_json_refused(self):
        (self.teams / 'team-a.json').write_text('{oops', encoding='utf-8')
        proc = self.merge('team-a')
        self.assertNotEqual(0, proc.returncode)
        self.assertIn('не разбирается как JSON', proc.stdout)

    def test_merge_picks_up_notes(self):
        notes = self.p.dir / 'reports' / 'sprint-report-notes.json'
        notes.write_text(json.dumps({'team-b': {'B-900': 'Ждём смежников'}}, ensure_ascii=False),
                         encoding='utf-8')
        proc = self.merge('team-a', 'team-b')
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertIn('заметок подхвачено 1', proc.stdout)
        self.assertIn('Ждём смежников', self.p.output.read_text(encoding='utf-8'))

    def test_merge_output_override(self):
        out = self.p.dir / 'elsewhere' / 'page.html'
        proc = self.merge('team-a', '--output', str(out))
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertTrue(out.is_file())
        self.assertFalse(self.p.output.exists())

    def test_token_never_in_sidecars(self):
        for path in self.teams.glob('*.json'):
            self.assertNotIn(support.FAKE_TOKEN, path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
