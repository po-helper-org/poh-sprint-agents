"""Работа на Python 3.9–3.10: мини-парсер TOML и даты JIRA с «+0300».

На 3.11+ конфиг читает stdlib tomllib; мини-парсер — запасной путь, и он обязан
давать тот же результат на наших конфигах (сверка — там, где tomllib есть).
"""
import unittest
from datetime import datetime, timedelta, timezone

import support
import mini_toml
import config as config_mod
from test_runner import CONFIG

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

CONFIGS = {
    'example': (support.SKILL / 'examples' / 'sprint-report.config.toml').read_text(encoding='utf-8'),
    'runner-tests': CONFIG.format(strict='true', replay='/tmp/replay', team_b_params='drop_field = true'),
}


class MiniTomlTest(unittest.TestCase):
    def test_parses_example_config(self):
        data = mini_toml.loads(CONFIGS['example'])
        self.assertEqual(1, data['version'])
        self.assertEqual(['team-a', 'team-b'], [t['slug'] for t in data['teams']])

    @unittest.skipIf(tomllib is None, 'tomllib есть только в Python 3.11+')
    def test_same_result_as_tomllib(self):
        for name, text in CONFIGS.items():
            with self.subTest(config=name):
                self.assertEqual(tomllib.loads(text), mini_toml.loads(text))

    def test_bad_toml_is_config_error(self):
        with self.assertRaises(config_mod._TomlError):
            config_mod._toml.loads('version = [1,\n')

    def test_parse_iso_accepts_jira_offsets(self):
        want = datetime(2026, 9, 15, 17, 0, tzinfo=timezone(timedelta(hours=3)))
        for text in ('2026-09-15T17:00:00.000+0300', '2026-09-15T17:00:00.000+03:00',
                     '2026-09-15T14:00:00.000Z'):
            with self.subTest(text=text):
                self.assertEqual(want, mini_toml.parse_iso(text))


class CollectorParseTest(unittest.TestCase):
    def test_collector_parse_accepts_jira_offsets(self):
        collector = support.load_module(support.BASE_COLLECTOR, 'base_collector_compat')
        a = collector.parse('2026-09-15T17:00:00.000+0300')
        b = collector.parse('2026-09-15T14:00:00.000Z')
        self.assertEqual(a, b)
        self.assertEqual(timedelta(hours=3), a.utcoffset())


if __name__ == '__main__':
    unittest.main()
