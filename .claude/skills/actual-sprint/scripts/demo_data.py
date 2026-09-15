#!/usr/bin/env python3
"""Генератор демо-данных для отчёта — без обращения к JIRA.

Нужен, чтобы показывать навык и снимать скриншоты, не таская корпоративные данные.
Всё синтетическое: вымышленные команды, задачи `INIT-*`, люди «Участник А…».
Форма данных совпадает с тем, что отдаёт collect.py, поэтому демо рендерится
тем же шаблоном, что и боевой отчёт.

    python3 demo_data.py --out demo-teams.json
    python3 demo_data.py --html demo-report.html    # сразу собрать страницу

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
                'subtasks': [],
            }
            for st in rnd.sample(SUBTASKS, rnd.randint(0, 5)):
                sstatus, scat = rnd.choice(STATUSES)
                sage = rnd.choice([0, 1, 2, 4, 7, 12])
                story['subtasks'].append({
                    'key': keys.next(), 'summary': st,
                    'status': sstatus, 'category': scat,
                    'statusChanged': (NOW - timedelta(days=sage, hours=rnd.randint(0, 20))).isoformat(),
                    'assignee': rnd.choice(PEOPLE),
                })
            stories.append(story)
            all_units.append(story)
            all_units.extend(story['subtasks'])
        epics.append({'rowId': ekey, 'epicKey': ekey, 'epicTitle': title, 'stories': stories})

    # истории без эпика — псевдо-эпик
    orphans = []
    for _ in range(rnd.randint(2, 4)):
        status, cat = rnd.choice(STATUSES[:6])
        orphans.append({
            'key': keys.next(), 'title': rnd.choice(STORIES),
            'status': status, 'category': cat,
            'statusChanged': (NOW - timedelta(days=rnd.randint(0, 20))).isoformat(),
            'assignee': rnd.choice(PEOPLE), 'subtasks': [],
        })
    all_units.extend(orphans)
    epics.append({'rowId': 'no-epic', 'epicKey': None, 'epicTitle': 'Без эпика', 'stories': orphans})

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

    # burndown: объём слегка растёт по ходу спринта
    days, scope = [], sprint_rows[-1]['total']
    done_by_day = 0
    for d in range(15):
        day = start + timedelta(days=d)
        if d in (3, 8):
            scope += rnd.randint(1, 4)
        if d <= 7:
            done_by_day += rnd.randint(0, 4)
        days.append({'date': day.date().isoformat(), 'scope': scope,
                     'remaining': scope - min(done_by_day, scope), 'closed': min(done_by_day, scope),
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
    logs = {'events': events, 'days': 7, 'kinds': kinds,
            'authors': sorted(authors.items(), key=lambda x: -x[1])}

    return {'slug': slug, 'team': spec['team'], 'boardId': 1000 + len(slug),
            'boardName': spec['board'],
            'boardUrl': f'https://tracker.demo-workspace.local/boards/{slug}',
            'jiraBase': 'https://tracker.demo-workspace.local',
            'sprintName': spec['sprint'], 'epics': epics, 'metrics': metrics,
            'burndown': burndown, 'control': control, 'velocity':
                {'sprints': velocity, 'unit': 'задач',
                 'avgDone': round(sum(v['done'] for v in velocity) / len(velocity), 1)},
            'logs': logs,
            'notes': {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=None, help='куда положить JSON команд')
    ap.add_argument('--html', default=None, help='сразу собрать HTML-страницу')
    a = ap.parse_args()

    rnd = random.Random(SEED)
    keys = Keys()
    teams = [build_team(spec, rnd, keys) for spec in TEAMS]

    # демо-заметки: показываем, что комментарии переносятся между запусками
    teams[0]['notes'] = {
        teams[0]['epics'][0]['rowId']: 'Ждём смежников по контракту приёма.\n'
                                       'Риск: два стенда не синхронизированы.\nРешение к четвергу.',
        '__metrics__': 'Половина спринта прошла, закрыто меньше четверти.\n'
                       'Разобрать на ретро: почему задачи висят в ревью.',
    }

    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(teams, ensure_ascii=False), encoding='utf-8')
        print('данные:', a.out)

    if a.html:
        tpl = (pathlib.Path(__file__).parent.parent / 'resources' / 'report_template.html').read_text(encoding='utf-8')
        html = tpl.replace('{{TEAMS_JSON}}', json.dumps(teams, ensure_ascii=False))
        pathlib.Path(a.html).write_text(html, encoding='utf-8')
        print('страница:', a.html, f'({len(html) // 1024} КБ)')

    for t in teams:
        units = sum(1 + len(s['subtasks']) for e in t['epics'] for s in e['stories'])
        print(f"  {t['team']}: эпиков {len(t['epics'])}, задач {units}, "
              f"событий {len(t['logs']['events'])}, в зоне риска "
              f"{len(t['control']['stories']['risks'])}")


if __name__ == '__main__':
    main()
