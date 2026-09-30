"""Эталон разбора квартала (docs/quarter-retro): инварианты формы и обезличенность.

Эталон — ориентир для будущего навыка ретро. Тест держит то, что в нём должно
оставаться верным при любых правках: у каждой строки KR есть карточка, исходы из
четырёх, счётчики фильтра = строкам таблицы, у каждого KR есть следующее действие.
И отдельно — что в публичный репозиторий не вернулись реальные ФИО.
"""
import collections
import json
import re
import unittest

import support

REF = support.ROOT / 'docs' / 'quarter-retro'
PAGE = REF / 'ideal_quarter_fact.html'
TARGET = REF / 'TARGET.md'

STATES = {'done': '✔', 'partial': '◐', 'failed': '✖', 'dropped': '⊘'}
NEXT_FORMS = ('Закрыт — снять с контроля', 'Продолжается в ', 'Отменён — записать причину',
              'Решить: продолжаем', '[УТОЧНИТЬ', 'MRS — планируется отдельно')
# частые имена в полной и разговорной форме: «Имя Фамилия» рядом — признак живого человека
FIRST_NAMES = ('Александр', 'Алексей', 'Анастасия', 'Андрей', 'Антон', 'Артём', 'Владимир',
               'Дмитрий', 'Дима', 'Екатерина', 'Евгений', 'Женя', 'Иван', 'Мария', 'Михаил',
               'Никита', 'Олег', 'Ольга', 'Павел', 'Саша', 'Сергей', 'Тимур', 'Юрий', 'Юра', 'Лёша')


class ReferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding='utf-8')
        cls.data = json.loads(re.search(r'var DATA = (\{.*?\});\n', cls.html, re.S).group(1))
        cls.rows = re.findall(r'<tr class="row" data-kr="([^"]+)" data-state="([^"]+)"', cls.html)

    def test_every_row_has_card(self):
        self.assertEqual(50, len(self.rows))
        self.assertEqual({k for k, _ in self.rows}, set(self.data))

    def test_outcomes_are_four(self):
        for kr, d in self.data.items():
            self.assertIn(d['state'], STATES, kr)
            self.assertEqual(STATES[d['state']], d['mark'], kr)
            self.assertEqual(d['pct'] is None, d['state'] == 'dropped', kr)

    def test_filter_counters_match_rows(self):
        """Счётчик на вкладке «Исход» — ровно число строк с этим исходом."""
        counts = collections.Counter(state for _, state in self.rows)
        shown = dict(re.findall(r'class="st-item"[^>]*data-state="(\w*)"[^>]*>.*?<span class="n">(\d+)<',
                                self.html))
        self.assertEqual(str(len(self.rows)), shown.pop(''))
        self.assertEqual({k: str(v) for k, v in counts.items()}, shown)

    def test_every_kr_has_next_action(self):
        for kr, d in self.data.items():
            self.assertTrue(d['next'].startswith(NEXT_FORMS), f'{kr}: {d["next"]}')

    def test_quarter_total_matches_data(self):
        """Итог в паспорте — среднее, взвешенное по PBV, по оценённым KR с весом."""
        rated = [(int(d['pbv']), d['pct']) for d in self.data.values()
                 if d['pct'] is not None and str(d['pbv']).isdigit()]
        weighted = sum(w * p for w, p in rated) / sum(w for w, _ in rated)
        self.assertEqual(92, round(weighted))
        self.assertIn(f'по {len(rated)} оценённым KR', self.html)

    def test_no_real_names(self):
        body = self.html[self.html.index('<body'):]
        hits = re.findall(rf'\b(?:{"|".join(FIRST_NAMES)})[а-яё]?\s+[А-ЯЁ][а-яё]+', body)
        self.assertEqual([], hits)
        self.assertNotIn('pageId', self.html)

    def test_target_describes_every_block(self):
        text = TARGET.read_text(encoding='utf-8')
        for block in ('Шапка и паспорт факта', 'Таблицы KR по целям', 'Карточка KR', 'Сводка',
                      'калибровка', 'Расхождения с ответами PO', 'Базовая линия', 'Критерии качества'):
            self.assertIn(block, text)


if __name__ == '__main__':
    unittest.main()
