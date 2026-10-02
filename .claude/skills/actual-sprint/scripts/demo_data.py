#!/usr/bin/env python3
"""Генератор демо-данных для отчёта — без обращения к JIRA.

Нужен, чтобы показывать навык и снимать скриншоты, не таская корпоративные данные.
Всё синтетическое: вымышленные команды, задачи `INIT-*`, люди «Участник А…».
Форма данных — та же схема, что у сборщиков (`contract/team.schema.json`),
поэтому демо рендерится тем же шаблоном, что и боевой отчёт.

    python3 demo_data.py --out demo-teams.json
    python3 demo_data.py --html demo-report.html    # сразу собрать страницу
    python3 demo_data.py --business demo-business.html   # она же, открытая презентацией

Сид фиксирован: одинаковый запуск даёт одинаковую картинку, скриншоты
не «плывут» между пересборками.
"""
import argparse, json, pathlib, random, statistics
from datetime import datetime, timedelta, timezone

SEED = 20260915
NOW = datetime(2026, 9, 15, 17, 0, tzinfo=timezone(timedelta(hours=3)))

PEOPLE = ['Участник ' + c for c in 'АБВГДЕЖЗИК']

TEAMS = [
    {'slug': 'platform', 'team': 'Платформа', 'board': 'Scrum Board Платформа', 'sprint': 'Спринт 74'},
    {'slug': 'catalog', 'team': 'Каталог', 'board': 'Scrum Board Каталог', 'sprint': 'Спринт 41'},
    {'slug': 'mobile', 'team': 'Мобильное приложение', 'board': 'Scrum Board Мобильное', 'sprint': 'Спринт 18'},
]

EPICS = {
    'platform': ['Приём заказов из внешнего канала', 'Единый каталог позиций', 'Наблюдаемость сервисов',
                 'Миграция хранилища', 'Контракты API'],
    'catalog': ['Поиск по каталогу', 'Импорт остатков партнёров', 'Кэш справочников', 'Модерация карточек'],
    'mobile': ['Онбординг пользователя', 'Офлайн-режим', 'Пуш-уведомления', 'Оплата в приложении'],
}

STORIES = [
    'Сервис приёма событий', 'Структура хранения заказов', 'Чтение событий создания',
    'Чтение событий отмены', 'Мониторинг работоспособности', 'Агрегация каталога и доступности',
    'Дедупликация по типам объектов', 'География и города', 'Метрики загрузчика',
    'Кэш карточек позиции', 'Переезд на новое хранилище', 'Контракт внешнего API',
    'Автотесты интеграционного слоя', 'Поиск по синонимам', 'Ранжирование выдачи',
    'Импорт остатков по расписанию', 'Инвалидация кэша справочников', 'Очередь модерации',
    'Экран онбординга', 'Локальное хранилище', 'Очередь отложенных действий',
    'Подписка на уведомления', 'Платёжная форма', 'Обработка отказов оплаты',
    'Рефакторинг слоя данных', 'Логи и трассировка запросов', 'Фича-флаги релиза',
]

SUBTASKS = ['Схема БД', 'Бизнес-логика', 'Покрытие тестами', 'Мониторинг и алерты',
            'Обновление контракта', 'Ревью безопасности', 'Нагрузочный прогон', 'Документация']

# приоритеты как в русскоязычной JIRA; берутся по номеру ключа, а не из генератора
# случайностей — так добавление поля не сдвинуло остальную демо-картинку
PRIORITIES = ['Средний', 'Высокий', 'Средний', 'Низкий', 'Критический', 'Средний', 'Высокий']


def priority(key):
    return PRIORITIES[int(key.rsplit('-', 1)[-1]) % len(PRIORITIES)]


# статус -> категория трекера
STATUSES = [
    ('Бэклог', 'К выполнению'), ('Открыто', 'К выполнению'), ('Анализ', 'В работе'),
    ('В работе', 'В работе'), ('Дизайн', 'В работе'), ('В ожидании', 'К выполнению'),
    ('Тестирование', 'В работе'), ('Ревью', 'В работе'), ('Готово к проверке', 'К выполнению'),
    ('Закрыт', 'Выполнено'),
]
DONE = ('Закрыт', 'Выполнено')

