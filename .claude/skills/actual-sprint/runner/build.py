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
    """Заметки прошлой версии страницы: {slug: {rowId: текст}}. Файл принадлежит человеку.

    Страница больше не выгружает заметки файлом — они уходят промтом из корзины.
    Файл читается для переноса: страница один раз кладёт эти заметки в корзину.
    """
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise BuildError(f'{path} не разбирается как JSON ({exc}). '
                         f'Это выгрузка заметок прошлой версии страницы — поправьте или уберите файл.') from exc
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


# Поля, которые runner кладёт поверх данных сборщика: в хеш данных они не входят,
# иначе инсайды «устаревали» бы от собственного встраивания и от правки заметок.
OVERLAY_FIELDS = ('notes', 'insights')
INSIGHT_CHARTS = ('burndown', 'velocity', 'controlStories', 'controlSubtasks')


def team_digest(team):
    """sha256 данных команды без наложений runner'а — по нему инсайды привязаны к сбору."""
    import hashlib
    core = {k: v for k, v in team.items() if k not in OVERLAY_FIELDS}
    return hashlib.sha256(script_json(core).encode('utf-8')).hexdigest()


def read_insights(path):
    """Файл инсайдов навыка sprint-insights. Нет файла — нет инсайдов, это не ошибка.

    Полную проверку (схема, ключи задач, числа против фактов) делает
    `insights.py check`; здесь — только то, без чего страница сломается.
    """
    path = Path(path)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise BuildError(f'{path} не разбирается как JSON ({exc}). '
                         f'Это инсайды /sprint-insights — пересоздайте или уберите файл.') from exc
    if not isinstance(doc, dict) or not isinstance(doc.get('teams'), dict):
        raise BuildError(f'{path}: ожидается объект с полем teams — см. contract/insights.schema.json')
    return doc


def attach_insights(teams, doc):
    """Инсайды в поле insights команды — только если они написаны по этим же данным.

    Возвращает (приложено, устарело): slug'и команд. Устаревшие не показываются:
    интерпретация прошлого сбора рядом со свежими цифрами вводила бы в заблуждение.
    """
    attached, stale = [], []
    for team in teams:
        team.pop('insights', None)
        entry = (doc or {}).get('teams', {}).get(team['slug'])
        if not isinstance(entry, dict):
            continue
        if entry.get('dataHash') != team_digest(team):
            stale.append(team['slug'])
            continue
        charts = entry.get('charts') or {}
        team['insights'] = {
            'generatedAt': doc.get('generatedAt'),
            'author': doc.get('author'),
            'charts': {c: [i for i in charts.get(c) or [] if isinstance(i, dict) and i.get('text')]
                       for c in INSIGHT_CHARTS},
        }
        attached.append(team['slug'])
    return attached, stale


def insights_line(attached, stale):
    """Строка сводки runner'а про инсайды; пусто, если файла нет вовсе."""
    parts = []
    if attached:
        parts.append(f'инсайды ИИ: {", ".join(attached)}')
    if stale:
        parts.append(f'инсайды устарели (данные пересобраны): {", ".join(stale)} — /sprint-insights')
    return '   '.join(parts)


# Данные встраиваются прямо в <script>: текст из трекера («</script>», «<!--» в названии
# эпика) не должен закрыть блок. Вне строк JSON этих символов нет, внутри строк
# \uXXXX — та же строка для JSON.parse и для JS, поэтому данные не меняются.
_SCRIPT_UNSAFE = {'<': '\\u003c', '>': '\\u003e', '&': '\\u0026',
                  '\u2028': '\\u2028', '\u2029': '\\u2029'}


def script_json(value):
    """JSON, безопасный для вставки внутрь <script>…</script>."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return ''.join(_SCRIPT_UNSAFE.get(ch, ch) for ch in text)


def render(teams, template_path):
    tpl = Path(template_path).read_text(encoding='utf-8')
    if PLACEHOLDER not in tpl:
        raise BuildError(f'в шаблоне {template_path} нет плейсхолдера {PLACEHOLDER}')
    return tpl.replace(PLACEHOLDER, script_json(teams))


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
