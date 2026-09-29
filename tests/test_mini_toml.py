"""Мини-парсер TOML-подмножества для конфига отчёта: работает на 3.10+.

Конфиг использует ограниченный TOML: таблицы, массивы таблиц, ключ-значение,
строки, целые, були, массивы строк/целых, комментарии. tomllib есть только в
3.11+, а стенд пользователя обязан работать на системном python3 без зависимостей.
Парсер не общий: он покрывает форму sprint-report.config.toml и отклоняет
всё, что не она, понятной ошибкой.
"""
import unittest

import support
from support import load_module

mini_toml = load_module(support.RUNNER / 'mini_toml.py', 'mini_toml')


class MiniTomlTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(mini_toml.loads(''), {})

    def test_top_level_keys(self):
        data = mini_toml.loads('version = 1\nstrict = true\nstrict2 = false')
        self.assertEqual(1, data['version'])
        self.assertIs(True, data['strict'])
        self.assertIs(False, data['strict2'])

    def test_strings(self):
        data = mini_toml.loads('slug = "team-a"\nname = "Команда А"')
        self.assertEqual('team-a', data['slug'])
        self.assertEqual('Команда А', data['slug'.replace('slug', 'name')])

    def test_arrays(self):
        data = mini_toml.loads('story_types = ["История", "Story"]\nboards = [203, 204]')
        self.assertEqual(['История', 'Story'], data['story_types'])
        self.assertEqual([203, 204], data['boards'])

    def test_table(self):
        data = mini_toml.loads('[jira]\nurl_env = "JIRA_URL"')
        self.assertEqual({'url_env': 'JIRA_URL'}, data['jira'])

    def test_array_of_tables(self):
        raw = '[[teams]]\nslug = "a"\n[teams.params]\nstory_types = ["История"]\n' \
              '[[teams]]\nslug = "b"\n[teams.collector]\ncmd = ["python3", "collector.py"]'
        data = mini_toml.loads(raw)
        self.assertEqual(['a', 'b'], [t['slug'] for t in data['teams']])
        self.assertEqual(['История'], data['teams'][0]['params']['story_types'])
        self.assertEqual(['python3', 'collector.py'], data['teams'][1]['collector']['cmd'])

    def test_comments_and_blank(self):
        raw = '# заголовок\n\nversion = 1  # int\noutput = "./reports/x.html"  # путь\n'
        data = mini_toml.loads(raw)
        self.assertEqual(1, data['version'])
        self.assertEqual('./reports/x.html', data['output'])

    def test_nested_status_buckets(self):
        raw = '[teams.params.status_buckets]\n"Ожидает релиза" = "review"\n"На паузе" = "blocked"'
        data = mini_toml.loads(raw)
        self.assertEqual({'Ожидает релиза': 'review', 'На паузе': 'blocked'},
                         data['teams']['params']['status_buckets'])

    def test_inline_trailing_comma_array(self):
        data = mini_toml.loads('xs = [\n  "a",\n  "b",\n]')
        self.assertEqual(['a', 'b'], data['xs'])

    def test_multiline_array_with_comments(self):
        raw = 'xs = [  # пояснение\n  "a",  # первый\n  "b"\n]'
        data = mini_toml.loads(raw)
        self.assertEqual(['a', 'b'], data['xs'])

    def test_quoted_key(self):
        data = mini_toml.loads('"ключ с пробелом" = 1')
        self.assertEqual(1, data['ключ с пробелом'])

    def test_error_names_line(self):
        with self.assertRaises(mini_toml.MiniTomlError) as ctx:
            mini_toml.loads('version = ')
        self.assertIn('строка 1', str(ctx.exception))

    def test_error_unknown_value(self):
        with self.assertRaises(mini_toml.MiniTomlError):
            mini_toml.loads('x = 1.5')  # float не входит в подмножество конфига

    def test_error_duplicate_key(self):
        with self.assertRaises(mini_toml.MiniTomlError):
            mini_toml.loads('[a]\nx = 1\nx = 2')

    def test_error_unterminated_string(self):
        with self.assertRaises(mini_toml.MiniTomlError):
            mini_toml.loads('x = "abc')

    def test_rejects_flow_table(self):
        with self.assertRaises(mini_toml.MiniTomlError):
            mini_toml.loads('jira = { url_env = "X" }')

    def test_parse_iso_helper(self):
        from datetime import datetime, timezone, timedelta
        dt = mini_toml.parse_iso('2026-09-15T17:00:00.000+0300')
        self.assertEqual(datetime(2026, 9, 15, 17, 0, tzinfo=timezone(timedelta(hours=3))), dt)
        z = mini_toml.parse_iso('2026-09-15T14:00:00Z')
        self.assertEqual(datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc), z)
        plain = mini_toml.parse_iso('2026-09-15')
        self.assertEqual(datetime(2026, 9, 15), plain)