COMMENTS = [
    'Согласовал контракт со смежной командой, приступаю к реализации.',
    'Завис на стенде — жду доступ, вернусь к задаче завтра.',
    'Собрал ветку, отправил на ревью.',
    'Нашёл расхождение в справочнике, уточняю у аналитика.',
    'Проверил на препроде: сценарий проходит, ошибок нет.',
    'Разделил задачу — часть вынес в отдельную подзадачу.',
]


def bucket(status, category):
    s = status.lower()
    if category == 'Выполнено':
        return 'done'
    if 'ожида' in s or 'блок' in s or 'пауза' in s:
        return 'blocked'
    if 'тест' in s:
        return 'testing'
    if 'ревью' in s or 'проверк' in s:
        return 'review'
    return 'open' if category == 'К выполнению' else 'progress'


def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {'mean': round(statistics.mean(vals), 1),
            'median': round(statistics.median(vals), 1), 'count': len(vals)}


class Keys:
    def __init__(self):
        self.n = 100

    def next(self):
        self.n += 1
        return f'INIT-{self.n}'


SCOPE_KEYS = iter(range(7000, 9999))


def epic_scope(ekey, stories, sprint_name, sprint_no):
    """Весь эпик для «Весь эпик»: задачи спринта + сделанное раньше + бэклог.

    Свой генератор на ключ эпика, а не общий rnd: иначе добавление объёма сдвинуло бы
    всю остальную демо-картинку и скриншоты в документации.
    """
    r = random.Random(ekey)
    day = lambda d: (NOW - timedelta(days=d)).date().isoformat()  # noqa: E731
    scope = [{'key': st['key'], 'title': st['title'], 'type': 'История', 'status': st['status'],
              'category': st['category'], 'assignee': st['assignee'], 'priority': st['priority'],
              'sprint': sprint_name, 'inSprint': True, 'created': day(r.randint(8, 30)),
              'doneAt': st['statusChanged'][:10] if st['category'] == 'Выполнено' else None,
              'sp': r.choice([1, 2, 3, 5, 5, 8, 13, None]),
              'subtasks': [{k: sub[k] for k in ('key', 'summary', 'status', 'category', 'priority')}
                           for sub in st['subtasks']]} for st in stories]
    plan = [('Закрыт', 'Выполнено', f'Спринт {sprint_no - 2}')] * r.randint(3, 6) + \
           [('Закрыт', 'Выполнено', f'Спринт {sprint_no - 1}')] * r.randint(2, 5) + \
           [('Бэклог', 'К выполнению', None)] * r.randint(2, 6) + \
           [('Анализ', 'В работе', None)] * r.randint(0, 2)
    # даты подзадач: созданы чуть позже родителя, закрыты — к закрытию родителя или раньше
    def sub_dates(parent):
        for sub in parent['subtasks']:
            c = parent['created'] or day(20)
            sub['created'] = min(day(0), (datetime.fromisoformat(c) + timedelta(days=r.randint(0, 3))).date().isoformat())
            if sub['category'] == 'Выполнено':
                end = parent['doneAt'] or day(r.randint(0, 6))
                sub['doneAt'] = max(sub['created'], (datetime.fromisoformat(end) - timedelta(days=r.randint(0, 4))).date().isoformat())
            else:
                sub['doneAt'] = None
    for status, cat, sprint in plan:
        key = f'INIT-{next(SCOPE_KEYS)}'
        subs = []
        for name in r.sample(SUBTASKS, r.randint(0, 3)):
            sub_key = f'INIT-{next(SCOPE_KEYS)}'
            subs.append({'key': sub_key, 'summary': name, 'status': status, 'category': cat,
                         'priority': priority(sub_key)})
        # закрытые раньше — в своём спринте: N-2 — 4–5 недель назад, N-1 — 1–3 недели назад
        done_ago = {f'Спринт {sprint_no - 2}': r.randint(22, 35), f'Спринт {sprint_no - 1}': r.randint(8, 21)}.get(sprint)
        scope.append({'key': key, 'title': r.choice(STORIES), 'type': r.choice(['История', 'История', 'Задача']),
                      'status': status, 'category': cat, 'assignee': r.choice(PEOPLE),
                      'priority': priority(key), 'sprint': sprint, 'inSprint': False,
                      'created': day((done_ago or 0) + r.randint(5, 25)),
                      'doneAt': day(done_ago) if done_ago and cat == 'Выполнено' else None,
                      'sp': r.choice([1, 2, 3, 5, 8, 13, None]), 'subtasks': subs})
    for it in scope:
        sub_dates(it)
    return scope


