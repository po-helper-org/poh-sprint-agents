"""Страница отчёта: корзина заметок, правый клик, привязка к сущности, приоритеты.

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

    def test_no_file_notes_no_log_block(self):
        """Ни заметок файлом, ни textarea в панели, ни лога над таблицей: всё в корзине."""
        for gone in ('notesExport', 'notesImport', 'notesFile', 'note-area', 'panelProgress',
                     'id="clog"', 'genInput'):
            self.assertNotIn(gone, self.html)

    def test_basket_in_top_right(self):
        """Как на странице ревью БФТ: кнопка «Комментарии (N)», под ней панель и промт."""
        box = self.html[self.html.index('<div class="promptbox"'):self.html.index('<div class="hero">')]
        for part in ('id="notesToggle"', 'id="cCount"', 'id="nText"', 'id="nRef"', 'id="itemsList"',
                     'id="promptOut"', 'id="copyBtn"', 'id="promptShow"'):
            self.assertIn(part, box)

    def test_notes_edit_delete_and_bind(self):
        for fn in ('function updateComment(', 'function removeComment(', 'function resolveRef(',
                   'function buildPrompt(', 'data-edit', 'data-del'):
            self.assertIn(fn, self.html)

    def test_actions_are_icons_on_hover(self):
        """Карандаш и мусорка иконками, как в панели poh-okr-plugin; видны при наведении."""
        self.assertIn("icoBtn('pencil', 'Редактировать'", self.html)
        self.assertIn("icoBtn('trash', 'Удалить'", self.html)
        self.assertIn('.nrow:hover .nacts', self.html)
        for gone in ('>изменить<', '>удалить<', 'class="where"'):
            self.assertNotIn(gone, self.html)

    def test_right_click_notes(self):
        self.assertIn("addEventListener('contextmenu'", self.html)
        for target in ("ctxAttr(epicTarget(e))", "itemTarget('story'", "itemTarget('subtask'"):
            self.assertIn(target, self.html)
        self.assertIn('id="cpopExisting"', self.html)

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
