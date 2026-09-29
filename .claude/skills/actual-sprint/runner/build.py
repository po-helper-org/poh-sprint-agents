#!/usr/bin/env python3
"""Сборка HTML: перенос заметок и подстановка TEAMS_JSON в шаблон.

Страница пишется атомарно (временный файл → замена), чтобы при ошибке сбора
прошлый отчёт остался нетронутым (ФТ-9).
"""
import json
import os
from pathlib import Path

PLACEHOLDER = '{{TEAMS_JSON}}'


class BuildError(Exception):
    pass


def read_notes(path):
    """Заметки прошлого запуска: {slug: {rowId: текст}}. Файл принадлежит человеку."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise BuildError(f'{path} не разбирается как JSON ({exc}). '
                         f'Это выгрузка кнопки «Заметки ⬇» — поправьте или уберите файл.') from exc
    if not isinstance(data, dict):
        raise BuildError(f'{path}: ожидается объект вида {{slug: {{rowId: текст}}}}')
    return data


def attach_notes(teams, notes):
    """Кладёт заметки команды в её поле notes. Возвращает, сколько подхвачено."""
    picked = 0
    for team in teams:
        bag = notes.get(team['slug'])
        if not isinstance(bag, dict):
            team.setdefault('notes', {})
            continue
        clean = {k: v for k, v in bag.items() if isinstance(v, str) and v.strip()}
        team['notes'] = clean
        picked += len(clean)
    return picked


def render(teams, template_path):
    tpl = Path(template_path).read_text(encoding='utf-8')
    if PLACEHOLDER not in tpl:
        raise BuildError(f'в шаблоне {template_path} нет плейсхолдера {PLACEHOLDER}')
    payload = json.dumps(teams, ensure_ascii=False, sort_keys=True)
    return tpl.replace(PLACEHOLDER, payload)


def snapshot(teams):
    """Тот же массив TEAMS, что уходит в страницу, — для PDF-статуса /sprint-status."""
    return json.dumps(teams, ensure_ascii=False, sort_keys=True, indent=1) + '\n'


def write_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)
    return path
