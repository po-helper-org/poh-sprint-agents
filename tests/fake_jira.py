#!/usr/bin/env python3
"""Синтетическая JIRA: сырые ответы REST для записи replay-фикстур.

Нужна затем, чтобы тесты сборщика шли без сети и без корпоративных данных
(НФТ-8): вымышленные команды, задачи INIT-*, люди «Участник А…». Форма ответов
повторяет то, что отдаёт реальный инстанс на тех же ручках, которые дёргает
сборщик, — иначе фикстура не проверяет ничего.

Сид и «сейчас» зафиксированы: один и тот же набор при каждом запуске.
"""
import random
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 9, 15, 17, 0, tzinfo=TZ)
SEED = 20260915
BASE = 'https://jira.demo-workspace.local'
BOARD_ID = 101
BOARD_NAME = 'Scrum Board Платформа'
OTHER_BOARD_ID = 777
EPIC_FIELD = 'customfield_10101'
SP_FIELD = 'customfield_10106'

PEOPLE = ['Участник ' + c for c in 'АБВГДЕ']

# (id, имя, категория) — набор с ловушками: «В ожидании» это блокировка,
# «Готово к проверке» это ревью, «Дизайн» проваливается в дефолт по категории.
STATUSES = [
    (1, 'Бэклог', 'К выполнению'),
    (2, 'Открыто', 'К выполнению'),
    (3, 'Анализ', 'В работе'),
    (4, 'В работе', 'В работе'),
    (5, 'Тестирование', 'В работе'),
    (6, 'Ревью', 'В работе'),
    (7, 'В ожидании', 'В работе'),
    (8, 'Готово к проверке', 'К выполнению'),
    (9, 'Закрыт', 'Выполнено'),
    (10, 'Дизайн', 'В работе'),
]
BY_NAME = {name: (sid, cat) for sid, name, cat in STATUSES}
DONE_ID = 9
PROGRESS_ID = 4

EPICS = [('INIT-900', 'Приём заказов из внешнего канала'),
         ('INIT-901', 'Единый каталог позиций'),
         ('INIT-902', 'Наблюдаемость сервисов')]

STORY_TITLES = ['Сервис приёма событий', 'Структура хранения заказов', 'Чтение событий создания',
                'Мониторинг работоспособности', 'Агрегация каталога', 'География и города',
                'Метрики загрузчика', 'Кэш карточек позиции', 'Контракт внешнего API',
                'Автотесты интеграционного слоя', 'Поиск по синонимам', 'Ранжирование выдачи']
SUB_TITLES = ['Схема БД', 'Бизнес-логика', 'Покрытие тестами', 'Мониторинг и алерты',
              'Обновление контракта', 'Ревью безопасности']
COMMENTS = ['Согласовал контракт со смежной командой, приступаю к реализации.',
            'Завис на стенде — жду доступ, вернусь к задаче завтра.',
            'Собрал ветку, отправил на ревью.',
            'Проверил на препроде: сценарий проходит, ошибок нет.']


class HttpError(Exception):
    """Ответ трекера с кодом ошибки — фикстура должна уметь и это."""

    def __init__(self, code, message=''):
        super().__init__(f'HTTP {code}: {message}')
        self.code = code


