#!/usr/bin/env python3
"""Ожидания команды: из истории статусов задач — интервалы, где работа стояла.

Чистое ядро навыка sprint-blockers, без сети и без модели. На входе снимок задач
(его пишет blockers.py fetch), период и правила команды; на выходе факты — вход
для агента и для страницы.

Модель случая заимствована у калькулятора impediments из jira-agile-metrics
(DeloitteDigitalUK, MIT): ожидание — интервал в статусе-стадии, время в бэклоге и
в «Готово» не считается, итог — по периодам в задачах и днях. Отличия: стадий
несколько (приостановлено, ждёт ревью, теста, установки), считаем рабочие дни, а
не календарные, и без pandas — плагин ставится копированием файлов.

Правила счёта дней (сверены с эталоном отчёта о простоях):
  - день ожидания — рабочий день D, для которого начало <= D < конец (по датам):
    17.08–17.09 — 23 дня;
  - открытое ожидание идёт по дату отчёта включительно: «с 23.09» на 14.10 — 16;
  - «дни из N» по стадии или стороне — число рабочих дней, когда ждала хотя бы
    одна задача: ожидания идут одновременно, поэтому дни не складываются.
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone

VERSION = 1
MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август',
          'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
              'сентября', 'октября', 'ноября', 'декабря']

# Стадии ожидания и статусы по умолчанию. В истории JIRA статус может быть записан
# по-английски («On Hold»), а в карточке — по-русски («В ожидании»): нужны оба имени.
# Команда переопределяет любой список в [teams.params.blockers] конфига.
STAGES = (
    ('hold', 'Приостановлено', 'hold',
     ['On Hold', 'В ожидании', 'Blocked', 'Заблокировано', 'Ожидание', 'Waiting']),
    ('review', 'Ждёт ревью', 'queue',
     ['Review', 'Ревью', 'Code Review', 'In Review', 'Ожидает ревью', 'Ready for Review',
      'Ready to Check', 'Готово к проверке', 'Ready for Approval', 'Готово к утверждению']),
    ('test', 'Ждёт тестирования', 'queue',
     ['Ready for Test', 'Ready for testing', 'Готово к тестированию', 'Ожидает тестирование']),
    ('deploy', 'Ждёт установки', 'queue',
     ['Ready to Install', 'Готово к установке', 'Ready for Release']),
)
BLOCKING_LINKS = ['is blocked by', 'depends on', 'to be done after']
QUEUE_MIN_DAYS = 5      # очередь короче недели — обычный ход процесса, не случай
EVIDENCE_COMMENTS = 4
SNIPPET = 220
SIGNALS_MAX = 40
# комментарий «ждём / нет доступа», а статуса ожидания рядом нет — слабый сигнал
WAIT_WORDS = re.compile(r'жд[её]м|ожида|блок|нет доступ|не можем|зависим|не работает стенд|'
                        r'waiting|blocked', re.I)
KEY_RE = re.compile(r'\b[A-Z][A-Z0-9_]*-\d+\b')


class FactsError(ValueError):
    """Снимок или правила нельзя использовать. Текст готов к показу человеку."""


# ------------------------------------------------------------------ время

def parse_ts(value, tz):
    """Момент из JIRA в поясе команды. Форматы: ISO с '+03:00' / '+0300' / 'Z',
    '2026-08-31 16:12:13 MSK' (так отдаёт MCP)."""
    if not value:
        return None
    s = str(value).strip()
    m = re.match(r'^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?\s*([A-Z]{2,4})?$', s)
    if m and m.group(3):
        offset = {'MSK': 3, 'UTC': 0, 'GMT': 0}.get(m.group(3))
        if offset is None:
            raise FactsError(f'неизвестный пояс времени в {value!r}')
        base = datetime.fromisoformat(f'{m.group(1)}T{m.group(2)}')
        return base.replace(tzinfo=timezone(timedelta(hours=offset))).astimezone(tz)
    s = re.sub(r'Z$', '+00:00', s)
    s = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', s)
    s = re.sub(r'\.(\d{1,6})\d*(?=[+-]|$)', lambda x: '.' + x.group(1).ljust(6, '0'), s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise FactsError(f'момент времени не разбирается: {value!r}') from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def parse_tz(value):
    m = re.match(r'^([+-])(\d{2}):?(\d{2})$', value or '+03:00')
    if not m:
        raise FactsError(f'utc_offset {value!r}: ожидается вид +03:00')
    sign = 1 if m.group(1) == '+' else -1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def iso_day(d):
    return d.isoformat()


def workdays(start, end_excl, holidays):
    """Рабочие дни в [start, end_excl)."""
    out = []
    d = start
    while d < end_excl:
        if d.weekday() < 5 and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------------ период

def quarter_bounds(quarter):
    m = re.match(r'^(\d{4})Q([1-4])$', quarter or '')
    if not m:
        raise FactsError(f'квартал {quarter!r}: ожидается вид 2026Q3')
    year, q = int(m.group(1)), int(m.group(2))
    start = date(year, 3 * (q - 1) + 1, 1)
    nxt = date(year + (q == 4), (3 * q) % 12 + 1, 1)
    return start, nxt - timedelta(days=1)


def window_label(start, end):
    if start.day == 1 and (end + timedelta(days=1)).day == 1:
        if start.month == end.month:
            return MONTHS[start.month - 1].capitalize()
        return f'{MONTHS[start.month - 1].capitalize()}–{MONTHS[end.month - 1]}'
    if start.month == end.month:
        return f'{start.day}–{end.day} {MONTHS_GEN[end.month - 1]}'
    return f'{start.day} {MONTHS_GEN[start.month - 1]} – {end.day} {MONTHS_GEN[end.month - 1]}'


def period(quarter, to, holidays=()):
    """Квартал и хвост после него: два окна, как в эталоне — «июль–сентябрь» и
    «1–14 октября». Квартал ещё идёт — одно окно, по дату отчёта."""
    q_start, q_end = quarter_bounds(quarter)
    to_d = date.fromisoformat(to)
    if to_d < q_start:
        raise FactsError(f'дата отчёта {to} раньше начала квартала {quarter}')
    hol = {date.fromisoformat(h) for h in holidays}
    windows = []
    for wid, start, end in (('q', q_start, min(q_end, to_d)),
                            ('m', q_end + timedelta(days=1), to_d)):
        if start > end:
            continue
        windows.append({'id': wid, 'label': window_label(start, end), 'from': iso_day(start),
                        'to': iso_day(end), 'workdays': len(workdays(start, end + timedelta(days=1), hol))})
    return {'quarter': quarter, 'from': iso_day(q_start), 'to': to, 'holidays': sorted(holidays),
            'windows': windows}


# ------------------------------------------------------------------ правила

def rules(params):
    """Стадии и пороги команды: params — таблица [teams.params.blockers]."""
    params = params or {}
    stages = []
    for sid, name, kind, statuses in STAGES:
        names = params.get(sid, statuses)
        if not isinstance(names, list) or not all(isinstance(s, str) for s in names):
            raise FactsError(f'blockers.{sid}: ожидается список имён статусов')
        stages.append({'id': sid, 'name': name, 'kind': kind, 'statuses': names})
    by_status = {}
    for st in stages:
        for s in st['statuses']:
            key = s.strip().casefold()
            if key in by_status:
                raise FactsError(f'статус «{s}» указан в двух стадиях: {by_status[key]} и {st["id"]}')
            by_status[key] = st['id']
    skip = {s.strip().casefold() for s in params.get('skip', [])}
    return {'stages': stages, 'byStatus': by_status, 'skip': skip,
            'queueMinDays': int(params.get('queue_min_days', QUEUE_MIN_DAYS)),
            'blockingLinks': [s.casefold() for s in params.get('blocking_links', BLOCKING_LINKS)],
            'tz': parse_tz(params.get('utc_offset', '+03:00'))}


# ------------------------------------------------------------------ интервалы

def status_intervals(item, tz):
    """[(статус, начало, конец|None)] по истории; первый статус — до первого перехода."""
    log = sorted(item.get('statusLog') or [], key=lambda e: parse_ts(e['at'], tz))
    created = parse_ts(item.get('created'), tz)
    out = []
    cur = log[0]['from'] if log else item.get('status')
    since = created
    for entry in log:
        at = parse_ts(entry['at'], tz)
        if cur is not None and since is not None:
            out.append((cur, since, at))
        cur, since = entry['to'], at
    out.append((cur, since, None))
    return out


def trim(text, limit=SNIPPET):
    text = re.sub(r'\s+', ' ', text or '').strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def facts(snap, per, params=None):
    """Факты ожиданий команды за период: стадии, интервалы-кандидаты в случаи,
    слабые сигналы. Детерминированно: один снимок — один хеш."""
    rl = rules(params)
    tz = rl['tz']
    hol = {date.fromisoformat(h) for h in per.get('holidays', [])}
    to_d = date.fromisoformat(per['to'])
    start_d = date.fromisoformat(per['from'])
    report_end = to_d + timedelta(days=1)
    wins = [(w['id'], date.fromisoformat(w['from']), date.fromisoformat(w['to']) + timedelta(days=1))
            for w in per['windows']]
    stage_days = {st['id']: {wid: set() for wid, _, _ in wins} for st in rl['stages']}
    stage_task_days = {st['id']: {wid: 0 for wid, _, _ in wins} for st in rl['stages']}
    stage_tasks = {st['id']: {wid: set() for wid, _, _ in wins} for st in rl['stages']}
    items = {it['key']: it for it in snap.get('issues', [])}
    found = []
    for item in sorted(items.values(), key=lambda it: key_order(it['key'])):
        for status, since, until in status_intervals(item, tz):
            norm = (status or '').strip().casefold()
            if norm in rl['skip'] or norm not in rl['byStatus']:
                continue
            sid = rl['byStatus'][norm]
            first = since.date()
            last_excl = until.date() if until else report_end
            if last_excl <= start_d or first > to_d:
                continue
            # дни — только внутри периода отчёта; даты интервала — как в JIRA
            all_days = workdays(max(first, start_d), min(last_excl, report_end), hol)
            days = {'total': len(all_days)}
            for wid, w0, w1 in wins:
                inside = [d for d in all_days if w0 <= d < w1]
                days[wid] = len(inside)
                stage_days[sid][wid].update(inside)
                stage_task_days[sid][wid] += len(inside)
                if inside:
                    stage_tasks[sid][wid].add(item['key'])
            found.append({'item': item, 'stage': sid, 'status': status, 'since': since,
                          'until': until, 'days': days})
    waits = []
    for f in found:
        kind = next(st['kind'] for st in rl['stages'] if st['id'] == f['stage'])
        need = 1 if kind == 'hold' else rl['queueMinDays']
        if f['days']['total'] < need:
            continue
        item = f['item']
        waits.append({
            'id': f'w{len(waits) + 1}', 'key': item['key'], 'summary': trim(item.get('summary'), 120),
            'type': item.get('type'), 'parent': item.get('parent'),
            'stage': f['stage'], 'status': f['status'],
            'from': iso_day(f['since'].date()), 'to': iso_day(f['until'].date()) if f['until'] else None,
            'open': f['until'] is None, 'days': f['days'],
            'evidence': evidence(item, items, f['since'], f['until'], rl),
        })
    stages = []
    for st in rl['stages']:
        per_win = {}
        for wid, _, _ in wins:
            lengths = sorted(f['days'][wid] for f in found if f['stage'] == st['id'] and f['days'][wid])
            per_win[wid] = {'days': len(stage_days[st['id']][wid]), 'taskDays': stage_task_days[st['id']][wid],
                            'tasks': len(stage_tasks[st['id']][wid]),
                            'medianDays': median(lengths), 'longestDays': lengths[-1] if lengths else 0}
        seen = sorted({f['status'] for f in found if f['stage'] == st['id']})
        stages.append({'id': st['id'], 'name': st['name'], 'kind': st['kind'],
                       'statuses': seen, 'windows': per_win})
    out = {
        'version': VERSION,
        'team': snap.get('team', {}),
        'jiraBase': snap.get('jiraBase'),
        'period': per,
        'source': {'transport': snap.get('transport'), 'jql': snap.get('jql'),
                   'fetchedAt': snap.get('fetchedAt'), 'issues': len(items)},
        'rules': {'queueMinDays': rl['queueMinDays'], 'skip': sorted(params.get('skip', [])) if params else [],
                  'blockingLinks': [s for s in (params or {}).get('blocking_links', BLOCKING_LINKS)]},
        'stages': stages,
        'waits': waits,
        'signals': signals(items, found, start_d, to_d, tz),
    }
    out['factsHash'] = digest(out)
    return out


def key_order(key):
    proj, _, num = key.rpartition('-')
    return (proj, int(num) if num.isdigit() else 0)


def median(values):
    if not values:
        return 0
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else round((values[mid - 1] + values[mid]) / 2, 1)


def evidence(item, items, since, until, rl):
    """Почему стояла задача — что есть в JIRA рядом с интервалом: комментарии
    (задачи и родителя), связи «блокируется / зависит от»."""
    tz = rl['tz']
    lo = since - timedelta(days=2)
    hi = until or datetime.max.replace(tzinfo=tz)
    comments = []
    sources = [(item, None)]
    if item.get('parent') and item['parent'] in items:
        sources.append((items[item['parent']], item['parent']))
    for src, via in sources:
        for c in src.get('comments') or []:
            at = parse_ts(c.get('at'), tz)
            if at and lo <= at <= hi:
                entry = {'at': at.isoformat(timespec='minutes'), 'text': trim(c.get('body'))}
                if via:
                    entry['on'] = via
                comments.append(entry)
    # первым — комментарий у начала ожидания: в нём обычно и написано, чего ждут
    comments.sort(key=lambda c: abs((parse_ts(c['at'], tz) - since).total_seconds()))
    links = []
    for src in (item, items.get(item.get('parent') or '')):
        for ln in (src or {}).get('links') or []:
            if (ln.get('label') or '').casefold() in rl['blockingLinks']:
                links.append({'label': ln['label'], 'key': ln['key'], 'summary': trim(ln.get('summary'), 120),
                              'status': ln.get('status'), 'from': src['key']})
    out = {}
    if comments:
        out['comments'] = comments[:EVIDENCE_COMMENTS]
    if links:
        out['links'] = links
    return out


def signals(items, found, start_d, to_d, tz):
    """Комментарии про ожидание, рядом с которыми нет ни одного интервала ожидания:
    сами по себе они не случай (нет дат), но говорят, где учёт неполон."""
    near = {}
    for f in found:
        near.setdefault(f['item']['key'], []).append((f['since'] - timedelta(days=2),
                                                      f['until'] or datetime.max.replace(tzinfo=tz)))
    out = []
    for item in sorted(items.values(), key=lambda it: key_order(it['key'])):
        for c in item.get('comments') or []:
            at = parse_ts(c.get('at'), tz)
            if not at or not (start_d <= at.date() <= to_d) or not WAIT_WORDS.search(c.get('body') or ''):
                continue
            if any(a <= at <= b for a, b in near.get(item['key'], [])):
                continue
            out.append({'key': item['key'], 'at': at.isoformat(timespec='minutes'),
                        'text': trim(c.get('body'), 160)})
    return out[:SIGNALS_MAX]


def digest(data):
    body = {k: v for k, v in data.items() if k != 'factsHash'}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
