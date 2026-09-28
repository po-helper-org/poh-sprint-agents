#!/usr/bin/env python3
"""Сборщик команды B — пример своего сборщика в проекте пользователя.

Здесь он синтетический: отдаёт заранее известный набор, чтобы тесты runner шли
без сети. В жизни на этом месте стоит код, который ходит в JIRA по правилам
команды B — протокол и схема при этом те же (contract/PROTOCOL.md).
"""
import json
import sys
from datetime import datetime, timedelta

PROTOCOL = 1
VERSION = '0.3.0'

STATUS_MAP = {'Бэклог': 'open', 'В работе': 'progress', 'Ревью': 'review',
              'Тестирование': 'testing', 'Ожидает релиза': 'blocked', 'Готово': 'done'}
PEOPLE = ['Участник Ж', 'Участник З']


def stats(vals):
    if not vals:
        return None
    ordered = sorted(vals)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {'mean': round(sum(ordered) / len(ordered), 1), 'median': round(median, 1),
            'count': len(ordered)}


def build(req):
    now = datetime.fromisoformat(req['now'])
    team = req['team']
    stories = [
        ('B-1201', 'Экран онбординга', 'Ревью', 'В работе', 'B-900',
         [('B-1211', 'Схема БД', 'Готово', 'Выполнено')]),
        ('B-1202', 'Очередь отложенных действий', 'В работе', 'В работе', 'B-900',
         [('B-1212', 'Бизнес-логика', 'Тестирование', 'В работе'),
          ('B-1213', 'Покрытие тестами', 'Бэклог', 'К выполнению')]),
        ('B-1203', 'Платёжная форма', 'Ожидает релиза', 'В работе', None, []),
    ]
    epics, counts = [], dict.fromkeys(STATUS_MAP.values(), 0)
    by_epic = {}
    for key, title, status, cat, epic, subs in stories:
        row = epic or 'no-epic'
        bag = by_epic.setdefault(row, {'rowId': row, 'epicKey': epic,
                                       'epicTitle': 'Мобильный онбординг' if epic else 'Без эпика',
                                       'stories': []})
        bag['stories'].append({
            'key': key, 'title': title, 'status': status, 'category': cat,
            'statusChanged': (now - timedelta(days=2, hours=3)).isoformat(),
            'assignee': PEOPLE[len(bag['stories']) % 2],
            'subtasks': [{'key': sk, 'summary': st, 'status': ss, 'category': sc,
                          'statusChanged': (now - timedelta(days=1)).isoformat(),
                          'assignee': PEOPLE[0]} for sk, st, ss, sc in subs],
        })
        counts[STATUS_MAP[status]] += 1
        for _, _, ss, _ in subs:
            counts[STATUS_MAP[ss]] += 1
    for row in ('B-900', 'no-epic'):
        if row in by_epic:
            epics.append(by_epic[row])

    units = sum(counts.values())
    done = counts['done']
    leads = [3.5, 7.25, 12.0]
    sprint = {'name': 'B-19', 'total': units, 'closed': done, 'open': units - done,
              'throughputPct': round(100 * done / units) if units else 0,
              'lead': stats(leads[:done] or []), 'cycle': stats([1.5] * done or []),
              'leadStory': stats(leads[:done] or []), 'leadTask': None,
              'points': sorted(leads[:done])}
    metrics = {'sprints': [sprint], 'overall': {
        'lead': sprint['lead'], 'cycle': sprint['cycle'], 'leadStory': sprint['leadStory'],
        'leadTask': None, 'total': units, 'closed': done}}

    start = (now - timedelta(days=5)).date()
    days = []
    for i in range(11):
        day = start + timedelta(days=i)
        closed = min(done, max(0, i - 2))
        days.append({'date': day.isoformat(), 'scope': units, 'remaining': units - closed,
                     'closed': closed, 'weekend': day.weekday() >= 5,
                     'future': day.isoformat() > now.date().isoformat()})
    burndown = {'sprintName': 'B-19', 'start': start.isoformat(),
                'end': days[-1]['date'], 'days': days}

    points = [{'key': 'B-1150', 'title': 'Пуш-уведомления', 'status': 'Готово',
               'category': 'Выполнено', 'doneAt': (now - timedelta(days=9)).date().isoformat(),
               'cycle': 2.0, 'outlier': False},
              {'key': 'B-1151', 'title': 'Офлайн-режим', 'status': 'Готово',
               'category': 'Выполнено', 'doneAt': (now - timedelta(days=4)).date().isoformat(),
               'cycle': 6.0, 'outlier': True}]
    mean, median = 4.0, 4.0
    limit = 4.0
    chart = {'points': points, 'days': 30, 'mean': mean, 'median': median, 'sd': 2.0,
             'limit': limit, 'outliers': 1, 'today': now.date().isoformat(),
             'risks': [{'key': 'B-1203', 'title': 'Платёжная форма', 'status': 'Ожидает релиза',
                        'category': 'В работе', 'assignee': PEOPLE[1], 'elapsed': 9.0}]}
    control = {'days': 30, 'stories': chart,
               'subtasks': {'points': [], 'risks': [], 'days': 30}}

    events = [{'kind': 'status', 'key': 'B-1201', 'title': 'Экран онбординга',
               'author': PEOPLE[0], 'at': (now - timedelta(hours=5)).isoformat(),
               'from': 'В работе', 'to': 'Ревью', 'toCat': 'В работе'},
              {'kind': 'comment', 'key': 'B-1202', 'title': 'Очередь отложенных действий',
               'author': PEOPLE[1], 'at': (now - timedelta(days=1, hours=2)).isoformat(),
               'body': 'Собрал ветку, отправил на ревью.'}]
    events.sort(key=lambda e: e['at'], reverse=True)
    kinds, authors = {}, {}
    for e in events:
        kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
        authors[e['author']] = authors.get(e['author'], 0) + 1

    return {
        'slug': team['slug'], 'team': team['name'], 'boardId': team['board'],
        'boardName': 'Scrum Board Мобильное', 'boardUrl': 'https://jira.demo-workspace.local'
                                                          '/secure/RapidBoard.jspa?rapidView=202',
        'jiraBase': 'https://jira.demo-workspace.local', 'sprintName': 'B-19',
        'epics': epics, 'metrics': metrics, 'burndown': burndown, 'control': control,
        'velocity': {'sprints': [{'name': 'B-19', 'planned': units, 'done': done,
                                  'split': counts}], 'unit': 'задач', 'avgDone': float(done)},
        'logs': {'events': events, 'days': 7, 'kinds': kinds,
                 'authors': sorted(authors.items(), key=lambda x: (-x[1], x[0]))},
        'statusMap': dict(sorted(STATUS_MAP.items())),
        '_meta': {'collector': team['slug'], 'version': VERSION, 'protocol': PROTOCOL,
                  'collectedAt': req['now'], 'requests': 4, 'durationMs': 120,
                  'warnings': ['статус «Ожидает релиза» считается блокировкой по решению команды B']},
    }


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        print('на stdin не пришёл запрос', file=sys.stderr)
        return 2
    req = json.loads(raw)
    if req.get('protocol') != PROTOCOL:
        print(f'сборщик знает protocol {PROTOCOL}', file=sys.stderr)
        return 2
    if req.get('params', {}).get('fail_jira'):
        print('JIRA недоступна (так задано в params для теста)', file=sys.stderr)
        return 3
    data = build(req)
    if req.get('params', {}).get('drop_field'):
        del data['metrics']['overall']['lead']
    print(f'команда {req["team"]["slug"]}: собрано {len(data["epics"])} эпиков', file=sys.stderr)
    json.dump(data, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
