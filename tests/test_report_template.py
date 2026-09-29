"""Страница отчёта: комментарии логом, правый клик, общее поле, приоритеты.

Поведение в браузере проверяет tests/e2e/report_comments.mjs (Chromium); здесь —
быстрые проверки шаблона, которые идут в каждом прогоне без браузера.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import support

TEMPLATE = support.SKILL / 'resources' / 'report_template.html'
DEMO = support.SKILL / 'scripts' / 'demo_data.py'


class TemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding='utf-8')

    def test_no_file_notes(self):
        """Заметки файлом убраны: ни выгрузки, ни загрузки, ни большой textarea в панели."""
        for gone in ('notesExport', 'notesImport', 'notesFile', 'note-area', 'panelProgress'):
            self.assertNotIn(gone, self.html)

    def test_comment_log_on_top(self):
        """Лог комментариев стоит над таблицей эпиков и копируется текстом."""
        self.assertLess(self.html.index('id="clog"'), self.html.index('id="tableBody"'))
        self.assertIn('id="clogCopy"', self.html)
        self.assertIn('function commentsText()', self.html)

    def test_general_field_in_top_right(self):
        top = self.html[self.html.index('<div class="top-actions">'):self.html.index('<div class="hero">')]
        self.assertIn('id="genInput"', top)

    def test_right_click_comments(self):
        self.assertIn("addEventListener('contextmenu'", self.html)
        for target in ("ctxAttr(epicTarget(e))", "itemTarget('story'", "itemTarget('subtask'"):
            self.assertIn(target, self.html)

    def test_priority_everywhere(self):
        for where in ('prioHtml(e.epicPriority)', 'prioHtml(story.priority)', 'prioHtml(sub.priority)'):
            self.assertIn(where, self.html)


class DemoPageTest(unittest.TestCase):
    def test_demo_has_priorities_on_every_level(self):
        out = Path(tempfile.mkdtemp()) / 'demo.json'
        subprocess.run([sys.executable, str(DEMO), '--out', str(out)], check=True, capture_output=True)
        teams = json.loads(out.read_text(encoding='utf-8'))
        for t in teams:
            for e in t['epics']:
                if e['epicKey']:
                    self.assertTrue(e['epicPriority'])
                for st in e['stories']:
                    self.assertTrue(st['priority'])
                    self.assertTrue(all(sub['priority'] for sub in st['subtasks']))


if __name__ == '__main__':
    unittest.main()
