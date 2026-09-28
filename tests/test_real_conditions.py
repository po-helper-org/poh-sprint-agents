"""Отказы, которых нет в фикстурах: сеть, авторизация, TLS, кривой конфиг стенда.

Это то, обо что спотыкается первый запуск на живом инстансе, поэтому проверяем
не «падает ли», а понятно ли написано, что чинить.
"""
import json
import os
import ssl
import subprocess
import sys
import unittest
import urllib.error

import support

COLLECTOR = support.load_module(support.BASE_COLLECTOR, 'collector_real')


class StubJira:
    """Считает запросы и отдаёт заранее заданные ответы — сеть не нужна."""

    def __init__(self, answers=None, raises=None):
        self.answers = answers or {}
        self.raises = raises or {}
        self.calls = []
        self.base = 'https://jira.example'

    def api(self, path, **params):
        self.calls.append((path, params))
        if path in self.raises:
            raise self.raises[path]
        for key, value in self.answers.items():
            if path.startswith(key):
                return value
        raise AssertionError(f'заглушка не знает ручку {path}')


def collector(jira, params=None):
    import buckets
    req = support.request(params=params or {})
    return COLLECTOR.Collector(jira, req, buckets.load())


class TlsTest(unittest.TestCase):
    def test_certificate_failure_points_at_ca_bundle(self):
        """Корпоративный CA — первый отказ на реальном инстансе, и «проверьте VPN»
        уводит не туда: сообщение должно называть jira.ca_bundle."""
        jira = COLLECTOR.Jira('https://jira.example', 'token')
        reason = ssl.SSLCertVerificationError(1, 'certificate verify failed: self-signed certificate')
        reason.verify_message = 'self-signed certificate'

        def boom(*a, **kw):
            raise urllib.error.URLError(reason)

        original = COLLECTOR.urllib.request.urlopen
        COLLECTOR.urllib.request.urlopen = boom
        try:
            with self.assertRaises(COLLECTOR.JiraProblem) as caught:
                jira.api('/rest/api/2/myself')
        finally:
            COLLECTOR.urllib.request.urlopen = original
        text = str(caught.exception)
        self.assertIn('ca_bundle', text)
        self.assertIn('сертификат', text.lower())
        self.assertNotIn('VPN', text)

    def test_unreadable_ca_bundle_names_the_path(self):
        """Путь из конфига должен доехать до контекста, а ошибка — назвать файл."""
        with self.assertRaises(COLLECTOR.ConfigProblem) as caught:
            COLLECTOR.Jira('https://jira.example', 'token', ca_bundle='/нет/такого/файла.pem')
        text = str(caught.exception)
        self.assertIn('/нет/такого/файла.pem', text)
        self.assertIn('jira.ca_bundle', text)

    def test_ca_bundle_is_actually_used(self):
        """Бандл должен попасть в контекст: иначе корпоративный CA не поможет."""
        import tempfile
        from pathlib import Path
        pem = Path(support.HERE) / 'fixtures' / 'demo-ca.pem'
        if not pem.is_file():
            self.skipTest('нет демо-сертификата')
        jira = COLLECTOR.Jira('https://jira.example', 'token', ca_bundle=str(pem))
        self.assertGreater(len(jira.ctx.get_ca_certs()), 0)


class TokenTest(unittest.TestCase):
    def test_non_ascii_token_is_config_error(self):
        """Не-ASCII в токене раньше валил сборщик трейсбеком на сборке заголовка."""
        proc = support.run_collector(env={'JIRA_PERSONAL_TOKEN': 'токен-кириллицей'},
                                     replay=None,
                                     req=support.request(url='https://jira.example'))
        self.assertEqual(2, proc.returncode, proc.stderr)
        self.assertIn('latin-1', proc.stderr)
        self.assertNotIn('Traceback', proc.stderr)

    def test_missing_token_is_jira_error(self):
        env = {k: v for k, v in os.environ.items() if k != 'JIRA_PERSONAL_TOKEN'}
        proc = subprocess.run([sys.executable, str(support.BASE_COLLECTOR)],
                              input=json.dumps(support.request(url='https://jira.example')),
                              capture_output=True, text=True,
                              env={**env, 'ACTUAL_SPRINT_CONTRACT': str(support.CONTRACT)})
        self.assertEqual(3, proc.returncode)
        self.assertIn('JIRA_PERSONAL_TOKEN', proc.stderr)