def iso(dt):
    """JIRA отдаёт миллисекунды и смещение без двоеточия — форма тоже часть фикстуры."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}' + dt.strftime('%z')


# приоритет по номеру ключа, а не из генератора случайностей: иначе сдвинулся бы
# весь синтетический набор и вместе с ним эталон старого сборщика
PRIORITIES = ['Средний', 'Высокий', 'Средний', 'Низкий', 'Критический', 'Средний', 'Высокий']


def priority_obj(key):
    name = PRIORITIES[int(key.rsplit('-', 1)[-1]) % len(PRIORITIES)]
    return {'id': str(PRIORITIES.index(name) + 1), 'name': name}


def status_obj(name):
    sid, cat = BY_NAME[name]
    return {'id': str(sid), 'name': name, 'statusCategory': {'name': cat}}


class Keys:
    def __init__(self, start=1000):
        self.n = start

    def next(self):
        self.n += 1
        return f'INIT-{self.n}'


class Dataset:
    """Доска, три спринта и их задачи с changelog — всё, что нужно сборщику."""

    def __init__(self):
        self.rnd = random.Random(SEED)
        self.keys = Keys()
        self.sprints = self._sprints()
        self.issues = {}          # sprint_id -> [issue]
        for i, sprint in enumerate(self.sprints):
            self.issues[sprint['id']] = self._sprint_issues(sprint, i)

    # ------------------------------------------------------------- спринты

    def _sprints(self):
        # активный спринт идёт вторую неделю: NOW − 7 дней от старта
        active_start = NOW - timedelta(days=7)
        out = []
        for i, name in enumerate(['Спринт 72', 'Спринт 73', 'Спринт 74']):
            start = active_start - timedelta(days=14 * (2 - i))
            out.append({
                'id': 5000 + i, 'name': name,
                'state': 'active' if i == 2 else 'closed',
                'startDate': iso(start), 'endDate': iso(start + timedelta(days=14)),
                'originBoardId': BOARD_ID,
            })
        # спринт чужой доски: попадёт в ответ ручки, но сборщик должен его отфильтровать
        out.append({'id': 5900, 'name': 'Спринт X (чужая доска)', 'state': 'active',
                    'startDate': iso(active_start), 'endDate': iso(active_start + timedelta(days=14)),
                    'originBoardId': OTHER_BOARD_ID})
        return out

    # ------------------------------------------------------------- задачи

    def _history(self, hid, when, field, frm, to, author, from_id=None, to_id=None):
        item = {'field': field, 'fromString': frm, 'toString': to}
        if from_id is not None:
            item['from'] = str(from_id)
        if to_id is not None:
            item['to'] = str(to_id)
        return {'id': str(hid), 'created': iso(when),
                'author': {'displayName': author}, 'items': [item]}

    def _issue(self, key, summary, issuetype, status_name, sprint, created, assignee,
               *, subtask=False, epic=None, parent=None, histories=None, comments=None):
        fields = {
            'summary': summary,
            'status': status_obj(status_name),
            'issuetype': {'name': issuetype, 'subtask': subtask},
            'created': iso(created),
            'creator': {'displayName': assignee or PEOPLE[0]},
            'assignee': {'displayName': assignee} if assignee else None,
            'priority': priority_obj(key),
            'subtasks': [],
            EPIC_FIELD: epic,
            # оценка — на задаче, не на подзадаче; детерминированно от ключа, без rnd:
            # остальной набор (и эталон legacy) от этого не меняется
            SP_FIELD: None if subtask else (1, 2, 3, 5, 8)[int(key.split('-')[1]) % 5],
            'comment': {'comments': comments or []},
        }
        # дата решения — момент перехода в закрытый статус (для графика сгорания эпика)
        closes = [h['created'] for h in (histories or []) if h['items'][0]['field'] == 'status'
                  and BY_NAME.get(h['items'][0]['toString'], (None, ''))[1] == 'Выполнено']
        fields['resolutiondate'] = closes[-1] if closes and BY_NAME[status_name][1] == 'Выполнено' else None
        return {'key': key, 'fields': fields, 'parent': parent,
                'changelog': {'histories': histories or []}}

    def _walk(self, issue_key, sprint, final_status, created, author, hid):
        """Путь задачи по статусам: вход в спринт, взятие в работу, финальный статус."""
        start = datetime.fromisoformat(sprint['startDate'])
        # сдвиг по номеру записи: в реальном трекере две правки не приходят в одну
        # секунду, и фикстура не должна создавать искусственных совпадений времени
        jitter = timedelta(seconds=(hid % 4000) * 11)
        hist = [self._history(hid, start + timedelta(hours=2) + jitter,
                              'Sprint', '', sprint['name'], author)]
        hid += 1
        cursor = start + timedelta(days=1, hours=3) + jitter
        sid, cat = BY_NAME[final_status]
        if cat != 'К выполнению':
            hist.append(self._history(hid, cursor, 'status', 'Бэклог', 'В работе',
                                      author, from_id=1, to_id=PROGRESS_ID))
            hid += 1
            cursor += timedelta(days=self.rnd.choice([1, 2, 3, 4]), hours=self.rnd.randint(1, 20))
        if final_status not in ('Бэклог', 'В работе'):
            when = min(cursor + timedelta(seconds=hid % 97), NOW - timedelta(hours=3, seconds=hid % 97))
            hist.append(self._history(hid, when, 'status', 'В работе', final_status,
                                      author, from_id=PROGRESS_ID, to_id=sid))
            hid += 1
        return hist, hid

    def _sprint_issues(self, sprint, index):
        rnd = self.rnd
        start = datetime.fromisoformat(sprint['startDate'])
        hid = 10000 + index * 1000
        issues = []
        # в закрытых спринтах закрыто больше, в активном — разнобой
        pool = (['Закрыт'] * 7 + ['Ревью', 'Тестирование', 'В ожидании', 'Анализ']) if index < 2 else \
               ['Бэклог', 'Анализ', 'В работе', 'Дизайн', 'Тестирование', 'Ревью',
                'В ожидании', 'Готово к проверке', 'Закрыт', 'Закрыт']
        for n in range(9):
            key = self.keys.next()
            author = rnd.choice(PEOPLE)
            final = rnd.choice(pool)
            created = start - timedelta(days=rnd.randint(1, 12), hours=rnd.randint(0, 20))
            epic = rnd.choice([e[0] for e in EPICS] + [None]) if n else EPICS[0][0]
            hist, hid = self._walk(key, sprint, final, created, author, hid)
            comments = []
            if index == 2 and n % 3 == 0:
                comments.append({'id': str(hid), 'created': iso(NOW - timedelta(days=rnd.randint(0, 5),
                                                                               hours=rnd.randint(0, 20))),
                                 'author': {'displayName': rnd.choice(PEOPLE)},
                                 'body': rnd.choice(COMMENTS)})
                hid += 1
            story = self._issue(key, rnd.choice(STORY_TITLES), 'История', final, sprint,
                                created, author, epic=epic, histories=hist, comments=comments)
            issues.append(story)
            for _ in range(rnd.randint(0, 3)):
                sub_key = self.keys.next()
                sub_author = rnd.choice(PEOPLE)
                sub_final = rnd.choice(pool)
                sub_created = created + timedelta(hours=rnd.randint(1, 40))
                sub_hist, hid = self._walk(sub_key, sprint, sub_final, sub_created, sub_author, hid)
                sub = self._issue(sub_key, rnd.choice(SUB_TITLES), 'Подзадача', sub_final, sprint,
                                  sub_created, sub_author, subtask=True, parent=key,
                                  histories=sub_hist)
                issues.append(sub)
                story['fields']['subtasks'].append(
                    {'key': sub_key, 'fields': {'summary': sub['fields']['summary'],
                                                'status': status_obj(sub_final),
                                                'priority': priority_obj(sub_key)}})
            # задача вне story_types: должна попасть в метрики, но не в таблицу эпиков
            if n % 4 == 0:
                task_key = self.keys.next()
                t_author = rnd.choice(PEOPLE)
                t_final = rnd.choice(pool)
                t_created = created - timedelta(days=rnd.randint(0, 3))
                t_hist, hid = self._walk(task_key, sprint, t_final, t_created, t_author, hid)
                issues.append(self._issue(task_key, 'Технический долг: ' + rnd.choice(SUB_TITLES),
                                          'Задача', t_final, sprint, t_created, t_author,
                                          histories=t_hist))
        return issues


# --------------------------------------------------------------- «сервер»

def project(issue, fields, expand):
    """Отдаёт только запрошенные поля — реальная JIRA тоже так делает."""
    wanted = [f.strip() for f in fields.split(',') if f.strip()]
    out = {'key': issue['key'], 'fields': {}}
    for name in wanted:
        if name == 'key':
            continue
        if name in issue['fields']:
            out['fields'][name] = issue['fields'][name]
    if expand and 'changelog' in expand:
        out['changelog'] = issue['changelog']
    return out


def epic_scope(ds):
    """Задачи эпиков без подзадач: все спринты набора + по две вне спринтов на эпик.

    Внеспринтовые строятся детерминированно, без генератора случайностей, чтобы не
    сдвинуть остальной набор: одна в бэклоге, одна закрыта давно, с подзадачей.
    """
    out, seen = [], set()
    for sprint in ds.sprints:
        for i in ds.issues.get(sprint['id'], []):
            f = i['fields']
            if f['issuetype'].get('subtask') or not f.get(EPIC_FIELD) or i['key'] in seen:
                continue
            seen.add(i['key'])
            out.append(i)
    for n, (ekey, _) in enumerate(EPICS):
        for j, (status, title) in enumerate((('Бэклог', 'Отложенная доработка'),
                                             ('Закрыт', 'Первая версия контракта'))):
            key = f'INIT-{3000 + n * 10 + j}'
            sub_key = f'INIT-{3000 + n * 10 + j + 5}'
            out.append({'key': key, 'parent': None, 'changelog': {'histories': []}, 'fields': {
                'summary': title, 'status': status_obj(status),
                'issuetype': {'name': 'История', 'subtask': False},
                'assignee': {'displayName': PEOPLE[n % len(PEOPLE)]},
                'priority': priority_obj(key), EPIC_FIELD: ekey,
                'created': iso(NOW - timedelta(days=80 + j * 5)),
                'resolutiondate': iso(NOW - timedelta(days=60)) if status == 'Закрыт' else None,
                'subtasks': [{'key': sub_key, 'fields': {'summary': 'Проверка на стенде',
                                                         'status': status_obj(status),
                                                         'priority': priority_obj(sub_key)}}],
            }})
    return out


def make_api(dataset=None):
    """api(path, **params) поверх синтетического набора — подменяет сеть."""
    ds = dataset or Dataset()

    def api(path, **params):
        if path == '/rest/api/2/status':
            return [{'id': str(sid), 'name': name, 'statusCategory': {'name': cat}}
                    for sid, name, cat in STATUSES]
        if path == '/rest/api/2/field':
            return [{'id': 'summary', 'name': 'Summary'},
                    {'id': EPIC_FIELD, 'name': 'Ссылка на эпик'},
                    {'id': SP_FIELD, 'name': 'Story Points'},
                    {'id': 'customfield_10100', 'name': 'Sprint'}]
        if path == '/rest/agile/1.0/board':
            return {'values': [{'id': BOARD_ID, 'name': BOARD_NAME},
                               {'id': OTHER_BOARD_ID, 'name': 'Scrum Board Другая'}],
                    'isLast': True}
        if path.startswith('/rest/agile/1.0/board/') and path.count('/') == 5:
            known = {BOARD_ID: BOARD_NAME, OTHER_BOARD_ID: 'Scrum Board Другая'}
            wanted = int(path.rsplit('/', 1)[-1])
            if wanted not in known:
                raise HttpError(404, f'board {wanted} does not exist')
            return {'id': wanted, 'name': known[wanted], 'type': 'scrum'}
        if path == f'/rest/agile/1.0/board/{BOARD_ID}/sprint':
            wanted = set((params.get('state') or 'active').split(','))
            return {'values': [s for s in ds.sprints if s['state'] in wanted], 'isLast': True}
        if path.startswith('/rest/agile/1.0/sprint/') and path.endswith('/issue'):
            sid = int(path.split('/')[-2])
            issues = ds.issues.get(sid, [])
            start = int(params.get('startAt', 0))
            page = issues[start:start + int(params.get('maxResults', 50))]
            return {'issues': [project(i, params.get('fields', ''), params.get('expand')) for i in page],
                    'total': len(issues), 'startAt': start}
        if path == '/rest/api/2/search':
            jql = params.get('jql', '')
            inside = jql[jql.find('(') + 1:jql.find(')')] if '(' in jql else ''
            keys = [k.strip() for k in inside.split(',') if k.strip()]
            if jql.startswith('parent in'):
                # подзадачи объёма эпиков: полные из спринтов, заглушки — с датами родителя
                full = {i['key']: i for sp in ds.sprints for i in ds.issues.get(sp['id'], [])}
                parents = {i['key']: i for i in epic_scope(ds)}
                subs = []
                for pk in keys:
                    parent = parents.get(pk) or full.get(pk)
                    for stub in (parent or {'fields': {}})['fields'].get('subtasks') or []:
                        if stub['key'] in full:
                            subs.append(full[stub['key']])
                        else:
                            pf = parent['fields']
                            subs.append({'key': stub['key'], 'fields': {
                                'status': stub['fields']['status'], 'created': pf.get('created'),
                                'resolutiondate': pf.get('resolutiondate')}})
                start = int(params.get('startAt', 0))
                page = subs[start:start + int(params.get('maxResults', 50))]
                return {'issues': [project(i, params.get('fields', ''), None) for i in page],
                        'total': len(subs), 'startAt': start}
            if jql.startswith('cf['):
                # весь объём эпиков: задачи всех спринтов набора плюс вне спринтов
                wanted = set(keys)
                scope = [i for i in epic_scope(ds) if i['fields'].get(EPIC_FIELD) in wanted]
                start = int(params.get('startAt', 0))
                page = scope[start:start + int(params.get('maxResults', 50))]
                return {'issues': [project(i, params.get('fields', ''), None) for i in page],
                        'total': len(scope), 'startAt': start}
            titles = dict(EPICS)
            want = params.get('fields', 'summary').split(',')
            return {'issues': [{'key': k, 'fields': {f: v for f, v in
                                                     (('summary', titles.get(k, 'Эпик ' + k)),
                                                      ('priority', priority_obj(k)),
                                                      ('duedate', '2026-10-15' if k == EPICS[0][0] else None))
                                                     if f in want}}
                               for k in keys if k in titles],
                    'total': len(keys)}
        raise AssertionError(f'синтетическая JIRA не знает ручку {path}')

    return api, ds
