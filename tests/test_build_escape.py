"""Данные команд встраиваются в <script> страницы: текст из JIRA не должен из него вырваться.

Название эпика, заметка или имя автора приходят из трекера — их пишет кто угодно.
`</script>` или `<!--` в таком тексте закрыли бы блок данных и выполнили чужой код
на странице отчёта.
"""
import json
import re
import unittest

import support

build = support.load_module(support.RUNNER / 'build.py', 'build_escape')
TEMPLATE = support.SKILL / 'resources' / 'report_template.html'

EVIL = [
    '</script><script>alert(1)</script>',
    '</SCRIPT ><img src=x onerror=alert(1)>',
    '<!--<script>',
    'разделители строк   и   внутри',
    'A & B < C > D',
]


def payload(html):
    m = re.search(r'var TEAMS = (.*?);\n', html, re.S)
    assert m, 'в странице нет блока var TEAMS'
    return m.group(1)


class ScriptEscapeTest(unittest.TestCase):
    def render(self):
        teams = [{'slug': 't', 'notes': {'E-1': EVIL[2]},
                  'epics': [{'rowId': f'E-{i}', 'epicTitle': t} for i, t in enumerate(EVIL)]}]
        return teams, build.render(teams, TEMPLATE)

    def test_text_cannot_close_script_block(self):
        _, html = self.render()
        data = payload(html)
        self.assertNotRegex(data.lower(), r'</script|<!--|<script')
        self.assertNotIn(' ', data)
        self.assertNotIn(' ', data)

    def test_data_survives_round_trip(self):
        teams, html = self.render()
        self.assertEqual(teams, json.loads(payload(html)))


if __name__ == '__main__':
    unittest.main()