class BoardTest(unittest.TestCase):
    def test_board_fetched_by_id_not_by_scanning(self):
        """На инстансе с сотнями досок обход списка стоит десяток запросов и прав."""
        jira = StubJira({'/rest/agile/1.0/board/101': {'id': 101, 'name': 'Доска команды'}})
        self.assertEqual('Доска команды', collector(jira).board_name(101))
        self.assertEqual([('/rest/agile/1.0/board/101', {})], jira.calls)

    def test_unknown_board_is_config_error(self):
        """404 по доске — это «поправьте board в конфиге», а не «JIRA недоступна»."""
        jira = StubJira(raises={'/rest/agile/1.0/board/999':
                                COLLECTOR.JiraProblem('JIRA вернула HTTP 404 на GET …')})
        with self.assertRaises(COLLECTOR.ConfigProblem) as caught:
            collector(jira).board_name(999)
        self.assertIn('board в конфиге', str(caught.exception))

    def test_other_http_error_stays_jira_problem(self):
        jira = StubJira(raises={'/rest/agile/1.0/board/101':
                                COLLECTOR.JiraProblem('JIRA вернула HTTP 500 на GET …')})
        with self.assertRaises(COLLECTOR.JiraProblem):
            collector(jira).board_name(101)


class EpicBatchTest(unittest.TestCase):
    """Названия эпиков: JQL «key in (…)» не резиновый, ключи идут пачками."""

    def stories(self, n):
        return [{'key': f'X-{i}', 'fields': {'summary': f'История {i}',
                                             'status': {'id': '1', 'name': 'Бэклог'},
                                             'issuetype': {'name': 'История'},
                                             'created': '2026-09-01T10:00:00+03:00',
                                             'assignee': None, 'subtasks': [],
                                             'epic': f'E-{i}'}}
                for i in range(n)]

    def collect_epics(self, count, chunk=None):
        params = {'epic_batch': chunk} if chunk else {}
        searched = []

        class Jira(StubJira):
            def api(self, path, **kw):
                self.calls.append((path, kw))
                keys = [k.strip() for k in kw['jql'].split('(')[1].rstrip(')').split(',')]
                searched.append(keys)
                return {'issues': [{'key': k, 'fields': {'summary': 'Эпик ' + k}} for k in keys]}

        jira = Jira()
        col = collector(jira, params)
        col.cats = {'1': 'К выполнению'}
        epics = col.build_epics(self.stories(count), 'epic')
        return epics, searched

    def test_single_batch_for_small_team(self):
        epics, searched = self.collect_epics(7)
        self.assertEqual(1, len(searched))
        self.assertEqual(7, len(epics))

    def test_many_epics_split_into_batches(self):
        epics, searched = self.collect_epics(120)
        self.assertEqual([50, 50, 20], [len(b) for b in searched])
        self.assertEqual(120, len(epics))
        self.assertTrue(all(e['epicTitle'] for e in epics), 'названия должны подтянуться все')

    def test_batch_size_is_a_param(self):
        _, searched = self.collect_epics(10, chunk=4)
        self.assertEqual([4, 4, 2], [len(b) for b in searched])


class DoctorTest(unittest.TestCase):
    """`doctor` — проверка стенда до первого похода в JIRA."""

    def setUp(self):
        import test_runner
        self.p = test_runner.Project()
        self.addCleanup(self.p.cleanup)

    def test_ready_stand(self):
        self.p.lock_all()
        proc = self.p.run('doctor')
        self.assertEqual(0, proc.returncode, proc.stdout)
        self.assertIn('Стенд готов', proc.stdout)
        for line in ('python', 'плагин', 'конфиг', 'токен', 'ca_bundle'):
            self.assertIn(line, proc.stdout)

    def test_unvalidated_collector_blocks(self):
        proc = self.p.run('doctor')
        self.assertEqual(2, proc.returncode)
        self.assertIn('не проверен', proc.stdout)
        self.assertIn('Стенд не готов', proc.stdout)

    def test_never_prints_token_value(self):
        self.p.lock_all()
        proc = self.p.run('doctor')
        self.assertNotIn(support.FAKE_TOKEN, proc.stdout + proc.stderr)

    def test_broken_config_named(self):
        self.p.config.write_text('version = 1\n', encoding='utf-8')
        proc = self.p.run('doctor')
        self.assertEqual(2, proc.returncode)
        self.assertIn('нет ни одной команды', proc.stdout)

    def test_plugin_update_names_itself(self):
        """Обновился плагин — базовый сборщик перепроверяется, и так и написано."""
        self.p.lock_all()
        import config as config_mod
        lock = json.loads(self.p.lock.read_text(encoding='utf-8'))
        lock['collectors']['team-a']['sha256'] = '0' * 64
        lock['collectors']['team-a']['version'] = '0.9.0'
        self.p.lock.write_text(json.dumps(lock, ensure_ascii=False), encoding='utf-8')
        proc = self.p.run('doctor')
        self.assertIn('базовый сборщик обновился', proc.stdout)
        self.assertIn(f'0.9.0 → {config_mod.PLUGIN_VERSION}', proc.stdout)


if __name__ == '__main__':
    unittest.main()
