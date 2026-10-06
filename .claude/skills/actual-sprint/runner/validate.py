#!/usr/bin/env python3
"""Проверка результата сборщика: схема, инварианты, выборка для сверки с JIRA.

Схема ловит форму (ФТ-11), инварианты — согласованность чисел между собой и с
конфигом (ФТ-12). Выборка (ФТ-13) — то, что ИИ потом руками сверяет с JIRA:
машина не может проверить, что «Ревью» в отчёте это и есть «Ревью» в трекере.
"""
import hashlib
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

CONTRACT = Path(__file__).resolve().parent.parent / 'contract'
RUNNER = Path(__file__).resolve().parent
for _p in (str(CONTRACT), str(RUNNER)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import buckets as buckets_mod
import config as config_mod
import mini_toml
import schema as schema_mod

BUCKET_SET = set(buckets_mod.BUCKETS)
INVARIANTS = 14


class Report:
    """Итог проверки одной команды: ошибки останавливают сбор, warnings — нет."""

    def __init__(self, slug):
        self.slug = slug
        self.schema_errors = []
        self.failed = []          # (номер инварианта, имя, текст)
        self.passed = 0
        self.warnings = []

    @property
    def ok(self):
        return not self.schema_errors and not self.failed

    @property
    def invariants_total(self):
        return self.passed + len(self.failed)

    def lines(self):
        out = []
        if self.schema_errors:
            out.append(f'схема          ✗ {len(self.schema_errors)} ошибок')
            for err in self.schema_errors[:10]:
                out.append(f'  [{self.slug}] {err}')
        else:
            out.append('схема          ✓')
        mark = '✓' if not self.failed else '✗'
        out.append(f'инварианты     {self.passed}/{self.invariants_total} {mark}')
        for num, name, text in self.failed:
            out.append(f'  [{self.slug}] инвариант {num} ({name}): {text}')
        if self.warnings:
            out.append(f'предупреждения {len(self.warnings)}')
            for w in self.warnings:
                out.append(f'  [{self.slug}] — {w}')
        return out


def _quoted(text):
    """Имя статуса из сообщения «статус «X» …» — по нему сверяем, не сказано ли уже."""
    left = text.find('«')
    right = text.find('»', left + 1)
    return text[left:right + 1] if left >= 0 and right > left else ''


def _parse_iso(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return mini_toml.parse_iso(value)
    except ValueError:
        return None


def _units(team):
    """Единицы подсчёта иерархии: (вид, задача, родитель).

    Родитель у истории — её эпик, у подзадачи — её история: в отчёте это
    единственный контекст, который нужен для сверки и сообщений об ошибках.
    """
    for epic in team.get('epics') or []:
        for story in epic.get('stories') or []:
            yield 'story', story, epic
            for sub in story.get('subtasks') or []:
                yield 'subtask', sub, story


def _title(unit):
    return unit.get('title') or unit.get('summary') or ''


def team_rules(cfg_team):
    """Правила бакетов с params команды: валидатор должен видеть ровно то, что сборщик."""
    params = getattr(cfg_team, 'params', None) or {}
    try:
        return buckets_mod.load(overrides=params.get('status_buckets') or {},
                                done_exact=params.get('done_statuses'),
                                categories=params.get('categories'),
                                done_categories=params.get('done_categories'),
                                progress_categories=params.get('progress_categories'))
    except (buckets_mod.RulesNotFound, ValueError):
        return None


def check(team, cfg_team=None, rules=None):
    """Схема + 14 инвариантов. Возвращает Report."""
    if rules is None:
        rules = team_rules(cfg_team)
    rep = Report(team.get('slug') if isinstance(team, dict) else '?')
    root = schema_mod.load_schema(config_mod.SCHEMA_PATH)
    rep.schema_errors = [str(e) for e in schema_mod.validate(team, root)]
    if rep.schema_errors:
        # инварианты по битой форме врут: числа могут отсутствовать вовсе
        return rep

    meta = team['_meta']
    collected = _parse_iso(meta['collectedAt'])
    checks = [
        ('совпадение с конфигом', lambda: _inv_config(team, cfg_team)),
        ('строки эпиков', lambda: _inv_rows(team)),
        ('уникальность ключей задач', lambda: _inv_keys(team)),
        ('категории статусов', lambda: _inv_categories(team, cfg_team)),
        ('даты смены статуса', lambda: _inv_status_changed(team, collected)),
        ('burndown', lambda: _inv_burndown(team, collected)),
        ('velocity', lambda: _inv_velocity(team)),
        ('metrics', lambda: _inv_metrics(team)),
        ('stats', lambda: _inv_stats(team)),
        ('диаграммы управления', lambda: _inv_control(team)),
        ('лента активности', lambda: _inv_logs(team, collected)),
        ('карта статусов', lambda: _inv_status_map(team)),
        ('выработка участников', lambda: _inv_output(team)),
        ('хронология историй', lambda: _inv_events(team)),
    ]
    assert len(checks) == INVARIANTS
    for i, (name, fn) in enumerate(checks, start=1):
        problems = fn() or []
        if problems:
            for text in problems:
                rep.failed.append((i, name, text))
        else:
            rep.passed += 1

    own = list(meta.get('warnings') or [])
    # сборщик обычно сам сообщает о дрейфе; повторять его же вывод — шум
    said = {w for w in own if 'бакет' in w}
    extra = [w for w in drift_warnings(team, rules)
             if not any(_quoted(w) and _quoted(w) in s for s in said)]
    rep.warnings = own + extra
    return rep


# ------------------------------------------------------------- инварианты

def _inv_config(team, cfg_team):
    """1. slug, team и boardId совпадают с конфигом."""
    if cfg_team is None:
        return []
    out = []
    for field, got, want in (('slug', team['slug'], cfg_team.slug),
                             ('team', team['team'], cfg_team.name),
                             ('boardId', team['boardId'], cfg_team.board)):
        if got != want:
            out.append(f'{field} в данных — {got!r}, в конфиге — {want!r}')
    return out


def _inv_rows(team):
    """2. rowId уникальны; псевдо-эпик один, с epicKey null и rowId no-epic."""
    out, seen, pseudo = [], set(), []
    for epic in team['epics']:
        row = epic['rowId']
        if row in seen:
            out.append(f'rowId «{row}» встречается больше одного раза')
        seen.add(row)
        if epic['epicKey'] is None or row == 'no-epic':
            pseudo.append(epic)
    if len(pseudo) > 1:
        out.append(f'псевдо-эпиков без эпика {len(pseudo)}, должен быть один')
    for epic in pseudo:
        if epic['rowId'] != 'no-epic' or epic['epicKey'] is not None:
            out.append(f'псевдо-эпик должен иметь rowId "no-epic" и epicKey null, '
                       f'получено rowId={epic["rowId"]!r} epicKey={epic["epicKey"]!r}')
    return out


def _inv_keys(team):
    """3. Ключи историй и подзадач уникальны во всём epics."""
    seen, dupes = set(), []
    for _, unit, _ in _units(team):
        key = unit['key']
        if key in seen:
            dupes.append(key)
        seen.add(key)
    if dupes:
        shown = ', '.join(sorted(set(dupes))[:5])
        return [f'ключи повторяются ({len(set(dupes))}): {shown}']
    return []


def _inv_categories(team, cfg_team):
    """4. category входит в допустимый набор категорий JIRA."""
    allowed = None
    if cfg_team is not None:
        allowed = cfg_team.params.get('categories')
    if allowed is None:
        allowed = buckets_mod.load().categories
    allowed = set(allowed)
    bad = {}
    for kind, unit, _ in _units(team):
        cat = unit.get('category')
        if cat not in allowed:
            bad.setdefault(cat, unit['key'])
    return [f'категория {cat!r} вне набора {sorted(allowed)} (например, {key})'
            for cat, key in bad.items()]


def _inv_status_changed(team, collected):
    """5. statusChanged разбирается как ISO-дата и не позже _meta.collectedAt."""
    out = []
    for kind, unit, _ in _units(team):
        raw = unit.get('statusChanged')
        if raw is None:
            continue
        when = _parse_iso(raw)
        if when is None:
            out.append(f'{unit["key"]}: statusChanged={raw!r} не разбирается как ISO-дата')
        elif collected and when > collected:
            out.append(f'{unit["key"]}: statusChanged {raw} позже _meta.collectedAt {team["_meta"]["collectedAt"]}')
    return out[:10]


def _inv_burndown(team, collected):
    """6. Дни идут подряд, remaining = scope − closed, closed ≤ scope, future согласован с now."""
    b = team['burndown']
    out, days = [], b['days']
    first, last = days[0]['date'], days[-1]['date']
    if first != b['start'] or last != b['end']:
        out.append(f'дни идут с {first} по {last}, а спринт заявлен {b["start"]}..{b["end"]}')
    expect = datetime.fromisoformat(first).date()
    for d in days:
        got = datetime.fromisoformat(d['date']).date()
        if got != expect:
            out.append(f'разрыв в днях: ожидался {expect.isoformat()}, получен {d["date"]}')
            expect = got
        expect += timedelta(days=1)
        if d['closed'] > d['scope']:
            out.append(f'{d["date"]}: closed {d["closed"]} больше scope {d["scope"]}')
        if d['remaining'] != d['scope'] - d['closed']:
            out.append(f'{d["date"]}: remaining {d["remaining"]} ≠ scope − closed '
                       f'({d["scope"]} − {d["closed"]})')
        if ('storyScope' in d) != ('storyClosed' in d):
            out.append(f'{d["date"]}: storyScope и storyClosed отдаются только парой')
        elif 'storyScope' in d and not (d['storyClosed'] <= d['storyScope'] <= d['scope']
                                        and d['storyClosed'] <= d['closed']):
            out.append(f'{d["date"]}: без подзадач {d["storyClosed"]}/{d["storyScope"]} не укладывается '
                       f'во все задачи {d["closed"]}/{d["scope"]}')
        if collected:
            want_future = d['date'] > collected.date().isoformat()
            if bool(d['future']) != want_future:
                out.append(f'{d["date"]}: future={d["future"]}, а относительно now '
                           f'({collected.date().isoformat()}) должно быть {want_future}')
    return out[:10]


def _inv_velocity(team):
    """7. done ≤ planned, сумма split равна planned; последний спринт — активный."""
    out = []
    sprints = team['velocity']['sprints']
    if sprints and sprints[-1]['name'] != team['sprintName']:
        out.append(f'последний спринт «{sprints[-1]["name"]}», а активный — «{team["sprintName"]}»: '
                   f'спринты идут от старого к новому')
    for s in team['velocity']['sprints']:
        if s['done'] > s['planned']:
            out.append(f'{s["name"]}: done {s["done"]} больше planned {s["planned"]}')
        total = sum(v for k, v in s['split'].items())
        if total != s['planned']:
            out.append(f'{s["name"]}: сумма split {total} ≠ planned {s["planned"]}')
        outside = sorted(set(s['split']) - BUCKET_SET)
        if outside:
            out.append(f'{s["name"]}: в split бакеты вне шести — {outside}')
        if s['split'].get('done') != s['done']:
            out.append(f'{s["name"]}: split.done {s["split"].get("done")} ≠ done {s["done"]}')
    return out


def _inv_metrics(team):
    """8. closed ≤ total по спринту, overall.total равен сумме по спринтам."""
    out = []
    sprints = team['metrics']['sprints']
    for s in sprints:
        if s['closed'] > s['total']:
            out.append(f'{s["name"]}: closed {s["closed"]} больше total {s["total"]}')
        # open, overall.closed и split.done проверяются как определения тех же чисел,
        # а не как дополнительные требования к сборщику
        if s['open'] != s['total'] - s['closed']:
            out.append(f'{s["name"]}: open {s["open"]} ≠ total − closed')
    overall = team['metrics']['overall']
    want = sum(s['total'] for s in sprints)
    if overall['total'] != want:
        out.append(f'overall.total {overall["total"]} ≠ сумме total по спринтам ({want})')
    want_closed = sum(s['closed'] for s in sprints)
    if overall['closed'] != want_closed:
        out.append(f'overall.closed {overall["closed"]} ≠ сумме closed по спринтам ({want_closed})')
    return out


def _inv_stats(team):
    """9. count равен числу точек, mean и median лежат в пределах min..max."""
    out = []
    for s in team['metrics']['sprints']:
        points, st = s['points'], s['lead']
        if st is None:
            if points:
                out.append(f'{s["name"]}: точек {len(points)}, а lead пуст')
            continue
        if st['count'] != len(points):
            out.append(f'{s["name"]}: lead.count {st["count"]} ≠ числу точек {len(points)}')
        if points:
            lo, hi = min(points), max(points)
            for field in ('mean', 'median'):
                if not (lo - 0.05 <= st[field] <= hi + 0.05):
                    out.append(f'{s["name"]}: lead.{field} {st[field]} вне диапазона точек {lo}..{hi}')
    for group in ('stories', 'subtasks'):
        c = team['control'][group]
        cycles = [p['cycle'] for p in c['points']]
        if not cycles:
            continue
        lo, hi = min(cycles), max(cycles)
        for field in ('mean', 'median'):
            if field in c and not (lo - 0.05 <= c[field] <= hi + 0.05):
                out.append(f'control.{group}.{field} {c[field]} вне диапазона cycle {lo}..{hi}')
    return out


def _inv_control(team):
    """10. Ключи точек уникальны и идут по doneAt; у непустой выборки есть статистика;
    outlier = cycle > limit, у риска elapsed > median."""
    out = []
    for group in ('stories', 'subtasks'):
        c = team['control'][group]
        if c['points']:
            lacking = [f for f in ('mean', 'median', 'sd', 'limit') if f not in c]
            if lacking:
                out.append(f'control.{group}: точки есть, а {", ".join(lacking)} нет — порог и коридор не построить')
            dates = [p['doneAt'] for p in c['points']]
            if dates != sorted(dates):
                out.append(f'control.{group}: точки не по возрастанию doneAt')
        keys = [p['key'] for p in c['points']]
        if len(keys) != len(set(keys)):
            dupes = sorted({k for k in keys if keys.count(k) > 1})[:5]
            out.append(f'control.{group}: ключи точек повторяются — {dupes}')
        limit = c.get('limit')
        if limit is not None:
            for p in c['points']:
                if 'outlier' not in p:
                    out.append(f'control.{group}.{p["key"]}: нет флага outlier при заданном limit')
                elif bool(p['outlier']) != (p['cycle'] > limit):
                    out.append(f'control.{group}.{p["key"]}: outlier={p["outlier"]}, '
                               f'а cycle {p["cycle"]} против limit {limit}')
        median = c.get('median')
        if median is not None:
            for r in c['risks']:
                if not r['elapsed'] > median:
                    out.append(f'control.{group}.{r["key"]}: elapsed {r["elapsed"]} '
                               f'не больше медианы {median} — это не зона риска')
    return out[:10]


def _inv_logs(team, collected):
    """11. События отсортированы по убыванию, попадают в окно, счётчики сходятся."""
    out = []
    logs = team['logs']
    events = logs['events']
    stamps = []
    for e in events:
        when = _parse_iso(e['at'])
        if when is None:
            out.append(f'{e["key"]}: at={e["at"]!r} не разбирается как ISO-дата')
        stamps.append(when)
    clean = [s for s in stamps if s]
    if clean != sorted(clean, reverse=True):
        out.append('события не отсортированы по at по убыванию')
    if collected:
        since = collected - timedelta(days=logs['days'])
        late = [e for e, s in zip(events, stamps) if s and s > collected]
        early = [e for e, s in zip(events, stamps) if s and s < since]
        if late:
            out.append(f'{len(late)} событий позже now (например, {late[0]["key"]} в {late[0]["at"]})')
        if early:
            out.append(f'{len(early)} событий старше окна {logs["days"]} дн. '
                       f'(например, {early[0]["key"]} в {early[0]["at"]})')
    kinds, authors = {}, {}
    for e in events:
        kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
        authors[e['author']] = authors.get(e['author'], 0) + 1
    if kinds != logs['kinds']:
        out.append(f'kinds {logs["kinds"]} не сходится с событиями {kinds}')
    got = {name: n for name, n in logs['authors']}
    if got != authors:
        out.append('authors не сходится с событиями')
    return out[:10]


def _inv_status_map(team):
    """12. Значения statusMap входят в 6 бакетов; карта покрывает встреченные статусы."""
    out = []
    smap = team.get('statusMap')
    if not smap:
        return []
    bad = {k: v for k, v in smap.items() if v not in BUCKET_SET}
    if bad:
        out.append(f'значения вне шести бакетов: {bad}')
    missing = sorted({unit['status'] for _, unit, _ in _units(team)
                      if unit['status'] not in smap})
    if missing:
        out.append(f'statusMap не покрывает статусы из данных: {missing[:5]}')
    return out


def _inv_output(team):
    """13. Выработка: unit согласован с field, спринты от старого к новому и последний —
    активный, число задач по бакету в split равно числу items с этим бакетом."""
    out = []
    o = team.get('output')
    if not o:
        return []
    if (o['unit'] == 'SP') != bool(o['field']):
        out.append(f'unit «{o["unit"]}» при field {o["field"]!r}: SP — только с полем Story Points')
    sprints = o['sprints']
    current = [i for i, s in enumerate(sprints) if s['current']]
    if len(current) > 1:
        out.append(f'активных спринтов {len(current)}, должен быть один')
    elif current and (current[0] != len(sprints) - 1 or sprints[-1]['name'] != team['sprintName']):
        out.append(f'активный спринт должен быть последним и называться «{team["sprintName"]}»')
    starts = [s.get('start') for s in sprints if s.get('start')]
    if starts != sorted(starts):
        out.append('спринты не по возрастанию start')
    for s in sprints:
        for m in s['members']:
            if 'items' not in m:
                continue
            got = {}
            for it in m['items']:
                got[it['bucket']] = got.get(it['bucket'], 0) + 1
            want = {b: v[0] for b, v in m['split'].items() if v[0]}
            if got != want:
                out.append(f'{s["name"]} · {m["name"]}: задач в split {want}, в items {got}')
    return out[:10]


def _inv_events(team):
    """14. Хронология истории: по возрастанию at, события — самой истории или её подзадач."""
    out = []
    for epic in team['epics']:
        for st in epic['stories']:
            events = st.get('events')
            if not events:
                continue
            stamps = [e['at'] for e in events]
            if stamps != sorted(stamps):
                out.append(f'{st["key"]}: события не по возрастанию at')
            own = {st['key']} | {sub['key'] for sub in st['subtasks']}
            alien = sorted({e['key'] for e in events} - own)
            if alien:
                out.append(f'{st["key"]}: события чужих задач {alien[:3]}')
    return out[:10]


def drift_warnings(team, rules=None):
    """Детектор дрейфа workflow (ФТ-12.12): статус, попавший в «В работе» по умолчанию.

    Молча уехать в progress может и новый статус, который команда ещё не описала,
    и опечатка в workflow. Лечится строкой в params.status_buckets.

    Своя карта своего сборщика — это и есть «покрыт картой»: команда решила за
    свой workflow сама. У базового сборщика карта выведена из тех же правил
    плагина, поэтому там она ничего не добавляет и проверка остаётся в силе.
    """
    if rules is None:
        try:
            rules = buckets_mod.load()
        except buckets_mod.RulesNotFound:
            return []
    own_map = team.get('statusMap') or {}
    collector = (team.get('_meta') or {}).get('collector')
    covered = set(own_map) if collector not in (None, 'base') else set()
    seen, out = {}, []
    for _, unit, _ in _units(team):
        seen.setdefault(unit['status'], unit.get('category'))
    for status, category in sorted(seen.items()):
        if status in covered:
            continue
        bucket, rule = rules.classify(status, category)
        if rule == 'category-default' and bucket == 'progress':
            out.append(f'статус «{status}» не покрыт правилами бакетов → progress. '
                       f'Опишите его в params.status_buckets, если это не «в работе».')
    return out


# ------------------------------------------------------------- покрытие экранов

# Какой экран страниц от каких полей JSON команды зависит. Схема говорит, какая форма
# допустима; покрытие — хватит ли данных, чтобы экран был не пустым. Список синхронен
# с sprint-data/reference/render.md (там же — что страница с этими полями делает).
# Путь: «a.b» — поле, «a[]» — каждый элемент массива, «a.*» — каждое значение объекта.
# Поле считается отданным, если хоть одно значение по пути не null и не пусто.
COVERAGE = (
    # страница, экран, поля, что видно без них
    ('отчёт PO', 'таблица эпиков, панель эпика', ('epics[].stories[]',), 'таблица пуста'),
    ('отчёт PO', 'исполнитель и возраст статуса в панели', ('epics[].stories[].assignee', 'epics[].stories[].statusChanged',
                                                            'epics[].stories[].subtasks[].assignee'), '«—» вместо инициалов и возраста'),
    ('отчёт PO', 'приоритет задач и эпиков', ('epics[].stories[].priority', 'epics[].epicPriority'), 'глиф «·»'),
    ('отчёт PO', 'Lead Time в шапке', ('metrics.overall.lead',), '«—»'),
    ('отчёт PO', 'метрики: burndown спринта', ('burndown.days[]',), 'график пуст'),
    ('отчёт PO', 'метрики: производительность', ('velocity.sprints[]',), 'график пуст'),
    ('отчёт PO', 'метрики: диаграммы управления', ('control.stories.points[]', 'control.subtasks.points[]'), '«Нет закрытых»'),
    ('отчёт PO', 'лента «Logs»', ('logs.events[]',), 'лента пуста'),
    ('отчёт PO', '«Команда: N участников»', ('output.sprints[].members[]', 'output.lead.*'), 'ссылки «Команда» нет'),
    ('отчёт PO', 'задачи участника по клику', ('output.sprints[].members[].items[]',), '«нужен сборщик 1.4.0+»'),
    ('отчёт PO', '«Весь эпик» и сгорание эпика', ('epics[].scope[]', 'epics[].scope[].created', 'epics[].scope[].doneAt'),
     'кнопки «Смотреть весь эпик» нет'),
    ('отчёт PO', 'сгорание эпика: основа SP', ('epics[].scope[].sp',), 'все задачи «без оценки»'),
    ('отчёт PO', 'сгорание эпика: по подзадачам', ('epics[].scope[].subtasks[].created', 'epics[].scope[].subtasks[].doneAt'),
     'режим подзадач пуст'),
    ('отчёт PO', 'плановая дата эпика', ('epics[].epicDue',), 'нет красной линии «план» и итога в днях'),
    ('презентация', 'титул и слайд команды', ('epics[].stories[]', 'burndown.days[]'), 'нет сводки'),
    ('презентация', 'слайд команды: SP за спринт', ('output.field', 'output.sprints[].members[]'), 'без SP'),
    ('презентация', 'слайды целей: строки-направления', ('epics[].stories[]', 'epics[].stories[].statusChanged'), 'нет строк'),
    ('презентация', 'клик по строке: истории спринта и весь эпик', ('epics[].scope[]', 'epics[].epicDue'), 'только истории спринта'),
    ('презентация', 'клик по истории: календарь и хронология', ('epics[].stories[].events[]',), 'события только из ленты спринта'),
    ('презентация', 'операционный: производительность', ('output.sprints[].members[]',), 'velocity в задачах вместо SP'),
    ('презентация', 'операционный: сгорание спринта', ('burndown.days[]', 'burndown.days[].storyScope'),
     'без storyScope — «нужна версия 1.10.0»'),
    ('презентация', 'операционный: истории, подзадачи и SP по участникам',
     ('epics[].stories[].assignee', 'epics[].stories[].subtasks[].assignee', 'epics[].stories[].subtasks[].statusChanged'),
     'всё у «Не назначен», застрявших нет'),
    ('презентация', '«Сроки»: cycle time по спринтам', ('control.stories.points[]', 'control.subtasks.points[]',
                                                       'output.sprints[].start'), 'нет точек / полос спринтов'),
    ('презентация', '«Сроки»: время в статусах', ('output.sprints[].timeInStatus',), '«нужна версия 1.8.0»'),
    ('презентация', '«Сроки»: разбор, зона риска', ('control.stories.risks[]', 'control.subtasks.risks[]'), 'зона риска пуста'),
    ('презентация', '«Планы на следующий спринт»', ('epics[].scope[]', 'epics[].scope[].priority'), 'колонка из бизнес-блока или пуста'),
    ('PDF-статус', 'KPI, burndown, «Внимание»', ('burndown.days[]', 'epics[].stories[].statusChanged',
                                                  'control.stories.risks[]'), 'без темпа и «без движения»'),
)


def _values(node, parts):
    """Все значения по пути (см. COVERAGE)."""
    if not parts:
        yield node
        return
    head, rest = parts[0], parts[1:]
    if node is None:
        return
    if head == '*':
        if isinstance(node, dict):
            for v in node.values():
                yield from _values(v, rest)
        return
    each = head.endswith('[]')
    name = head[:-2] if each else head
    if not isinstance(node, dict) or name not in node:
        return
    value = node[name]
    if each:
        for item in value if isinstance(value, list) else []:
            yield from _values(item, rest)
    else:
        yield from _values(value, rest)


def given(team, path):
    """Поле отдано: хоть одно значение по пути не null и не пусто."""
    return any(v is not None and v != [] and v != {} and v != ''
               for v in _values(team, path.split('.')))


def coverage(team):
    """[(страница, экран, состояние, нет_полей, что_видно)]: состояние — есть | частично | нет."""
    out = []
    for page, screen, paths, empty in COVERAGE:
        missing = [p for p in paths if not given(team, p)]
        state = 'нет' if len(missing) == len(paths) else 'частично' if missing else 'есть'
        out.append((page, screen, state, missing, empty))
    return out


def coverage_lines(team, full=False):
    """Строки покрытия для печати: по умолчанию — только экраны с пробелами."""
    rows = coverage(team)
    gaps = [r for r in rows if r[2] != 'есть']
    out = [f'покрытие экранов {len(rows) - len(gaps)}/{len(rows)}' + (' ✓' if not gaps else '')]
    for page, screen, state, missing, empty in (rows if full else gaps):
        mark = {'есть': '✓', 'частично': '◐', 'нет': '✗'}[state]
        line = f'  {mark} {page}: {screen}'
        if missing:
            line += f' — нет {", ".join(missing)} → {empty}'
        out.append(line)
    return out


# ------------------------------------------------------------- выборка ФТ-13

def sample(team, n=5, seed=None):
    """N задач с полями для сверки с JIRA. Затравка фиксирована — выборка повторяема."""
    if seed is None:
        material = f'{team["slug"]}:{team.get("sprintName", "")}'.encode()
        seed = int(hashlib.sha256(material).hexdigest()[:8], 16)
    rows = []
    for kind, unit, parent in _units(team):
        row = {'key': unit['key'], 'kind': kind, 'status': unit['status'],
               'category': unit.get('category', ''), 'title': _title(unit)}
        if kind == 'story':
            row['epic'] = parent.get('epicKey')
            row['assignee'] = unit.get('assignee')
        else:
            row['parent'] = parent['key']
            row['assignee'] = unit.get('assignee')
        rows.append(row)
    rnd = random.Random(seed)
    picked = rnd.sample(rows, min(n, len(rows)))
    picked.sort(key=lambda r: r['key'])
    return picked, seed


def format_sample(rows):
    out = []
    for r in rows:
        line = (f'  {r["key"]:10} {r["kind"]:8} status=«{r["status"]}»  '
                f'category=«{r["category"]}»')
        if r['kind'] == 'story':
            line += f'  epic={r["epic"] or "—"}'
        else:
            line += f'  parent={r["parent"]}'
        line += f'  assignee=«{r["assignee"] or "—"}»'
        out.append(line)
    return out
