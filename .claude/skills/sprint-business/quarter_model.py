"""Риски квартала: инициативы, шанс к концу квартала, блокаторы, статус, эскалации, смещение.

Чистая функция build() над уже собранными данными — без Jira и файлов. Правила — docs/quarter-risks.md,
термины — GLOSSARY.md. Даты в результате — объекты date; в JSON их пишет вызывающий.
"""
import hashlib
import re
import zlib
from datetime import date, datetime, timedelta

import forecast as fc

WINDOW = 12            # недель истории темпа
BLOCKER_DAYS = 3       # рабочих дней в ожидании — блокатор (как «✋ Блокаторы» в /sprints)
RED_BLOCKER_DAYS = 10  # целый спринт без движения
ON_TRACK, EVEN = 0.85, 0.5
TOP_ESCALATIONS = 3

STATUSES = ('red', 'yellow', 'none', 'green', 'done')      # порядок строк в таблице
TITLES = {'red': 'Не успевает', 'yellow': 'Под риском', 'none': 'Нет прогноза', 'green': 'В срок',
          'done': 'Готово', 'dropped': 'Снята'}


def quarter_bounds(quarter):
    m = re.match(r'^(\d{4})Q([1-4])$', quarter or '')
    if not m:
        raise ValueError(f'квартал {quarter!r}: ожидается вид 2026Q4')
    year, q = int(m.group(1)), int(m.group(2))
    start = date(year, 3 * (q - 1) + 1, 1)
    nxt = date(year + (q == 4), (3 * q) % 12 + 1, 1)
    return start, nxt - timedelta(days=1)


