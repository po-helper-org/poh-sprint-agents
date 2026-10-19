#!/usr/bin/env python3
"""Блокаторы спринта — наложение runner'а поверх данных сборщика (раздел «✋ Блокаторы»).

Блокатор — незакрытая задача спринта (история или подзадача), которая стоит:
  · wait  — «в ожидании»: статус в бакете blocked; стоит с последней смены статуса;
  · stale — «без движения»: задача в работе / тесте / ревью, по которой STALE_DAYS+
            рабочих дней ни смены статуса, ни комментария. История движется вместе
            со своими подзадачами; если у истории есть подзадачи в работе или в ожидании,
            «без движения» считаются они, а не история (дни не задваиваются).

Дни — рабочие (пн–пт) от начала стоянки до дня сбора (_meta.collectedAt), не системные
часы: страница, пересобранная завтра из того же снимка, покажет те же числа.
Бакет — из statusMap команды (как на странице), нет карты — правила контракта.
Это расчёт, не данные: в хеш команды не входит (build.OVERLAY_FIELDS).
"""
import sys
from datetime import date, timedelta
from pathlib import Path

_CONTRACT = str(Path(__file__).resolve().parent.parent / 'contract')
if _CONTRACT not in sys.path:   # правила бакетов — часть контракта, рядом с runner
    sys.path.insert(0, _CONTRACT)
import buckets as buckets_mod  # noqa: E402

STALE_DAYS = 3
ACTIVE = ('progress', 'testing', 'review')
NO_EPIC = 'Без эпика'
NOBODY = 'Не назначен'


def _day(value):
    """Дата из ISO-строки трекера (с поясом или без) — до дня; мусор → None."""
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def workdays(a, b):
    """Рабочих дней с a до b: пт → пн = 1, тот же день = 0. Принимает date или ISO-строки."""
    a = _day(a) if isinstance(a, str) else a
    b = _day(b) if isinstance(b, str) else b
    if a is None or b is None or b <= a:
        return 0
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _bucketer(team):
    """Бакет статуса: statusMap команды, иначе правила контракта. Нет правил — ошибка, а не «всё в работе»."""
    smap = team.get('statusMap') or {}
    rules = buckets_mod.load()

    def bucket(status, category):
        return smap[status] if status in smap else rules.bucket(status, category)
    return bucket


def _last_comment(events):
    comments = [e for e in events if e.get('kind') == 'comment' and e.get('at')]
    if not comments:
        return None
    c = max(comments, key=lambda e: e['at'])
    return {'by': c.get('by'), 'at': c['at'], 'text': str(c.get('body') or '')[:300]}


def _latest(*stamps):
    days = [d for d in (_day(s) for s in stamps) if d]
    return max(days) if days else None


def team_blockers(team, stale_days=STALE_DAYS):
    """{asOf, staleDays, items[], byEpic[], byPerson[]} — что стоит в спринте команды."""
    today = _day((team.get('_meta') or {}).get('collectedAt')) or date.today()
    bucket = _bucketer(team)
    base = (team.get('jiraBase') or '').rstrip('/')
    items = []
    for epic in team.get('epics') or []:
        for st in epic.get('stories') or []:
            events = [e for e in st.get('events') or [] if isinstance(e, dict)]
            subs = [s for s in st.get('subtasks') or [] if isinstance(s, dict) and s.get('key')]
            open_subs = [s for s in subs if bucket(s.get('status'), s.get('category')) in ACTIVE + ('blocked',)]
            entries = [(st, 'story', events, st.get('title'))]
            entries += [(s, 'subtask', [e for e in events if e.get('key') == s['key']], s.get('summary'))
                        for s in subs]
            for it, kind, own, title in entries:
                if not it.get('key'):
                    continue
                b = bucket(it.get('status'), it.get('category'))
                if b == 'blocked':
                    why, since = 'wait', _day(it.get('statusChanged'))
                elif b in ACTIVE:
                    if kind == 'story' and open_subs:
                        continue   # работу ведут подзадачи — стоят они, а не история (иначе дни считались бы дважды)
                    stamps = [it.get('statusChanged')] + [e.get('at') for e in own]
                    if kind == 'story':   # движение подзадач — движение истории
                        stamps += [s.get('statusChanged') for s in subs]
                    since = _latest(*stamps)
                    if since is None or workdays(since, today) < stale_days:
                        continue
                    why = 'stale'
                else:
                    continue
                items.append({
                    'key': it['key'], 'kind': kind, 'title': str(title or it['key']).strip(),
                    'status': it.get('status'), 'why': why,
                    'since': since.isoformat() if since else None,
                    'days': workdays(since, today) if since else None,
                    'assignee': it.get('assignee') or None,
                    'epicKey': epic.get('epicKey'), 'epicTitle': epic.get('epicTitle') or (None if epic.get('epicKey') else NO_EPIC),
                    'rowId': epic.get('rowId'),
                    'url': f'{base}/browse/{it["key"]}' if base else None,
                    'comment': _last_comment(own),
                })
    # дольше стоит — выше; без даты начала — в конце
    items.sort(key=lambda b: (b['days'] is None, -(b['days'] or 0), b['key']))
    return {'asOf': today.isoformat(), 'staleDays': stale_days, 'items': items,
            'byEpic': _group(items, lambda b: (b['epicKey'], b['epicTitle'] or NO_EPIC, b['rowId']),
                             lambda k: {'key': k[0], 'title': k[1], 'rowId': k[2]}),
            'byPerson': _group(items, lambda b: b['assignee'] or NOBODY, lambda k: {'name': k})}


def _group(items, key, head):
    acc = {}
    for b in items:
        k = key(b)
        g = acc.setdefault(k, dict(head(k), count=0, days=0))
        g['count'] += 1
        g['days'] += b['days'] or 0
    return sorted(acc.values(), key=lambda g: (-g['days'], -g['count'], str(g.get('title') or g.get('name'))))


if __name__ == '__main__':   # быстрый взгляд на снимок: blockers.py reports/sprint-report.data.json
    import json
    for t in json.load(open(sys.argv[1], encoding='utf-8')):
        r = team_blockers(t)
        print(f"{t.get('slug')}: {len(r['items'])} блокаторов на {r['asOf']}")
        for b in r['items']:
            print(f"  {b['days'] if b['days'] is not None else '?':>3} {b['why']:5} {b['key']:12} {b['title'][:60]}")
