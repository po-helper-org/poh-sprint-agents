#!/usr/bin/env python3
"""Раскладка статусов по бакетам — по правилам из status_rules.json.

Правила лежат данными, а не кодом, затем, что их читают двое: сборщик (чтобы
положить statusMap и посчитать разбивку velocity) и валидатор runner (чтобы
поймать дрейф workflow, ФТ-12.12). Одна копия правил — один источник истины.

Этот модуль — питонья реализация тех правил, общая для runner и сборщиков на
Python: часть контракта, а не деталь runner. Сборщик на другом языке читает
status_rules.json и повторяет порядок проверок (шесть строк, см. classify).
Путь к каталогу контракта runner передаёт в env ACTUAL_SPRINT_CONTRACT.
"""
import json
import os
import re
from pathlib import Path

ENV_RULES = 'ACTUAL_SPRINT_STATUS_RULES'
ENV_CONTRACT = 'ACTUAL_SPRINT_CONTRACT'
DEFAULT_RULES = Path(__file__).resolve().parent / 'status_rules.json'

# порядок фиксирован — он же порядок чисел в счётчике 2/0/3/0/5/1
BUCKETS = ('open', 'blocked', 'progress', 'testing', 'review', 'done')


class RulesNotFound(Exception):
    pass


def rules_path(explicit=None):
    """Порядок поиска: аргумент → env от runner → файл рядом с плагином."""
    contract = os.environ.get(ENV_CONTRACT)
    near_contract = Path(contract) / 'status_rules.json' if contract else None
    for candidate in (explicit, os.environ.get(ENV_RULES), near_contract, DEFAULT_RULES):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RulesNotFound(
        f'правила бакетов не найдены. Передайте путь к contract/status_rules.json '
        f'в переменной {ENV_RULES} или положите файл рядом со сборщиком.')


class Rules:
    def __init__(self, data, overrides=None, done_exact=None, categories=None,
                 done_categories=None, progress_categories=None):
        self.buckets = tuple(data.get('buckets') or BUCKETS)
        self.done_categories = set(done_categories if done_categories is not None
                                   else data.get('doneCategories', []))
        self.open_categories = set(data.get('openCategories', []))
        # по этим категориям считаются Lead/Cycle Time: «взяли в работу» и «закрыли»
        self.progress_categories = set(progress_categories if progress_categories is not None
                                       else data.get('progressCategories', []))
        self.categories = list(categories if categories is not None else data.get('categories', []))
        source = done_exact if done_exact is not None else data.get('doneExact', [])
        self.done_exact = {s.strip().lower() for s in source}
        self.rules = [(r['bucket'], re.compile(r['pattern'])) for r in data.get('rules', [])]
        # явная карта из params команды: «у нас "Ожидает релиза" на самом деле ревью»
        self.overrides = {k.strip().lower(): v for k, v in (overrides or {}).items()}
        bad = {k: v for k, v in self.overrides.items() if v not in self.buckets}
        if bad:
            raise ValueError(f'status_buckets: значения вне шести бакетов — {bad}')

    def classify(self, status, category):
        """(бакет, имя правила). Правило category-default — сигнал дрейфа workflow."""
        s = (status or '').strip().lower()
        if s in self.overrides:
            return self.overrides[s], 'override'
        if category in self.done_categories:
            return 'done', 'done-category'
        if s in self.done_exact:
            return 'done', 'done-exact'
        for bucket, rx in self.rules:
            if rx.search(s):
                return bucket, 'rule:' + bucket
        if category in self.open_categories:
            return 'open', 'category-default'
        return 'progress', 'category-default'

    def bucket(self, status, category):
        return self.classify(status, category)[0]

    def is_done(self, category):
        return category in self.done_categories

    def is_progress(self, category):
        return category in self.progress_categories

    def empty_counts(self):
        return dict.fromkeys(self.buckets, 0)


def load(path=None, overrides=None, done_exact=None, categories=None,
         done_categories=None, progress_categories=None):
    """Правила из файла; всё, что перечислено, переопределяется params команды (ФТ-15)."""
    data = json.loads(rules_path(path).read_text(encoding='utf-8'))
    return Rules(data, overrides, done_exact, categories, done_categories, progress_categories)
