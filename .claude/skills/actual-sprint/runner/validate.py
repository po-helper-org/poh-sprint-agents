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
INVARIANTS = 12


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
    """Схема + 12 инвариантов. Возвращает Report."""
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
        if collected:
            want_future = d['date'] > collected.date().isoformat()
            if bool(d['future']) != want_future:
                out.append(f'{d["date"]}: future={d["future"]}, а относительно now '
                           f'({collected.date().isoformat()}) должно быть {want_future}')
    return out[:10]


def _inv_velocity(team):
    """7. done ≤ planned и сумма split равна planned."""
    out = []
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
    """10. Ключи точек уникальны, outlier = cycle > limit, у риска elapsed > median."""
    out = []
    for group in ('stories', 'subtasks'):
        c = team['control'][group]
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