def story_events(st):
    """Хронология истории за всё время (как у сборщика 1.7.0): создание, путь по статусам,
    комментарии; то же по подзадачам. Свой генератор от ключа — остальное демо не сдвигается."""
    r = random.Random('events:' + st['key'])
    path = {'open': [], 'blocked': ['В работе', 'В ожидании'], 'progress': ['Анализ', 'В работе'],
            'testing': ['В работе', 'Тестирование'], 'review': ['В работе', 'Ревью'], 'done': ['В работе', 'Ревью', 'Закрыт']}
    def walk(key, status, category, last, created):
        steps = path[bucket(status, category)][:]
        if steps and steps[-1] != status:
            steps[-1] = status
        out = [{'at': created.strftime('%Y-%m-%dT%H:%M'), 'kind': 'created', 'key': key, 'by': r.choice(PEOPLE)}]
        prev, n = 'Бэклог', len(steps)
        for i, to in enumerate(steps):
            at = created + (last - created) * (i + 1) / n
            out.append({'at': at.strftime('%Y-%m-%dT%H:%M'), 'kind': 'status', 'key': key, 'by': r.choice(PEOPLE),
                        'from': prev, 'to': to, 'done': to == 'Закрыт'})
            prev = to
        for _ in range(r.choice([0, 0, 1, 1, 2, 3])):
            at = created + (NOW - created) * r.uniform(.15, .98)
            out.append({'at': at.strftime('%Y-%m-%dT%H:%M'), 'kind': 'comment', 'key': key, 'by': r.choice(PEOPLE),
                        'body': r.choice(COMMENTS)})
        return out
    last = datetime.fromisoformat(st['statusChanged'])
    created = last - timedelta(days=r.randint(6, 40), hours=r.randint(0, 20))
    events = walk(st['key'], st['status'], st['category'], last, created)
    for sub in st['subtasks']:
        s_last = datetime.fromisoformat(sub['statusChanged']) if sub.get('statusChanged') else NOW
        s_created = max(created + timedelta(hours=r.randint(2, 60)), s_last - timedelta(days=r.randint(2, 20)))
        events += walk(sub['key'], sub['status'], sub['category'], max(s_last, s_created), s_created)
    return sorted(events, key=lambda e: e['at'])


