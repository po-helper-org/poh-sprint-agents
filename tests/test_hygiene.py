"""Гигиена кодовой базы: TLS, отсутствие ручного сбора, актуальность документации."""
import pathlib
import re
import unittest

import support

SKILL = support.SKILL
CODE_SUFFIX = ('.py', '.mjs', '.js', '.go', '.sh', '.html')


def code_files():
    """Файлы кода репозитория. Сам этот тест исключён: в нём запрещённые строки живут
    как образцы для поиска."""
    this = pathlib.Path(__file__).resolve()
    for path in support.ROOT.rglob('*'):
        if not path.is_file() or path.suffix not in CODE_SUFFIX:
            continue
        if path.resolve() == this:
            continue
        if any(part in {'.git', '__pycache__', '.venv', 'node_modules'} for part in path.parts):
            continue
        yield path


class TlsTest(unittest.TestCase):
    """НФТ-3: проверка сертификата включена всегда, CA подключается через ca_bundle."""

    FORBIDDEN = [r'CERT_NONE', r'check_hostname\s*=\s*False', r'InsecureSkipVerify',
                 r'verify\s*=\s*False', r'rejectUnauthorized\s*:\s*false',
                 r'NODE_TLS_REJECT_UNAUTHORIZED']

    def test_no_tls_disabling_in_code(self):
        hits = []
        for path in code_files():
            text = path.read_text(encoding='utf-8', errors='ignore')
            for pattern in self.FORBIDDEN:
                if re.search(pattern, text):
                    hits.append(f'{path.relative_to(support.ROOT)}: {pattern}')
        self.assertEqual([], hits)

    def test_collector_uses_default_context_with_ca(self):
        text = support.BASE_COLLECTOR.read_text(encoding='utf-8')
        self.assertIn('ssl.create_default_context', text)
        self.assertIn('cafile', text)


class SkillTest(unittest.TestCase):
    """ФТ-22, ФТ-23: навык запускает runner и не собирает данные сам."""

    def setUp(self):
        self.skill = (SKILL / 'SKILL.md').read_text(encoding='utf-8')
        self.command = (support.ROOT / '.claude' / 'commands' / 'actual-sprint.md').read_text(encoding='utf-8')

    def test_no_manual_collection_instructions(self):
        """Механики запроса (curl, JQL, ручки REST) в SKILL.md быть не должно —
        по ним модель соберёт данные сама."""
        lowered = self.skill.lower()
        for forbidden in ('curl', 'jql', 'rest/api', 'rest/agile', 'customfield'):
            self.assertNotIn(forbidden, lowered,
                             f'в SKILL.md осталась инструкция ручного сбора: {forbidden}')

    def test_states_ai_is_not_a_data_source(self):
        """БТ-5 читается прямо в навыке, а не выводится из умолчаний."""
        self.assertIn('ИИ не источник данных', self.skill)

    def test_points_at_runner(self):
        self.assertIn('runner/run.py', self.skill)

    def test_single_page_output(self):
        """ФТ-24: команда обещает один файл sprint-report.html."""
        self.assertIn('sprint-report.html', self.command)
        self.assertNotIn('{team-slug}-sprint-report.html', self.command)

    def test_commands_exist(self):
        commands = support.ROOT / '.claude' / 'commands'
        for name in ('actual-sprint', 'sprint-setup', 'collector-new', 'collector-validate'):
            self.assertTrue((commands / f'{name}.md').is_file(), f'нет команды /{name}')


class ContractDocsTest(unittest.TestCase):
    def test_protocol_documents_exit_codes(self):
        text = (support.CONTRACT / 'PROTOCOL.md').read_text(encoding='utf-8')
        for fragment in ('stdin', 'stdout', 'stderr', '`0`', '`2`', '`3`', 'now'):
            self.assertIn(fragment, text)

    def test_data_shape_points_at_schema(self):
        """ФТ-1: схема — источник истины, в data_shape.md остаются пояснения «почему»."""
        text = (SKILL / 'resources' / 'data_shape.md').read_text(encoding='utf-8')
        self.assertIn('team.schema.json', text)

    def test_example_config_parses(self):
        import config as config_mod  # tomllib на 3.11+, мини-парсер на 3.9–3.10
        raw = (SKILL / 'examples' / 'sprint-report.config.toml').read_bytes()
        data = config_mod._toml.loads(raw.decode('utf-8'))
        self.assertEqual(1, data['version'])
        self.assertEqual(['team-a', 'team-b'], [t['slug'] for t in data['teams']])
        # токен в конфиг не попадает: там только имя переменной окружения
        self.assertEqual('JIRA_PERSONAL_TOKEN', data['jira']['token_env'])
        for forbidden in ('token', 'password', 'secret'):
            self.assertNotIn(forbidden, data['jira'], f'секрет в конфиге: {forbidden}')


if __name__ == '__main__':
    unittest.main()
