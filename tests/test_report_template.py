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

import build as build_mod  # noqa: E402

TEMPLATE = support.SKILL / 'resources' / 'report_template.html'
BUSINESS_TEMPLATE = support.ROOT / '.claude' / 'skills' / 'sprint-business' / 'resources' / 'business_template.html'
DEMO = support.SKILL / 'scripts' / 'demo_data.py'


class TemplateTest(unittest.TestCase):
    """Отчёт PO: шаблон в сборе с общим движком resources/shared."""
    @classmethod
    def setUpClass(cls):
        cls.html = build_mod.assemble(TEMPLATE)

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
        """Кнопка «Смотреть весь эпик» в шапке панели; объём — «Что осталось» по процессу и «Что выполнено»."""
        head = self.html[self.html.index('<div class="stack-head">'):self.html.index('<div class="stack-body">')]
        self.assertIn('id="scopeBtn"', head)
        self.assertIn('Смотреть весь эпик', head)
        self.assertNotIn('Открыть в JIRA →', head, 'ссылка в JIRA — сам ключ эпика')
        self.assertIn('class="key-link"', self.html)
        for part in ('function renderScope(', "scopeSection('left', 'Что осталось'", "scopeSection('done', 'Что выполнено'",
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

    def test_whole_epic_has_forecast(self):
        """«Весь эпик» в общем движке: сгорание по неделям с прогнозом — один вид в обоих отчётах."""
        scope = self.html[self.html.index('function renderScope('):self.html.index('function setScopeMode(')]
        self.assertIn('epicBurnHtml(team, epic)', scope)
        self.assertIn("'Итог', verdictTip", self.html)
        self.assertNotIn('ea-sub', self.html, 'пояснения — в подсказках, не текстом')
        for part in ('BURN_WEEKS', 'BURN_MODES', "label: 'Закрытие историй'", "label: 'Закрытие подзадач'", "id: 'sp'",
                     "'Плановая дата'", "'Расчётная дата'", "'Темп сгорания'", 'eb-analysis', "'Что осталось'", "'Что выполнено'"):
            self.assertIn(part, self.html)
        self.assertNotIn('На чём прогноз', self.html, 'пояснений словами нет — всё на графике')
        biz = build_mod.assemble(BUSINESS_TEMPLATE)
        kr = biz[biz.index('function openKr('):]
        self.assertIn('renderScope(epic)', kr[:kr.index('\n  }\n')])

    def test_team_link_instead_of_sprint(self):
        """Шапка: ни метки «Команда», ни названия заголовком — вместо «Спринт:» ссылка «Команда: N» на участников."""
        hero = self.html[self.html.index('<div class="hero">'):self.html.index('<main>')]
        self.assertNotIn('<h1', hero)
        self.assertNotIn('Спринт:', hero)
        self.assertIn('id="teamLink"', hero)
        self.assertIn('id="interpBtn"', hero)
        for part in ('function openTeam(', 'memberTable(team, m, { back: true })', 'data-team-back'):
            self.assertIn(part, self.html)

    def test_business_report_is_separate(self):
        """Колоды в отчёте PO нет: «Бизнес-отчёт» даёт промт на отдельный навык sprint-business."""
        bar = self.html[self.html.index('<div class="pb-row">'):self.html.index('<div class="notes-panel"')]
        self.assertIn('id="bizBtn"', bar)
        self.assertIn('>Бизнес-отчёт<', bar)
        for gone in ('id="deck"', 'function buildDeck(', 'START_MODE', '#presentation', 'presBtn'):
            self.assertNotIn(gone, self.html)
        for part in ('function businessPrompt(', "'/sprint-business'", 'function openGenPrompt(', 'id="genWrap"',
                     'function allNotesLines(', 'OKR/roadmap PO'):
            self.assertIn(part, self.html)

    def test_shared_engine_assembled(self):
        """Части движка подставлены целиком: в странице не остаётся директив include."""
        self.assertNotIn('#include', self.html)
        raw = TEMPLATE.read_text(encoding='utf-8')
        for part in ('<!--#include shared/head.html-->', '/*#include shared/core.css*/', '/*#include shared/core.js*/',
                     '<!--#include shared/panels.html-->', '<!--#include shared/notes.html-->'):
            self.assertIn(part, raw)

    def test_priority_everywhere(self):
        for where in ('prioHtml(e.epicPriority)', 'prioHtml(story.priority)', 'prioHtml(sub.priority)'):
            self.assertIn(where, self.html)


class BusinessTemplateTest(unittest.TestCase):
    """Бизнес-отчёт (навык sprint-business): свой шаблон, тот же общий движок."""
    @classmethod
    def setUpClass(cls):
        cls.html = build_mod.assemble(BUSINESS_TEMPLATE)

    def test_fact_deck_from_goals(self):
        """Колода «ФАКТ | спринт» от целей — OBJ → KR (эпик) → истории; отчёта PO на странице нет."""
        for gone in ('id="tableBody"', 'id="metricsLink"', 'id="logsBtn"', 'START_MODE', 'id="deckClose"'):
            self.assertNotIn(gone, self.html)
        for part in ('id="deck"', 'id="techBtn"', '>Для техлидов<', 'function techPrompt(', "'/actual-sprint'",
                     'function biz(t) { return t.business || {}; }', 'function titleSlide(', 'function heroSlide(',
                     'function objGroups(', 'function objSlide(', 'function krHeader(', 'function storyRow(',
                     'function autoText(', 'function opsSlide(', 'function memberTable(', 'function changesSlide(',
                     'function demoSlide(', 'function totalsSlide(', 'function risksSlide(', 'function openKr(',
                     'function openStory(', "'Без привязки к OKR'", '@page { size: 1280px 720px',
                     '<th>Задачи</th><th>Комментарий</th><th>Результат</th>', 'stat-green', 'stat-yellow', 'stat-red',
                     'ROWS_PER_SLIDE = 8'):
            self.assertIn(part, self.html)
        self.assertNotIn('class="legend"', self.html, 'пояснения цветов на слайдах нет')
        self.assertNotIn("'Стримы: '", self.html, 'заголовок слайда — цель, а не «Стримы: команда»')

    def test_ops_slide_member_output(self):
        """Операционный отчёт без заголовка: производительность и сгорание спринта; группы статусов
        участников — для подсказок и сайдбара участника."""
        for part in ('Производительность команды за 3 спринта', 'Lead time', 'function tipHtml(', 'function teamOutputChart(', 'function openMember(',
                     'function itemActivityHtml(', "label: 'Backlog / To Do'", "label: 'Отменено'", 'CANCEL_RE'):
            self.assertIn(part, self.html)
        ops = self.html[self.html.index('var OUT_GROUPS = ['):self.html.index('function changesSlide(')]
        order = [ops.index("label: '" + g + "'") for g in ('Не начато', 'В работе', 'Выполнено')]
        self.assertEqual(sorted(order), order, 'три группы: не начато / в работе / выполнено')
        slide = self.html[self.html.index('function opsSlide('):]
        self.assertNotIn('slide-title', slide[:slide.index('function plansSlide(')], 'заголовка у операционного слайда нет')
        self.assertNotIn('memberTable(', slide[:slide.index('function plansSlide(')], 'участники — только в отчёте PO')
        self.assertNotIn('function memberChart(', self.html, 'графика выработки по участникам больше нет')

    def test_title_team_and_plans_slides(self):
        """Титул и слайд команды — со сводкой; после операционного — «Планы на следующий спринт»."""
        for part in ('function teamStats(', 't-cards', 'h-kpis', 'h-goals', 'function plansSlide(', "'Взять в работу'",
                     "'Доделать'", "'Эскалировать'", 'html += plansSlide(x.t, x.streams);'):
            self.assertIn(part, self.html)
        for gone in ('ИИ-агент PO по данным спринта', "' · эпик «'", "'Sprint Goal: '"):
            self.assertNotIn(gone, self.html)

    def test_story_calendar_and_feed(self):
        """Сайдбар истории: календарь активности за всё время и одна хронология с фильтром."""
        for part in ('function storyCalendar(', 'function storyFeedHtml(', "label: 'Все'", 'st.events'):
            self.assertIn(part, self.html)
        self.assertNotIn("'Активность за '", self.html)

    def test_ops_three_charts(self):
        """Операционный слайд: крупно производительность и сгорание спринта; следом слайд «Сроки»."""
        ops = self.html[self.html.index('function opsSlide('):self.html.index('// «Планы на следующий спринт»')]
        self.assertLess(ops.index('teamOutputChart(m, box)'), ops.index('burndownChart'))
        self.assertNotIn('controlChart', ops, 'диаграмма управления — на слайде «Сроки» и в его разборе')
        self.assertNotIn('function controlOverview(', self.html)
        build = self.html[self.html.index('function buildDeck('):]
        self.assertLess(build.index('html += opsSlide(x.t);'), build.index('html += cycleSlide(x.t);'))
        self.assertLess(build.index('html += cycleSlide(x.t);'), build.index('html += plansSlide('))

    def test_cycle_slide(self):
        """«Сроки»: cycle time с полосами спринтов и скользящими средними, время в статусах по спринтам;
        клик по графику — разбор в классической диаграмме управления."""
        for part in ('function cycleSlide(', 'function cycleChart(', 'function smoothPath(', 'CYCLE_ROLL = 5',
                     'Cycle time закрытых задач, дни', 'Среднее время в статусе по спринтам, дни', "label: 'Заблокировано'",
                     "label: 'Ревью'", "label: 'Отладка'", 'timeInStatus', "'хуже'", "'лучше'", 'без изменений к ',
                     'data-ctl=', 'function openControl(', 'controlWindow(', 'По спринтам'):
            self.assertIn(part, self.html)

    def test_kr_epic_burndown(self):
        """Клик по KR: сгорание эпика — объём, осталось, план (duedate) и прогноз по темпу спринта."""
        for part in ('function epicBurn(', 'function epicBurnChart(', 'epic.epicDue', 'прогноз', 'renderScope(epic)'):
            self.assertIn(part, self.html)

    def test_deck_stage_full_screen(self):
        """Широкий экран: один слайд на всю площадь, навигация кнопками; «Слайды» — выезжающий сайдбар-список."""
        for part in ('id="deckPrev"', 'id="deckNext"', 'id="deckCount"', 'id="deckFull"', 'function fitStage(',
                     'function renderToc(', 'id="deckSideTab"', 'function setToc(', '.deck-toc.open',
                     '.deck.stage .deck-slides > .fslide.cur', 'scale(var(--k, 1))'):
            self.assertIn(part, self.html)
        self.assertNotIn('thumb-box', self.html, 'постоянной панели миниатюр нет')
        printing = self.html[self.html.index('@media print'):]
        self.assertIn('.deck .deck-slides > .fslide { display: block !important;', printing, 'в PDF — все слайды, не только текущий')

    def test_deck_text_editing_and_rmb_comments(self):
        """PO правит текст на слайде сам; комментарий — правым кликом (на телефоне — долгим нажатием)."""
        for part in ('id="deckEdit"', 'Редактировать текст', "contenteditable', 'plaintext-only'", 'function loadEdits(',
                     "'actual-sprint:deck-text:'", 'id="deckReset"', 'data-edit="'):
            self.assertIn(part, self.html)
        deck = self.html[self.html.index('function storyRow('):self.html.index('function objSlide(')]
        self.assertIn('ctxAttr(r.target)', deck, 'у строки истории — правый клик для комментария')


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