def demo_output(slug, epics, sprint_names):
    """Выработка участников: задачи и SP по статусу на конец спринта, с движением статусов
    и комментариями (как у сборщика 1.4.0). Свой генератор от slug — остальные демо-числа
    от него не сдвигаются."""
    r = random.Random('output:' + slug)
    order = ('open', 'blocked', 'progress', 'testing', 'review', 'done')
    by_bucket = {b: [st for st, cat in STATUSES if bucket(st, cat) == b] for b in order}
    by_bucket['done'] = ['Закрыт', 'Закрыт', 'Закрыт', 'Отменён']
    sp_of = lambda: r.choice([1, 2, 3, 3, 5, 5, 8, 13])  # noqa: E731
    stories = [st for e in epics for st in e['stories']]
    people = sorted({st['assignee'] for st in stories if st.get('assignee')})
    cur_start = (NOW - timedelta(days=7)).date()
    n = len(sprint_names)
    keyno = iter(range(8000 + 300 * (sum(map(ord, slug)) % 7), 10 ** 6))

    def history(status, end):
        path = ['Бэклог', 'В работе'] + ([] if status in ('В работе', 'Бэклог') else [status])
        out, at = [], end - timedelta(days=r.randint(6, 12))
        for a, b in zip(path, path[1:]):
            at += timedelta(days=r.randint(1, 3), hours=r.randint(1, 8))
            out.append({'at': min(at, end).strftime('%Y-%m-%dT%H:%M'), 'from': a, 'to': b, 'by': r.choice(PEOPLE)})
        return out

    def comments(end):
        return [{'at': (end - timedelta(days=r.randint(0, 6), hours=r.randint(1, 9))).strftime('%Y-%m-%dT%H:%M'),
                 'by': r.choice(PEOPLE), 'body': r.choice(COMMENTS)} for _ in range(r.choice([0, 0, 1, 2]))]

    sprints, leads = [], {}
    for i, name in enumerate(sprint_names):
        current = i == n - 1
        s_start = cur_start - timedelta(days=14 * (n - 1 - i))
        s_end = s_start + timedelta(days=14)
        end_dt = NOW if current else datetime.combine(s_end, datetime.min.time(), NOW.tzinfo)
        members = {}
        if current:
            for st in stories:
                b = bucket(st['status'], st['category'])
                members.setdefault(st.get('assignee') or 'Не назначен', []).append(
                    {'key': st['key'], 'title': st['title'], 'status': st['status'], 'bucket': b, 'sp': sp_of(),
                     'history': history(st['status'], end_dt), 'comments': comments(end_dt)})
        else:
            for who in people:
                for _ in range(r.randint(2, 6)):
                    b = r.choices(order, [1, 1, 1, 1, 1, 12])[0]
                    status = r.choice(by_bucket[b])
                    members.setdefault(who, []).append(
                        {'key': f'INIT-{next(keyno)}', 'title': r.choice(STORIES), 'status': status, 'bucket': b,
                         'sp': sp_of(), 'history': history(status, end_dt), 'comments': comments(end_dt)})
        out = []
        for who, items in sorted(members.items()):
            split = {b: [0, 0] for b in order}
            for it in items:
                split[it['bucket']][0] += 1
                split[it['bucket']][1] += it['sp']
            leads.setdefault(who, []).extend(round(r.uniform(2, 22), 1) for _ in range(split['done'][0]))
            out.append({'name': who, 'split': split, 'items': items})
        sprints.append({'name': name, 'current': current, 'start': s_start.isoformat(), 'end': s_end.isoformat(),
                        'members': out,
                        'timeInStatus': {'blocked': round(r.uniform(0.8, 4.5), 1), 'progress': round(r.uniform(2, 5), 1),
                                         'review': round(r.uniform(0.6, 2.5), 1), 'testing': round(r.uniform(0.8, 3), 1)}})
    lead = {w: {'median': round(statistics.median(v), 1), 'count': len(v)} for w, v in leads.items() if v}
    return {'unit': 'SP', 'field': 'customfield_10106', 'sprints': sprints, 'lead': lead}


