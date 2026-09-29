"""Модель статуса спринта: объект команды (team.schema.json) → плоский словарь для страницы.

Здесь все расчёты и все пороги; page.py только раскладывает готовые числа по макету.
Так одно и то же правило («стоит без движения», «зона риска») не разъедется между
текстом подписи и PDF.
"""
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACTUAL = HERE.parent / 'actual-sprint'
for _p in (ACTUAL / 'runner', ACTUAL / 'contract'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import buckets as buckets_mod  # noqa: E402

BUCKETS = buckets_mod.BUCKETS
STALE_DAYS = 3          # как на странице actual-sprint: дольше — «стоит без движения»
ACTIVE = {'progress', 'testing', 'review'}


# ------------------------------------------------------------------ помощники

def parse_ts(value):
    if not value:
        return None
    value = value.strip().replace('Z', '+00:00')
    # JIRA отдаёт смещение без двоеточия: +0300
    if len(value) > 5 and value[-5] in '+-' and value[-3] != ':':
        value = value[:-2] + ':' + value[-2:]
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def ddmm(value):
    d = value if isinstance(value, date) else date.fromisoformat(value[:10])
    return d.strftime('%d.%m')


def person(name):
    """«Фамилия Имя Отчество» → «Фамилия И.»; не назначен → «без исполнителя»."""
    if not name:
        return 'без исполнителя'
    parts = name.split()
    return parts[0] if len(parts) == 1 else f'{parts[0]} {parts[1][0]}.'


def plural(n, one, few, many):
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


# ------------------------------------------------------------------ команда

class TeamModel:
    def __init__(self, team, rules):
        self.t = team
        self.rules = rules
        self.status_map = team.get('statusMap') or {}
        self.collected = parse_ts(team['_meta']['collectedAt'])

    def bucket(self, status, category):
        return self.status_map.get(status) or self.rules.bucket(status, category)

    def age(self, iso):
        ts = parse_ts(iso)
        if not ts or not self.collected:
            return None
        # одна из меток без смещения — сравниваем как местное время сбора
        if (ts.tzinfo is None) != (self.collected.tzinfo is None):
            ts = ts.replace(tzinfo=self.collected.tzinfo)
        return max(0, (self.collected - ts).days)

    def items(self):
        """Истории и подзадачи эпиков: (эпик, ключ, название, объект)."""
        for epic in self.t['epics']:
            for st in epic['stories']:
                yield epic, st['key'], st['title'], st
                for sub in st['subtasks']:
                    yield epic, sub['key'], sub['summary'], sub

    # --- сроки и темп: burndown и та же идеальная прямая, что на графике страницы
    def pace(self):
        bd = self.t['burndown']
        days = bd['days']
        past = [d for d in days if not d['future']]
        today = past[-1] if past else days[0]
        idx = days.index(today)
        # Первый день с ненулевым объёмом — старт идеальной прямой. Сборщик считает день
        # на момент старта спринта: задачи, внесённые через минуты после старта, дают
        # нулевой первый день, и прямая «от нуля до нуля» превращала бы весь остаток в отставание.
        first = next((i for i, d in enumerate(days) if d['scope']), 0)
        span = len(days) - 1 - first
        # целые задачи с округлением «от половины вверх»: подпись «идеал N» на графике
        # и отставание в плитке должны сходиться в уме читателя
        ideal = [None if i < first else
                 int(days[first]['scope'] * (1 - (i - first) / span) + 0.5) if span > 0 else 0
                 for i in range(len(days))]
        workdays = [d for d in days if not d['weekend']]
        overdue = bool(self.collected) and self.collected.date().isoformat() > bd['end']
        prev = days[idx - 1] if idx > 0 else None
        return {
            'start': bd['start'], 'end': bd['end'], 'days': days, 'ideal': ideal, 'first': first,
            'todayIndex': idx if past else None, 'started': bool(past), 'overdue': overdue,
            'workday': sum(1 for d in workdays if not d['future']),
            'workdays': len(workdays),
            'left': sum(1 for d in workdays if d['future']),
            'scope': today['scope'], 'closed': today['closed'], 'remaining': today['remaining'],
            # плюс — отстаём: остатка больше, чем на идеальной прямой
            'gap': today['remaining'] - (ideal[idx] or 0) if past and idx >= first else 0,
            'dClosed': today['closed'] - prev['closed'] if prev else None,
            'dScope': today['scope'] - prev['scope'] if prev else None,
        }

    def split(self):
        """Статусы всех задач активного спринта (с подзадачами) — последний столбец velocity."""
        sprints = self.t['velocity']['sprints']
        return dict(sprints[-1]['split']) if sprints else dict.fromkeys(BUCKETS, 0)

    def attention(self):
        """Блокеры, затем стоящие без движения, затем зона риска — без повторов."""
        blocked, stale = [], []
        for _, key, title, it in self.items():
            b = self.bucket(it['status'], it.get('category', ''))
            age = self.age(it.get('statusChanged'))
            row = {'key': key, 'title': title, 'status': it['status'], 'bucket': b,
                   'who': person(it.get('assignee')), 'days': age, 'priority': it.get('priority')}
            if b == 'blocked':
                blocked.append(dict(row, kind='blocked'))
            elif b in ACTIVE and age is not None and age > STALE_DAYS:
                stale.append(dict(row, kind='stale'))
        order = lambda r: (-(r['days'] or 0), r['key'])  # noqa: E731
        return sorted(blocked, key=order), sorted(stale, key=order)

    def risks(self):
        """Зона риска только по задачам активного спринта.

        control.*.risks сборщик считает по всем sprints_back спринтам — для графика
        это правильно, а в статусе спринта хвосты прошлых спринтов раздували бы число
        сверх объёма самого спринта.
        """
        prio = {key: it.get('priority') for _, key, _, it in self.items()}
        in_sprint = set(prio)
        rows = {}
        for group in ('stories', 'subtasks'):
            chart = self.t['control'].get(group) or {}
            for r in chart.get('risks', []):
                if r['key'] in in_sprint and r['key'] not in rows:
                    rows[r['key']] = {
                        'key': r['key'], 'title': r['title'], 'status': r['status'],
                        'bucket': self.bucket(r['status'], r.get('category', '')),
                        'who': person(r.get('assignee')), 'days': round(r['elapsed']),
                        'priority': prio.get(r['key']),
                        'median': chart.get('median'), 'kind': 'risk'}
        return sorted(rows.values(), key=lambda r: (-r['days'], r['key']))

    def epics(self):
        """Порядок сборщика, но «Без эпика» всегда последней строкой."""
        out = []
        for epic in self.t['epics']:
            counts = dict.fromkeys(BUCKETS, 0)
            for st in epic['stories']:
                counts[self.bucket(st['status'], st.get('category', ''))] += 1
                for sub in st['subtasks']:
                    counts[self.bucket(sub['status'], sub.get('category', ''))] += 1
            out.append({'key': epic.get('epicKey'),
                        'title': epic.get('epicTitle') or epic.get('epicKey') or 'Без эпика',
                        'counts': counts, 'total': sum(counts.values()), 'done': counts['done']})
        return sorted(out, key=lambda ep: ep['key'] is None)

    def build(self):
        blocked, stale = self.attention()
        risks = self.risks()
        listed = {r['key'] for r in blocked + stale}
        meta = self.t['_meta']
        return {
            'slug': self.t['slug'], 'team': self.t['team'], 'sprint': self.t['sprintName'],
            'boardName': self.t['boardName'], 'boardUrl': self.t['boardUrl'],
            'pace': self.pace(), 'split': self.split(),
            'blocked': blocked, 'stale': stale, 'risks': risks,
            'attention': blocked + stale + [r for r in risks if r['key'] not in listed],
            'epics': self.epics(),
            'collected': self.collected, 'warnings': list(meta.get('warnings', [])),
            'collector': f'{meta.get("collector", "?")}@{meta.get("version", "?")}',
        }


def build(teams):
    rules = buckets_mod.load()
    return [TeamModel(t, rules).build() for t in teams]