def day(value):
    """'2026-10-05', '2026-10-05T12:00:00.000+0300' или date → date; пусто → None."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()


def workdays_between(start, end):
    """Рабочие дни (пн–пт) в [start, end)."""
    n, d = 0, start
    while d < end:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def ddmm(d, today=None):
    if not d:
        return '—'
    return d.strftime('%d.%m') if not today or d.year == today.year else d.strftime('%d.%m.%Y')


def plural(n, one, few, many):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def text_hash(esc):
    raw = '|'.join(str(esc.get(k) or '') for k in ('ask', 'who', 'by', 'ifNot'))
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]


# ------------------------------------------------------------------ строка инициативы

def blockers_of(items, today):
    out = []
    for it in items:
        if it.get('bucket') != 'blocked' or it.get('doneAt'):
            continue
        changed = day(it.get('statusChanged') or it.get('created'))
        days = workdays_between(changed, today) if changed else 0
        if days >= BLOCKER_DAYS:
            out.append({'key': it['key'], 'title': it.get('title', ''), 'status': it.get('status', ''),
                        'since': changed, 'days': days, 'assignee': it.get('assignee')})
    return sorted(out, key=lambda b: -b['days'])


def growth_of(items, q_start):
    at_start = sum(1 for it in items if day(it.get('created')) and day(it['created']) < q_start)
    added = sum(1 for it in items if day(it.get('created')) and day(it['created']) >= q_start)
    return min(1.0, added / at_start) if at_start else 0.0


def status_of(fcast, blockers, has_items):
    b = blockers[0]['days'] if blockers else 0
    p = fcast.get('chance') if fcast.get('status') in ('ok', 'thin') else None
    if (p is not None and p < EVEN) or b >= RED_BLOCKER_DAYS:
        return 'red'
    if (p is not None and p < ON_TRACK) or b >= BLOCKER_DAYS:
        return 'yellow'
    if p is None or not has_items:
        return 'none'
    return 'green'


def auto_escalation(row, deadline, monday, today):
    """Текст эскалации из данных — пока агент не написал свой."""
    nxt = monday + timedelta(weeks=1)
    if row['blockers']:
        b = row['blockers'][0]
        by = row['okUntil'] if row['okUntil'] and row['okUntil'] > monday else nxt
        if_not = (f'с 85% — не раньше {ddmm(row["p85"], today)}' if row['p85'] else
                  'шанс дойти к концу квартала продолжит падать')
        return {'ask': f'снять блокатор {b["key"]}: «{b["status"]}» {b["days"]} раб. дн.',
                'who': 'уточнить, кого ждём', 'by': by, 'ifNot': if_not,
                'why': f'стоит {b["days"]} раб. дн., шанс к {ddmm(deadline)} — {pct(row["chance"])}'}
    return {'ask': f'решение по объёму или сроку: к {ddmm(deadline)} с 85% успеем '
                   f'{row["howMany85"]} из {row["open"]} {plural(row["open"], "задачи", "задач", "задач")}',
            'who': 'CPO', 'by': nxt,
            'ifNot': (f'с 85% — не раньше {ddmm(row["p85"], today)}' if row['p85'] else 'инициатива не закончится в квартале'),
            'why': f'шанс к {ddmm(deadline)} — {pct(row["chance"])}'}


def pct(p):
    return '—' if p is None else f'{round(p * 100)}%'


def path_to_green(row, monday):
    if row['status'] in ('green', 'done'):
        return ''
    if row['note']:
        return ''
    if not row['total']:
        return 'декомпозировать эпик: задач нет'
    if row['blockers']:
        by = row['okUntil'] if row['okUntil'] and row['okUntil'] > monday else monday + timedelta(weeks=1)
        return f'снять блокатор до {ddmm(by)}'
    if row['chance'] is None:
        return f'нужна история темпа: {row["points"]} нед. из {fc.MIN_POINTS}'
    if row['chance'] < ON_TRACK and row['howMany85'] < row['open']:
        cut = row['open'] - row['howMany85']
        return f'снять {cut} из {row["open"]} {plural(row["open"], "задачи", "задач", "задач")} из квартала или сдвинуть срок'
    return ''


def team_samples(epics, monday, open_count):
    done = [day(it.get('doneAt')) for e in epics for it in e.get('items', []) if it.get('doneAt')]
    created = [day(it.get('created')) for e in epics for it in e.get('items', []) if it.get('created')]
    counts = fc.weekly_throughput(done, monday, WINDOW, since=min(created) if created else None)
    return [c / max(1, open_count) for c in counts]


def build_row(slug, team_name, key, obj, goals_t, epic, today, monday, q_start, deadline, team_pace):
    kr = (goals_t.get('kr') or {}).get(key)
    base = {'key': key, 'team': slug, 'teamName': team_name, 'obj': obj,
            'objTitle': (goals_t.get('objectives') or {}).get(obj), 'kr': kr,
            'title': (epic or {}).get('title') or key, 'due': day((epic or {}).get('due')),
            'note': '', 'blockers': [], 'items': [], 'total': 0, 'open': 0, 'done': 0, 'lastWeek': 0,
            'chance': None, 'p50': None, 'p85': None, 'p95': None, 'howMany85': 0, 'okUntil': None,
            'method': None, 'points': 0, 'growth': 0.0, 'risks': [], 'override': None, 'escalation': None,
            'delta': None, 'epicStatus': (epic or {}).get('status')}
    if epic is None:
        return {**base, 'status': 'none', 'computedStatus': 'none', 'note': 'нет данных из Jira'}
    items = [it for it in epic.get('items') or [] if not it.get('subtask')]
    open_items = [it for it in items if not it.get('doneAt') and it.get('bucket') != 'done']
    done_dates = [day(it['doneAt']) for it in items if it.get('doneAt')]
    created = [day(it['created']) for it in items if it.get('created')]
    own = fc.weekly_throughput(done_dates, monday, WINDOW, since=min(created) if created else None)
    row = {**base, 'items': open_items, 'total': len(items), 'open': len(open_items), 'done': len(items) - len(open_items),
           'lastWeek': own[-1] if own else 0, 'growth': growth_of(items, q_start),
           'blockers': blockers_of(open_items, today)}
    if items and not open_items or (epic.get('bucket') == 'done' and not open_items):
        return {**row, 'status': 'done', 'computedStatus': 'done'}
    samples, method = own, 'own'
    if len(own) < fc.MIN_POINTS or not any(own):
        samples, method = team_pace, 'team'
    seed = zlib.crc32(f'{key}:{today.isoformat()}'.encode())
    f = fc.forecast(len(open_items), samples, monday, deadline, growth=row['growth'], seed=seed) if open_items else {'status': 'no_data'}
    if f['status'] in ('ok', 'thin'):
        row.update({k: f[k] for k in ('chance', 'p50', 'p85', 'p95', 'okUntil')})
        row.update({'howMany85': min(len(open_items), int(f['howMany85'])), 'method': method,
                    'points': f['points'], 'thin': f['status'] == 'thin'})
    else:
        row['points'] = len(own)
    status = status_of(f, row['blockers'], bool(items))
    return {**row, 'status': status, 'computedStatus': status}


# ------------------------------------------------------------------ квартал

def build(goals, data, block=None, approvals=None, history=None, today=None):
    """Вид страницы: строки по командам, эскалации, кандидаты, итоги, снимок недели для смещения."""
    today = today or day(data.get('fetchedAt')) or date.today()
    monday = fc.week_monday(today)
    quarter = data.get('quarter') or next((g.get('quarter') for g in goals.values() if g.get('quarter')), None)
    q_start, deadline = quarter_bounds(quarter)
    approvals = approvals or {}
    prev = (history or {}).get('rows') or {}
    by_slug = {t['slug']: t for t in data.get('teams', [])}
    teams, unconfirmed, dropped, candidates, approved = [], [], [], [], []
    for slug, goals_t in goals.items():
        team = by_slug.get(slug) or {'slug': slug, 'name': slug.upper(), 'epics': []}
        epics = {e['key']: e for e in team.get('epics', [])}
        keys = list((goals_t.get('epics') or {}).items())
        skip = set(goals_t.get('unconfirmed') or []) | set(goals_t.get('dropped') or [])
        open_count = sum(1 for k, _ in keys if k not in skip and any(
            not it.get('doneAt') and it.get('bucket') != 'done' for it in (epics.get(k) or {}).get('items', [])))
        pace = team_samples([epics[k] for k, _ in keys if k in epics], monday, open_count)
        agent = (((block or {}).get('teams') or {}).get(slug) or {}).get('initiatives') or {}
        rows = []
        for key, obj in keys:
            row = build_row(slug, team.get('name') or slug.upper(), key, obj, goals_t, epics.get(key),
                            today, monday, q_start, deadline, pace)
            mine = agent.get(key) or {}
            row['risks'] = [r for r in mine.get('risks') or [] if r.get('roam') != 'Resolved']
            if mine.get('override'):
                row['status'], row['override'] = mine['override']['status'], mine['override'].get('reason', '')
            row['path'] = path_to_green(row, monday)
            if key in (goals_t.get('dropped') or []):
                dropped.append({**row, 'status': 'dropped'})
                continue
            if key in (goals_t.get('unconfirmed') or []):
                unconfirmed.append(row)
                continue
            esc = None
            if mine.get('escalation'):
                esc = {**mine['escalation'], 'by': day(mine['escalation'].get('by')), 'source': 'agent'}
            elif row['status'] in ('red', 'yellow') and (row['blockers'] or (row['chance'] is not None and row['chance'] < EVEN)):
                esc = {**auto_escalation(row, deadline, monday, today), 'source': 'data'}
            if esc:
                esc.update({'key': key, 'team': slug, 'teamName': row['teamName'], 'kr': row['kr'],
                            'title': row['title'], 'status': row['status'], 'chance': row['chance']})
                esc['hash'] = text_hash({**esc, 'by': esc['by'].isoformat() if esc['by'] else ''})
                esc['approved'] = approvals.get(key) == esc['hash']
                row['escalation'] = esc
                (approved if esc['approved'] else candidates).append(esc)
            row['delta'] = delta(row, prev.get(key))
            rows.append(row)
        rows.sort(key=lambda r: (STATUSES.index(r['status']), -(r['blockers'][0]['days'] if r['blockers'] else 0),
                                 r['chance'] if r['chance'] is not None else 2))
        teams.append({'slug': slug, 'name': team.get('name') or slug.upper(), 'rows': rows,
                      'warnings': team.get('warnings') or []})
    approved.sort(key=lambda e: (e['by'] or date.max, e['key']))
    candidates.sort(key=lambda e: (STATUSES.index(e['status']), e['by'] or date.max, e['key']))
    all_rows = [r for t in teams for r in t['rows']]
    counts = {s: sum(1 for r in all_rows if r['status'] == s) for s in STATUSES}
    return {
        'quarter': quarter, 'today': today, 'monday': monday, 'qStart': q_start, 'deadline': deadline,
        'weeksLeft': fc.weeks_until(monday, deadline), 'fetchedAt': data.get('fetchedAt'),
        'teams': teams, 'unconfirmed': unconfirmed, 'dropped': dropped, 'counts': counts,
        'escalations': approved[:TOP_ESCALATIONS], 'moreEscalations': max(0, len(approved) - TOP_ESCALATIONS),
        'candidates': candidates,
        'shifted': sum(1 for r in all_rows if r['delta'] and (r['delta'].get('p85Days') or 0) > 0),
        'previousWeek': (history or {}).get('week'),
        'snapshot': {'week': monday.isoformat(), 'rows': {r['key']: {
            'status': r['status'], 'p85': r['p85'].isoformat() if r['p85'] else None, 'chance': r['chance'],
            'blockers': [b['key'] for b in r['blockers']]} for r in all_rows}},
    }


def delta(row, prev):
    if not prev:
        return None
    was = day(prev.get('p85'))
    now_keys = [b['key'] for b in row['blockers']]
    old_keys = prev.get('blockers') or []
    return {'p85Days': (row['p85'] - was).days if row['p85'] and was else None,
            'statusWas': prev.get('status') if prev.get('status') != row['status'] else None,
            'chanceWas': prev.get('chance'),
            'newBlockers': [k for k in now_keys if k not in old_keys],
            'resolvedBlockers': [k for k in old_keys if k not in now_keys]}
