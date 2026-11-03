"""Unslop-линтер статических текстов UI отчётов (правила heydamir/unslop, pass «Copy»).

Проверяет строки в шаблонах отчётов и shared-движке: короткие подписи и
empty-states без точки на конце, без восклицательных знаков, канцелярита
и хайп-слов. Точки в конце допустимы у многословных прозаических подсказок
(«Как читать», burn-how), промтов для ИИ-агента и строк, встраиваемых
в середину предложения (после двоеточия или с конкатенацией).

Правила калиброваны по audited-состоянию 2026-11 (t_69b8ed32): до чистки
в шаблонах было ~25 подписей с точкой; рецидив должен падать в CI.
"""
import re
import unittest
from pathlib import Path

import support

ROOT = support.ROOT
FILES = [
    ROOT / '.claude/skills/actual-sprint/resources/report_template.html',
    ROOT / '.claude/skills/actual-sprint/resources/shared/core.js',
    ROOT / '.claude/skills/sprint-business/resources/business_template.html',
]

# короткая подпись/empty-state с точкой на конце — только в пустых состояниях
# (div с классом *-empty/*-list) и в присвоениях textContent = '…';
# прозаические абзацы, тултипы и промты не проверяются
SHORT_CAPTION_DOT = re.compile(
    r'(?:class="(?:sidebar-empty|ops-empty|rm-empty|rk-empty|log-empty|mi-act-empty|empty-list|blk-empty)[^"]*">'
    r'([^<>]{4,70}[а-яё])\.'
    r'(?:</div>)'
    r'|textContent\s*=\s*\'([^\'\n]{4,70}[а-яё])\.\')')

EXCLAIM = re.compile(r'[а-яёА-ЯЁ]\s*!{1,2}[\s"\'<)]')
# empty-state, собранный конкатенацией: короткая строка в кавычках, кончается на «нет.»
CONCAT_EMPTY_DOT = re.compile(r"'([А-ЯЁ][^'\n]{8,70}нет)\.'")
OFFICE = re.compile(
    r'(?:важно отметить|следует отметить|стоит отметить|необходимо отметить|'
    r'обратите внимание, что|заметим, что|осуществля\w+|обеспечива\w+|'
    r'представляет собой|с целью|в рамках данного)')
HYPE = re.compile(
    r'(?:[Уу]никальн|[Кк]омплексн|[Ии]нновационн|[Бб]есшовн|[Уу]спешн|'
    r'[Ээ]ффективн|[Оо]птимальн|[Гг]армоничн|[Пп]рорывн|по-настоящему|поистине)')


class UnslopStaticTest(unittest.TestCase):
    def test_no_trailing_period_in_short_captions(self):
        hits = []
        for path in FILES:
            for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                m = SHORT_CAPTION_DOT.search(line) or CONCAT_EMPTY_DOT.search(line)
                if m:
                    text = m.group(1) or m.group(2)
                    hits.append(f'{path.name}:{n}: «{text}.»')
        self.assertEqual([], hits,
                         'короткая подпись без точки на конце (unslop Copy)')

    def test_no_exclamation_marks(self):
        hits = []
        for path in FILES:
            text = path.read_text(encoding='utf-8')
            # вырезаем комментарии и JS-условия, где ! — оператор
            for n, line in enumerate(text.splitlines(), 1):
                code = re.sub(r'//.*$', '', line)
                code = re.sub(r"'[^']*'", "''", code)      # строки отдельно
                for m in EXCLAIM.finditer(line):
                    # точное место: смотрим только внутри кавычек на исходной строке
                    for sm in re.finditer(r"'([^']*)'|\"([^\"]*)\"", line):
                        frag = sm.group(1) or sm.group(2) or ''
                        if EXCLAIM.search(frag):
                            hits.append(f'{path.name}:{n}: …{frag[:60]}…')
                            break
        self.assertEqual([], sorted(set(hits)), 'без восклицательных знаков в UI-текстах')

    def test_no_office_speak_or_hype(self):
        hits = []
        for path in FILES:
            text = path.read_text(encoding='utf-8')
            for rx, name in ((OFFICE, 'канцелярит'), (HYPE, 'хайп')):
                m = rx.search(text)
                if m:
                    hits.append(f'{path.name}: {name} «{m.group(0)}»')
        self.assertEqual([], hits, 'канцелярит и хайп — не для UI-текстов отчёта')


if __name__ == '__main__':
    unittest.main()
