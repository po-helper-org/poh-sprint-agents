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

    def test_whole_epic_view(self):
        """Кнопка «Смотреть весь эпик» в шапке панели; объём — «Осталось» по процессу и «Сделано»."""
        head = self.html[self.html.index('<div class="stack-head">'):self.html.index('<div class="stack-body">')]
        self.assertIn('id="scopeBtn"', head)
        self.assertIn('Смотреть весь эпик', head)
        self.assertNotIn('Открыть в JIRA →', head, 'ссылка в JIRA — сам ключ эпика')
        self.assertIn('class="key-link"', self.html)
        for part in ('function renderScope(', "scopeSection('left', 'Осталось'", "scopeSection('done', 'Сделано'",
                     'function sprintChip(', 'function storyNode('):
            self.assertIn(part, self.html)

    def test_metrics_panel_clean(self):
        """Под графиками только легенда и списки; расшифровка — в подсказке «i»; строки — в сетке."""
        self.assertNotIn('Зелёная точка', self.html)
        self.assertNotIn('Серая ступенька', self.html)
        for part in ('function infoHtml(', 'function chartSection(', 'chartItemTarget(p, kind)',
                     'chartItemTarget(r, kind)', "kind: 'chart'"):
            self.assertIn(part, self.html)
        row = self.html[self.html.index('  .outlier-row {'):]
        self.assertIn('grid-template-columns', row[:row.index('}')], 'колонки фиксированы — строки не плавают')

    def test_phone_and_pwa(self):
        """Телефон: viewport, режим приложения, иконка внутри файла, долгое нажатие вместо правого клика."""
        head = self.html[:self.html.index('<style>')]
        self.assertIn('width=device-width', head)
        self.assertIn('viewport-fit=cover', head)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', head)
        self.assertIn('rel="apple-touch-icon" href="data:image/png;base64,', head)
        for part in ('@media (max-width: 640px)', '@media (hover: none)', 'env(safe-area-inset-top)',
                     "addEventListener('touchstart'", 'LONG_PRESS_MS', 'id="cpopCancel"'):
            self.assertIn(part, self.html)

    def test_presentation_fact_deck(self):
        """Кнопка «Презентация»: колода «ФАКТ | спринт» от целей — OBJ → KR (эпик) → истории."""
        bar = self.html[self.html.index('<div class="pb-row">'):self.html.index('<div class="notes-panel"')]
        self.assertIn('id="presBtn"', bar)
        self.assertIn('>Презентация<', bar)
        for part in ("var START_MODE = '{{START_MODE}}';", 'id="deck"', 'function titleSlide(', 'function heroSlide(',
                     'function objGroups(', 'function objSlide(', 'function krHeader(', 'function storyRow(',
                     'function autoText(', 'function opsSlides(', 'function controlCards(', 'function changesSlide(',
                     'function demoSlide(', 'function totalsSlide(', 'function risksSlide(', 'function openKr(',
                     'function openStory(', "'Без привязки к OKR'", "'#presentation'", '@page { size: 1280px 720px',
                     '<th>Задачи</th><th>Комментарий</th><th>Результат</th>', 'stat-green', 'stat-yellow', 'stat-red',
                     'ROWS_PER_SLIDE = 8', 'Прошлые 2 недели', 'Текущие 2 недели'):
            self.assertIn(part, self.html)
        self.assertNotIn('class="legend"', self.html, 'пояснения цветов на слайдах нет')
        self.assertNotIn("'Стримы: '", self.html, 'заголовок слайда — цель, а не «Стримы: команда»')

    def test_deck_text_editing_and_rmb_comments(self):
        """PO правит текст на слайде сам; комментарий — правым кликом (на телефоне — долгим нажатием)."""
        for part in ('id="deckEdit"', 'Редактировать текст', "contenteditable', 'plaintext-only'", 'function loadEdits(',
                     "'actual-sprint:deck-text:'", 'id="deckReset"', 'data-edit="'):
            self.assertIn(part, self.html)
        deck = self.html[self.html.index('function storyRow('):self.html.index('function objSlide(')]
        self.assertIn('ctxAttr(r.target)', deck, 'у строки истории — правый клик для комментария')

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
                if e['epicKey']:
                    scope = {i['key'] for i in e['scope']}
                    self.assertTrue({st['key'] for st in e['stories']} <= scope, 'спринт входит в объём эпика')
                for st in e['stories']:
                    self.assertTrue(st['priority'])
                    self.assertTrue(all(sub['priority'] for sub in st['subtasks']))


if __name__ == '__main__':
    unittest.main()