def build_team(spec, rnd, keys):
    slug = spec['slug']
    start = NOW - timedelta(days=7)
    end = start + timedelta(days=14)

    epics, all_units = [], []
    for title in EPICS[slug]:
        ekey = keys.next()
        stories = []
        for _ in range(rnd.randint(2, 5)):
            skey = keys.next()
            status, cat = rnd.choice(STATUSES)
            age = rnd.choice([0, 1, 1, 2, 3, 5, 8, 14, 22])
            story = {
                'key': skey, 'title': rnd.choice(STORIES),
                'status': status, 'category': cat,
                'statusChanged': (NOW - timedelta(days=age, hours=rnd.randint(0, 20))).isoformat(),
                'assignee': rnd.choice(PEOPLE),
                'priority': priority(skey),
                'subtasks': [],
            }
            for st in rnd.sample(SUBTASKS, rnd.randint(0, 5)):
                sstatus, scat = rnd.choice(STATUSES)
                sage = rnd.choice([0, 1, 2, 4, 7, 12])
                sub_key = keys.next()
                story['subtasks'].append({
                    'key': sub_key, 'summary': st, 'priority': priority(sub_key),
                    'status': sstatus, 'category': scat,
                    'statusChanged': (NOW - timedelta(days=sage, hours=rnd.randint(0, 20))).isoformat(),
                    'assignee': rnd.choice(PEOPLE),
                })
            stories.append(story)
            all_units.append(story)
            all_units.extend(story['subtasks'])
        sprint_no = int(spec['sprint'].split()[-1])
        # плановая дата эпика — у двух из трёх, детерминированно от ключа
        due_n = int(ekey.split('-')[1])
        epics.append({'rowId': ekey, 'epicKey': ekey, 'epicTitle': title,
                      'epicPriority': priority(ekey), 'stories': stories,
                      'epicDue': (NOW + timedelta(days=6 + due_n % 40)).date().isoformat() if due_n % 3 else None,
                      'scope': epic_scope(ekey, stories, spec['sprint'], sprint_no)})

    # истории без эпика — псевдо-эпик
    orphans = []
    for _ in range(rnd.randint(2, 4)):
        status, cat = rnd.choice(STATUSES[:6])
        okey = keys.next()
        orphans.append({
            'key': okey, 'title': rnd.choice(STORIES), 'priority': priority(okey),
            'status': status, 'category': cat,
            'statusChanged': (NOW - timedelta(days=rnd.randint(0, 20))).isoformat(),
            'assignee': rnd.choice(PEOPLE), 'subtasks': [],
        })
    all_units.extend(orphans)
    epics.append({'rowId': 'no-epic', 'epicKey': None, 'epicTitle': 'Без эпика',
                  'epicPriority': None, 'stories': orphans})

    # метрики по трём спринтам
    nums = [int(spec['sprint'].split()[-1]) - 2 + i for i in range(3)]
    sprint_rows, velocity, all_closed = [], [], []
    for i, n in enumerate(nums):
        total = rnd.randint(40, 95)
        closed = total if i < 2 else 0
        if i < 2:
            closed = int(total * rnd.uniform(.66, .8))
        else:
            closed = sum(1 for u in all_units if bucket(u['status'], u['category']) == 'done')
            total = len(all_units)
        leads = [round(rnd.choice([1, 2, 3, 5, 8, 12, 16, 21, 28, 40, 62]) * rnd.uniform(.7, 1.3), 2)
                 for _ in range(closed)]
        cycles = [round(l * rnd.uniform(.15, .55), 2) for l in leads]
        counts = dict.fromkeys(('open', 'blocked', 'progress', 'testing', 'review', 'done'), 0)
        if i < 2:
            counts['done'] = closed
            rest = total - closed
            for k in ('open', 'blocked', 'progress', 'review'):
                take = rnd.randint(0, rest); counts[k] = take; rest -= take
            counts['open'] += rest
        else:
            for u in all_units:
                counts[bucket(u['status'], u['category'])] += 1
        sprint_rows.append({
            'name': f'Спринт {n}', 'total': total, 'closed': closed, 'open': total - closed,
            'throughputPct': round(100 * closed / total) if total else 0,
            'lead': stats(leads), 'cycle': stats(cycles),
            'leadStory': stats(leads[:max(1, len(leads) // 3)]),
            'leadTask': stats(leads[max(1, len(leads) // 3):]),
            'points': sorted(leads),
        })
        velocity.append({'name': f'Спринт {n}', 'planned': total, 'done': counts['done'], 'split': counts})
        all_closed += [{'lead': l, 'cycle': c} for l, c in zip(leads, cycles)]

    metrics = {'sprints': sprint_rows, 'overall': {
        'lead': stats([x['lead'] for x in all_closed]),
        'cycle': stats([x['cycle'] for x in all_closed]),
        'leadStory': stats([x['lead'] for x in all_closed[::3]]),
        'leadTask': stats([x['lead'] for x in all_closed[1::3]]),
        'total': sum(s['total'] for s in sprint_rows),
        'closed': sum(s['closed'] for s in sprint_rows)}}

    # burndown: на сегодня сходится со статусами задач (как у боевого сборщика —
    # там оба числа из одного списка), объём один раз подрастает посреди спринта.
    # Число вызовов rnd прежнее, чтобы графики ниже не сдвинулись от правки.
    scope_now, closed_now = sprint_rows[-1]['total'], velocity[-1]['done']
    added = rnd.randint(1, 4)
    rnd.randint(1, 4)
    steps = [rnd.randint(0, 4) for _ in range(8)]
    today_idx = min((NOW.date() - start.date()).days, len(steps) - 1)
    ramp = [sum(steps[:d + 1]) for d in range(today_idx + 1)]
    days = []
    for d in range(15):
        day = start + timedelta(days=d)
        scope = scope_now - added if d < 3 else scope_now
        if d > today_idx:
            closed_n = closed_now
        else:
            closed_n = round(closed_now * ramp[d] / ramp[-1]) if ramp[-1] else 0
        closed_n = min(closed_n, scope)
        days.append({'date': day.date().isoformat(), 'scope': scope,
                     'remaining': scope - closed_n, 'closed': closed_n,
                     'weekend': day.weekday() >= 5, 'future': day.date() > NOW.date()})
    burndown = {'sprintName': spec['sprint'], 'start': start.date().isoformat(),
                'end': end.date().isoformat(), 'days': days}

    # диаграммы управления: закрытые за 30 дней + незакрытые в зоне риска
    def chart(unit_pool, n_points):
        pts = []
        for i in range(n_points):
            cyc = round(rnd.choice([0.4, 1, 2, 3, 4, 6, 9, 14, 22, 31]) * rnd.uniform(.7, 1.4), 2)
            pts.append({'key': keys.next(), 'title': rnd.choice(unit_pool),
                        'status': DONE[0], 'category': DONE[1],
                        'doneAt': (NOW - timedelta(days=rnd.randint(0, 29))).date().isoformat(),
                        'cycle': cyc})
        pts.sort(key=lambda p: p['doneAt'])
        vals = [p['cycle'] for p in pts]
        mean, median = statistics.mean(vals), statistics.median(vals)
        sd = statistics.pstdev(vals)
        limit = round(mean + sd, 2)
        for p in pts:
            p['outlier'] = p['cycle'] > limit
        risks = []
        for u in all_units:
            if bucket(u['status'], u['category']) in ('progress', 'testing', 'review'):
                elapsed = round((NOW - datetime.fromisoformat(u['statusChanged'])).total_seconds() / 86400
                                + rnd.uniform(1, 14), 2)
                if elapsed > median:
                    risks.append({'key': u['key'], 'title': u.get('title') or u.get('summary'),
                                  'status': u['status'], 'category': u['category'],
                                  'assignee': u['assignee'], 'elapsed': elapsed})
        risks.sort(key=lambda r: -r['elapsed'])
        return {'points': pts, 'risks': risks[:8], 'days': 30, 'mean': round(mean, 1),
                'median': round(median, 1), 'sd': round(sd, 1), 'limit': limit,
                'outliers': sum(1 for p in pts if p['outlier']), 'today': NOW.date().isoformat()}

    control = {'days': 30, 'stories': chart(STORIES, rnd.randint(22, 40)),
               'subtasks': chart(SUBTASKS, rnd.randint(14, 28))}

    # лента активности за неделю
    events = []
    for _ in range(rnd.randint(40, 70)):
        when = NOW - timedelta(days=rnd.uniform(0, 7))
        unit = rnd.choice(all_units)
        kind = rnd.choices(['status', 'comment', 'created'], [6, 4, 1])[0]
        ev = {'kind': kind, 'key': unit['key'],
              'title': unit.get('title') or unit.get('summary'),
              'author': rnd.choice(PEOPLE), 'at': when.isoformat()}
        if kind == 'status':
            a, _ = rnd.choice(STATUSES); b, bc = rnd.choice(STATUSES)
            ev.update({'from': a, 'to': b, 'toCat': bc})
        elif kind == 'comment':
            ev['body'] = rnd.choice(COMMENTS)
        else:
            ev['issueType'] = rnd.choice(['Задача', 'История', 'Ошибка'])
        events.append(ev)
    events.sort(key=lambda e: e['at'], reverse=True)
    authors, kinds = {}, {}
    for e in events:
        authors[e['author']] = authors.get(e['author'], 0) + 1
        kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
    logs = {'events': events, 'days': 8, 'since': start.date().isoformat(), 'kinds': kinds,
            'authors': sorted(authors.items(), key=lambda x: -x[1])}

    for e in epics:
        for st in e['stories']:
            st['events'] = story_events(st)
    output = demo_output(slug, epics, [r['name'] for r in sprint_rows])

    return {'slug': slug, 'team': spec['team'], 'boardId': 1000 + len(slug),
            'boardName': spec['board'],
            'boardUrl': f'https://tracker.demo-workspace.local/boards/{slug}',
            'jiraBase': 'https://tracker.demo-workspace.local',
            'sprintName': spec['sprint'], 'epics': epics, 'metrics': metrics,
            'burndown': burndown, 'control': control, 'velocity':
                {'sprints': velocity, 'unit': 'задач',
                 'avgDone': round(sum(v['done'] for v in velocity) / len(velocity), 1)},
            'output': output, 'logs': logs,
            'statusMap': dict(sorted({(u.get('status')): bucket(u['status'], u['category'])
                                      for u in all_units}.items())),
            '_meta': {'collector': 'demo', 'version': '1.0.0', 'protocol': 1,
                      'collectedAt': NOW.isoformat(), 'requests': 0, 'durationMs': 0,
                      'warnings': ['демо-данные: в JIRA не ходили']},
            'notes': {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None, help='куда положить JSON команд')
    ap.add_argument('--html', default=None, help='отчёт PO (sprint-report.html)')
    ap.add_argument('--business', default=None, help='бизнес-отчёт «ФАКТ | спринт» (навык sprint-business)')
    a = ap.parse_args()

    rnd = random.Random(SEED)
    keys = Keys()
    teams = [build_team(spec, rnd, keys) for spec in TEAMS]

    # заметки старого формата: страница при открытии переносит их в корзину
    teams[0]['notes'] = {
        teams[0]['epics'][0]['rowId']: 'Ждём смежников по контракту приёма.\n'
                                       'Риск: два стенда не синхронизированы.\nРешение к четвергу.',
        '__metrics__': 'Половина спринта прошла, закрыто меньше четверти.\n'
                       'Разобрать на ретро: почему задачи висят в ревью.',
    }

    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(teams, ensure_ascii=False), encoding='utf-8')
        print('данные:', a.out)

    if a.html or a.business:
        # примеры агентов на демо-данных: хеш ставим по ним, дальше — тот же путь, что у
        # runner и business.py (блок прикладывается, только если хеш совпал)
        import sys
        import copy
        here = pathlib.Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(here / 'runner'))
        import build as build_mod

        def example(rel):
            doc = json.loads((here.parent / rel).read_text(encoding='utf-8'))
            for t in teams:
                if t['slug'] in doc['teams']:
                    doc['teams'][t['slug']]['dataHash'] = build_mod.team_digest(t)
            return doc

        if a.html:
            page = copy.deepcopy(teams)
            build_mod.attach_insights(page, example('sprint-insights/examples/demo-insights.json'))
            build_mod.write_page(page, here / 'resources' / 'report_template.html', a.html)
            print('отчёт PO:', a.html)
        if a.business:
            page = copy.deepcopy(teams)
            doc = example('sprint-business/examples/demo-business.json')
            for t in page:
                entry = doc['teams'].get(t['slug'])
                if entry:
                    t['business'] = {k: v for k, v in entry.items() if k != 'dataHash'}
            build_mod.write_page(page, here.parent / 'sprint-business' / 'resources' / 'business_template.html', a.business)
            print('бизнес-отчёт:', a.business)

    for t in teams:
        units = sum(1 + len(s['subtasks']) for e in t['epics'] for s in e['stories'])
        print(f"  {t['team']}: эпиков {len(t['epics'])}, задач {units}, "
              f"событий {len(t['logs']['events'])}, в зоне риска "
              f"{len(t['control']['stories']['risks'])}")


if __name__ == '__main__':
    main()
