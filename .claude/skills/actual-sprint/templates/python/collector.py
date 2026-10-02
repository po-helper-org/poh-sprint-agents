#!/usr/bin/env python3
"""Базовый сборщик данных отчёта по спринту (протокол 1, Python, только stdlib).

Забирает из JIRA всё, что нужно одной команде: эпики с историями и подзадачами,
метрики за N спринтов, burndown, диаграммы управления, velocity и ленту активности.
Читает запрос из stdin, отдаёт один объект команды в stdout (contract/PROTOCOL.md).

    echo '{"protocol":1,"team":{...},"params":{},"jira":{...},"now":"…"}' | collector.py
    collector.py --record fixtures/   # сохранить сырые ответы JIRA
    collector.py --replay fixtures/   # работать из них, без сети

Те же режимы доступны через params.record и params.replay — так их можно включить
из конфига, не меняя строку запуска (на этом стоят тесты и сверка после правок).

Все правила команды — в params, дефолты равны поведению до вынесения:

    story_types      ["История", "История Enabler", "Story"]  что считать историей
    done_statuses    doneExact из status_rules.json            что считать закрытым по имени
    status_buckets   {}                 «у нас "Ожидает релиза" на самом деле ревью»
    epic_link_field  "auto"             или customfield_XXXXX
    epic_link_names  ["ссылка на эпик", "epic link"]  по каким именам искать поле
    sprints_back     3                  глубина метрик по спринтам
    activity_days    период спринта     окно ленты активности; не задано — с начала текущего спринта
    control_days     30                 окно диаграмм управления
    categories       из status_rules.json               допустимые категории JIRA
    done_categories  ["Выполнено", "Done"]      категории «закрыто» для Lead/Cycle Time
    progress_categories ["В работе", "In Progress"]   категории «взято в работу"
    epic_scope       true               забрать весь объём эпиков, не только задачи спринта
    epic_scope_max   2000               сколько задач эпиков забирать максимум за запуск
    sp_field         "auto"             поле Story Points или customfield_XXXXX
    sp_names         ["story points", "story point estimate", …]  по каким именам искать поле

Точки, которые обычно правят под команду, помечены «# TEAM RULE:».
"""
import argparse
import hashlib
import json
import os
import re
import ssl
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

PROTOCOL = 1
VERSION = '1.5.0'
NAME = 'base'

EXIT_OK, EXIT_ERROR, EXIT_CONFIG, EXIT_JIRA = 0, 1, 2, 3

CONTRACT_ENV = 'ACTUAL_SPRINT_CONTRACT'


class ConfigProblem(Exception):
    """Запрос или params непригодны — код выхода 2."""


class JiraProblem(Exception):
    """JIRA недоступна или не авторизует — код выхода 3."""


def log(msg):
    """Прогресс идёт в stderr: stdout занят единственным JSON-объектом."""
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------- правила бакетов

def load_rules(params):
    """Правила раскладки статусов. Общий модуль контракта, чтобы не плодить копии."""
    contract = os.environ.get(CONTRACT_ENV)
    candidates = [Path(contract)] if contract else []
    candidates += [Path(__file__).resolve().parents[2] / 'contract', Path(__file__).resolve().parent]
    for path in candidates:
        if (path / 'buckets.py').is_file():
            sys.path.insert(0, str(path))
            import buckets
            try:
                return buckets.load(overrides=params.get('status_buckets') or {},
                                    done_exact=params.get('done_statuses'),
                                    categories=params.get('categories'),
                                    done_categories=params.get('done_categories'),
                                    progress_categories=params.get('progress_categories'))
            except ValueError as exc:
                raise ConfigProblem(str(exc)) from exc
    raise ConfigProblem(
        f'не найден contract/buckets.py с правилами бакетов. Укажите каталог контракта '
        f'в переменной {CONTRACT_ENV}.')


# --------------------------------------------------------------- доступ к JIRA

class Jira:
    """GET-клиент JIRA со включённой проверкой TLS, счётчиком запросов и record/replay.

    Только чтение: другого метода, кроме GET, у клиента нет (НФТ-4).
    """

    def __init__(self, base, token, ca_bundle=None, record=None, replay=None):
        self.base = base.rstrip('/')
        self.token = token
        self.requests = 0
        self.record = Path(record) if record else None
        self.replay = Path(replay) if replay else None
        if self.record:
            self.record.mkdir(parents=True, exist_ok=True)
        # проверка сертификата включена всегда; корпоративный CA — через ca_bundle
        try:
            self.ctx = ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle else None)
        except OSError as exc:
            # голый «No such file or directory» без пути стоит часа отладки
            raise ConfigProblem(f'не читается CA-бандл {ca_bundle}: {exc.strerror}. '
                                f'Проверьте jira.ca_bundle в конфиге.') from exc

    @staticmethod
    def _key(path, params):
        canon = path + '?' + urllib.parse.urlencode(sorted(params.items()))
        return hashlib.sha1(canon.encode()).hexdigest()[:16], canon

    def api(self, path, **params):
        key, canon = self._key(path, params)
        self.requests += 1
        if self.replay:
            fixture = self.replay / f'{key}.json'
            if not fixture.is_file():
                raise JiraProblem(f'в replay-каталоге нет ответа на GET {canon} '
                                  f'(ожидался файл {fixture.name})')
            return json.loads(fixture.read_text(encoding='utf-8'))

        url = self.base + path + ('?' + urllib.parse.urlencode(params) if params else '')
        req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.token})
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=120) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise JiraProblem(f'JIRA не авторизует запрос (HTTP {exc.code}) — проверьте токен') from exc
            raise JiraProblem(f'JIRA вернула HTTP {exc.code} на GET {canon}') from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise JiraProblem(
                    f'сертификат JIRA не проверился ({exc.reason.verify_message or exc.reason}). '
                    f'Если инстанс за корпоративным CA, укажите путь к бандлу в jira.ca_bundle '
                    f'конфига. Проверку сертификата не отключаем: по этому соединению идёт '
                    f'личный токен.') from exc
            raise JiraProblem(f'JIRA недоступна ({exc.reason}) — проверьте VPN и адрес') from exc
        if self.record:
            # в дамп идут только путь, параметры и тело ответа: заголовок с токеном — никогда
            (self.record / f'{key}.json').write_text(
                json.dumps(data, ensure_ascii=False, sort_keys=True), encoding='utf-8')
            index = self.record / '_index.json'
            known = json.loads(index.read_text(encoding='utf-8')) if index.is_file() else {}
            known[key] = canon
            index.write_text(json.dumps(known, ensure_ascii=False, indent=1, sort_keys=True),
                             encoding='utf-8')
        return data

    def paged(self, path, key='values', **params):
        """Обходит постраничный ответ целиком: у досок с длинной историей спринтов
        первая страница отдаёт самые старые записи, и активный спринт теряется."""
        out, start = [], 0
        while True:
            d = self.api(path, startAt=start, maxResults=50, **params)
            vals = d.get(key, [])
            out += vals
            start += len(vals)
            if d.get('isLast', True) or not vals:
                return out

    def sprint_issues(self, sprint_id, fields, expand=None):
        out, start = [], 0
        while True:
            params = {'fields': fields, 'maxResults': 200, 'startAt': start}
            if expand:
                params['expand'] = expand
            d = self.api(f'/rest/agile/1.0/sprint/{sprint_id}/issue', **params)
            out += d['issues']
            start += len(d['issues'])
            if start >= d.get('total', 0) or not d['issues']:
                return out


# --------------------------------------------------------------- помощники

_TZ_RE = re.compile(r'([+-]\d{2})(\d{2})$')


def parse(ts):
    """fromisoformat, толерантный к формату JIRA: '+0300' без двоеточия, 'Z'.

    Шаблон сборщика не импортирует код раннера: он копируется в проект команды
    и работает автономно, поэтому нормализация продублирована здесь (3.10)."""
    text = ts.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    m = _TZ_RE.search(text)
    if m and ':' not in text[m.start():]:
        text = text[:m.start()] + m.group(1) + ':' + m.group(2)
    return datetime.fromisoformat(text)


def plural(n, one, few, many):
    """Склонение числительного: предупреждения читают люди."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {'mean': round(statistics.mean(vals), 1),
            'median': round(statistics.median(vals), 1),
            'count': len(vals)}


def priority_name(fields):
    """Имя приоритета как в JIRA; поле выключено в схеме проекта → None."""
    return ((fields or {}).get('priority') or {}).get('name')


def last_status_change(issue):
    """Дата последней смены статуса. Нет смен — дата создания.
    fields.updated не годится: двигается от любой правки."""
    last = None
    for h in issue.get('changelog', {}).get('histories', []):
        for it in h['items']:
            if it['field'] == 'status' and (last is None or h['created'] > last):
                last = h['created']
    return last or issue['fields']['created']


def lead_cycle(issue, cats, rules):
    """(lead, cycle, done_at) в днях. Переоткрытие сбрасывает дату закрытия.

    Что считать «взяли в работу» и «закрыли» — категории из правил, а не строки
    здесь: у англоязычного workflow они называются иначе.
    """
    f = issue['fields']
    created = parse(f['created'])
    done_at = start_at = None
    for h in sorted(issue.get('changelog', {}).get('histories', []), key=lambda x: x['created']):
        for it in h['items']:
            if it['field'] != 'status':
                continue
            cat = cats.get(str(it.get('to')))
            when = parse(h['created'])
            if rules.is_progress(cat) and start_at is None:
                start_at = when
            if rules.is_done(cat):
                done_at = when
            elif done_at is not None:
                done_at = None
    is_done = rules.is_done(cats.get(str(f['status']['id'])))
    if not (is_done and done_at):
        return None, None, None
    lead = round((done_at - created).total_seconds() / 86400, 2)
    cycle = round((done_at - start_at).total_seconds() / 86400, 2) if start_at else None
    return lead, cycle, done_at


def value_at(issue, field, moment):
    """(значение, id) поля из changelog на момент moment: статус и исполнитель на конец
    спринта, а не сейчас. Смен до момента нет — берётся «from» первой смены после него;
    смен нет вовсе — None (значит, текущее значение)."""
    changes = sorted(((h['created'], it) for h in issue.get('changelog', {}).get('histories', [])
                      for it in h['items'] if it['field'] == field), key=lambda c: c[0])
    if not changes:
        return None
    before = [it for at, it in changes if parse(at) <= moment]
    if before:
        return before[-1].get('toString'), before[-1].get('to')
    return changes[0][1].get('fromString'), changes[0][1].get('from')


def status_history(issue, until, since=None):
    """Смены статуса задачи в периоде спринта [since, until]: когда, откуда, куда, кто."""
    out = []
    for h in sorted(issue.get('changelog', {}).get('histories', []), key=lambda x: x['created']):
        if parse(h['created']) > until:
            break
        if since and parse(h['created']) < since:
            continue
        for it in h['items']:
            if it['field'] == 'status':
                out.append({'at': h['created'][:16], 'from': it.get('fromString'), 'to': it.get('toString'),
                            'by': (h.get('author') or {}).get('displayName')})
    return out


def in_progress_since(issue, cats, rules):
    """Когда задачу взяли в работу, если она до сих пор не закрыта. Иначе None."""
    if rules.is_done(cats.get(str(issue['fields']['status']['id']))):
        return None
    start = None
    for h in sorted(issue.get('changelog', {}).get('histories', []), key=lambda x: x['created']):
        for it in h['items']:
            if it['field'] == 'status' and rules.is_progress(cats.get(str(it.get('to')))) \
                    and start is None:
                start = parse(h['created'])
    return start


class Collector:
    def __init__(self, jira, request, rules):
        self.jira = jira
        self.rules = rules
        self.params = request.get('params') or {}
        self.team = request['team']
        self.now = parse(request['now'])
        self.warnings = []
        self.status_map = {}
        self.cats = {}      # id статуса -> категория; заполняется в collect()
        p = self.params
        # TEAM RULE: что считать историей внутри эпика
        self.story_types = tuple(p.get('story_types') or ('История', 'История Enabler', 'Story'))
        self.sprints_back = int(p.get('sprints_back', 3))
        # окно ленты: по умолчанию — период текущего спринта (с его начала), а не N дней
        self.activity_days = int(p['activity_days']) if p.get('activity_days') else None
        self.control_days = int(p.get('control_days', 30))
        self.epic_scope = bool(p.get('epic_scope', True))
        self.epic_scope_max = int(p.get('epic_scope_max', 2000))
        self.sp_id = None   # поле Story Points; находится в collect()

    # ---------------------------------------------------------- инфраструктура

    def warn(self, text):
        if text not in self.warnings:
            self.warnings.append(text)

    def bucket(self, status, category):
        """Бакет статуса + запись в statusMap: раскладка считается один раз (ФТ-18)."""
        bucket, rule = self.rules.classify(status, category)
        self.status_map[status] = bucket
        if rule == 'category-default' and bucket == 'progress':
            self.warn(f'статус «{status}» не покрыт правилами бакетов → progress')
        return bucket

    def status_categories(self):
        """Карта «id статуса → категория». По id, а не по имени: в changelog имена
        приходят на языке workflow (Closed/In progress), а /status отдаёт русские."""
        return {str(s['id']): s['statusCategory']['name']
                for s in self.jira.api('/rest/api/2/status')}

    def board_name(self, board_id):
        """Имя доски одним запросом по id: на инстансе с сотнями досок обход списка
        стоит десяток запросов и упирается в права видимости."""
        try:
            return self.jira.api(f'/rest/agile/1.0/board/{board_id}')['name']
        except JiraProblem as exc:
            if 'HTTP 404' in str(exc):
                raise ConfigProblem(f'доски #{board_id} не существует или она не видна этому '
                                    f'токену — проверьте board в конфиге') from exc
            raise

    def epic_link_field(self):
        """TEAM RULE: через какое поле история связана с эпиком."""
        explicit = self.params.get('epic_link_field', 'auto')
        if explicit and explicit != 'auto':
            return explicit
        names = [n.lower() for n in (self.params.get('epic_link_names')
                                     or ('ссылка на эпик', 'epic link'))]
        for f in self.jira.api('/rest/api/2/field'):
            if f['name'].strip().lower() in names:
                return f['id']
        self.warn('поле связи с эпиком не найдено — все истории уйдут в «Без эпика». '
                  'Задайте params.epic_link_field.')
        return None

    def sp_field(self):
        """TEAM RULE: поле Story Points. Нет его — выработка считается в задачах."""
        explicit = self.params.get('sp_field', 'auto')
        if explicit and explicit != 'auto':
            return explicit
        names = [n.lower() for n in (self.params.get('sp_names')
                                     or ('story points', 'story point estimate', 'сторипоинты', 'стори поинты'))]
        for f in self.jira.api('/rest/api/2/field'):
            if f['name'].strip().lower() in names:
                return f['id']
        self.warn('поле Story Points не найдено — выработка участников в задачах. Задайте params.sp_field.')
        return None

    # ---------------------------------------------------------- сбор

    def collect(self):
        board_id = self.team['board']
        self.cats = self.status_categories()
        epic_field = self.epic_link_field()
        self.sp_id = self.sp_field()

        board_name = self.board_name(board_id)

        sprints = [s for s in self.jira.paged(f'/rest/agile/1.0/board/{board_id}/sprint',
                                              state='closed,active')
                   if s.get('originBoardId') == board_id]
        sprints.sort(key=lambda s: s.get('startDate') or '')
        if not sprints:
            raise ConfigProblem(f'у доски {board_id} нет спринтов — проверьте board в конфиге')
        # активный спринт — якорь отчёта; последние N отсчитываем от него, а не от конца списка
        active = next((s for s in reversed(sprints) if s['state'] == 'active'), sprints[-1])
        idx = sprints.index(active)
        last = sprints[max(0, idx - (self.sprints_back - 1)):idx + 1]
        if len(last) < self.sprints_back:
            self.warn(f'спринтов у доски меньше, чем sprints_back={self.sprints_back}: '
                      f'метрики посчитаны по {len(last)}')
        log(f'доска «{board_name}», спринт «{active["name"]}», метрики по {len(last)} спринтам')

        fields = 'key,summary,status,issuetype,created,creator,assignee,subtasks,priority'
        if epic_field:
            fields += ',' + epic_field  # иначе пришлось бы делать запрос на каждую историю
        if self.sp_id:
            fields += ',' + self.sp_id
        per_sprint = {s['id']: self.jira.sprint_issues(s['id'], fields, expand='changelog')
                      for s in last}
        # второй пакетный проход: в ответе с expand=changelog комментариев нет
        with_comments = {s['id']: self.jira.sprint_issues(
            s['id'], 'key,summary,issuetype,created,creator,comment') for s in last}

        issues = per_sprint[active['id']]
        epics = self.build_epics(issues, epic_field)
        self.build_scope(epics, epic_field, last, per_sprint, active)
        metrics, velocity = self.build_metrics(last, per_sprint)
        burndown = self.build_burndown(active, issues)
        control = self.build_control(last, per_sprint)
        logs = self.build_logs(last, per_sprint, with_comments, active)
        output = self.build_output(last, per_sprint, active, with_comments)

        return {
            'slug': self.team['slug'], 'team': self.team['name'], 'boardId': board_id,
            'boardName': board_name,
            'boardUrl': f'{self.jira.base}/secure/RapidBoard.jspa?rapidView={board_id}',
            'jiraBase': self.jira.base, 'sprintName': active['name'],
            'epics': epics, 'metrics': metrics, 'burndown': burndown, 'control': control,
            'velocity': velocity, 'output': output, 'logs': logs,
            'statusMap': dict(sorted(self.status_map.items())),
        }

    def build_epics(self, issues, epic_field):
        stories = [i for i in issues if i['fields']['issuetype']['name'] in self.story_types]
        if issues and not stories:
            self.warn(f'ни одна задача спринта не попала в story_types {list(self.story_types)} — '
                      f'таблица эпиков будет пустой')
        groups, order, epic_cache, epic_prio, epic_due = {}, [], {}, {}, {}

        # ключи эпиков уже пришли в полях историй; названия добираем одним запросом на все
        epic_keys = sorted({st['fields'].get(epic_field) for st in stories
                            if epic_field and st['fields'].get(epic_field)})
        # пачками: длина JQL и maxResults не резиновые, а эпиков у команды бывает много
        chunk = int(self.params.get('epic_batch', 50))
        for start in range(0, len(epic_keys), chunk):
            batch = epic_keys[start:start + chunk]
            jql = 'key in (' + ','.join(batch) + ')'
            found = self.jira.api('/rest/api/2/search', jql=jql, fields='summary,priority,duedate',
                                  maxResults=len(batch))['issues']
            epic_cache.update({i['key']: i['fields']['summary'] for i in found})
            epic_prio.update({i['key']: priority_name(i['fields']) for i in found})
            # плановая дата закрытия эпика — для графика сгорания на KR
            epic_due.update({i['key']: (i['fields'].get('duedate') or None) for i in found})
        missing = [k for k in epic_keys if k not in epic_cache]
        if missing:
            self.warn(f'{len(missing)} эпиков не отдались по ключу (нет прав или удалены): '
                      f'{", ".join(missing[:3])}')

        orphans = 0
        for st in stories:
            f = st['fields']
            ek = f.get(epic_field) if epic_field else None
            gkey = ek or 'no-epic'
            if not ek:
                orphans += 1
            row = groups.setdefault(gkey, {
                'rowId': gkey, 'epicKey': ek,
                'epicTitle': epic_cache.get(ek) if ek else 'Без эпика',
                'epicPriority': epic_prio.get(ek) if ek else None,
                'epicDue': epic_due.get(ek) if ek else None, 'stories': []})
            if gkey not in order:
                order.append(gkey)
            row['stories'].append({
                'key': st['key'], 'title': f['summary'],
                'status': f['status']['name'],
                'category': self.cats.get(str(f['status']['id'])) or '',
                'statusChanged': last_status_change(st),
                'assignee': (f.get('assignee') or {}).get('displayName'),
                'priority': priority_name(f),
                'subtasks': [{
                    'key': s['key'], 'summary': s['fields']['summary'],
                    'status': s['fields']['status']['name'],
                    'category': s['fields']['status']['statusCategory']['name'],
                    'statusChanged': None, 'assignee': None,
                    # приоритет есть и в заглушке подзадачи, но полная задача точнее
                    'priority': priority_name(s['fields']),
                } for s in (f.get('subtasks') or [])],
            })
        if orphans:
            self.warn(f'{orphans} {plural(orphans, "история", "истории", "историй")} '
                      f'без эпика → псевдо-эпик «Без эпика»')

        # даты и исполнители подзадач — из общего списка спринта, без запроса на каждую
        by_key = {i['key']: i for i in issues}
        for row in groups.values():
            for st in row['stories']:
                self.bucket(st['status'], st['category'])
                for sub in st['subtasks']:
                    self.bucket(sub['status'], sub['category'])
                    src = by_key.get(sub['key'])
                    if src:
                        sub['statusChanged'] = last_status_change(src)
                        sub['assignee'] = (src['fields'].get('assignee') or {}).get('displayName')
                        sub['priority'] = priority_name(src['fields']) or sub['priority']
        return [groups[k] for k in order]

    def build_scope(self, epics, epic_field, sprints, per_sprint, active):
        """Весь объём каждого эпика — и то, что в спринте, и сделанное раньше, и бэклог.

        Таблица и панель эпика показывают только задачи спринта; «Весь эпик» на странице
        отвечает на другой вопрос: что по эпику уже сделано и что осталось. Один пакетный
        поиск на пачку эпиков, а не запрос на эпик. Подзадачи — из заглушек в полях
        задачи: отдельный запрос на каждую стоил бы на порядок дороже.
        """
        keys = [e['epicKey'] for e in epics if e['epicKey']]
        if not (self.epic_scope and epic_field and keys):
            return
        # в каком спринте отчёта задача была: «в спринте», имя прошлого спринта или ничего
        where = {}
        for s in sprints:
            for i in per_sprint[s['id']]:
                where[i['key']] = s['name']
        # TEAM RULE: как в JQL сослаться на поле связи с эпиком
        m = re.match(r'customfield_(\d+)$', epic_field)
        field_ref = f'cf[{m.group(1)}]' if m else f'"{epic_field}"'
        fields = f'summary,status,issuetype,assignee,priority,subtasks,created,resolutiondate,{epic_field}'
        chunk = int(self.params.get('epic_batch', 50))
        by_epic, seen = {k: [] for k in keys}, 0
        for start in range(0, len(keys), chunk):
            batch = keys[start:start + chunk]
            jql = f'{field_ref} in ({",".join(batch)}) ORDER BY Rank ASC'
            at = 0
            while seen < self.epic_scope_max:
                page = self.jira.api('/rest/api/2/search', jql=jql, fields=fields,
                                     startAt=at, maxResults=100)
                found = page.get('issues', [])
                for i in found:
                    f = i['fields']
                    if f['issuetype'].get('subtask'):
                        continue
                    ek = f.get(epic_field)
                    if ek not in by_epic:
                        continue
                    seen += 1
                    status = f['status']['name']
                    category = self.cats.get(str(f['status']['id'])) or \
                        f['status'].get('statusCategory', {}).get('name', '')
                    bucket = self.bucket(status, category)
                    done_at = f.get('resolutiondate') if bucket == 'done' else None
                    item = {
                        'key': i['key'], 'title': f['summary'], 'type': f['issuetype']['name'],
                        'status': status, 'category': category,
                        'assignee': (f.get('assignee') or {}).get('displayName'),
                        'priority': priority_name(f),
                        'sprint': where.get(i['key']), 'inSprint': where.get(i['key']) == active['name'],
                        # даты — для графика сгорания эпика: когда задача появилась и когда закрыта
                        'created': (f.get('created') or '')[:10] or None,
                        'doneAt': done_at[:10] if done_at else None,
                        'subtasks': [],
                    }
                    for sub in f.get('subtasks') or []:
                        sf = sub['fields']
                        sub_cat = sf['status'].get('statusCategory', {}).get('name', '')
                        self.bucket(sf['status']['name'], sub_cat)
                        item['subtasks'].append({
                            'key': sub['key'], 'summary': sf['summary'], 'status': sf['status']['name'],
                            'category': sub_cat, 'priority': priority_name(sf)})
                    by_epic[ek].append(item)
                at += len(found)
                if not found or at >= page.get('total', 0):
                    break
            if seen >= self.epic_scope_max:
                self.warn(f'объём эпиков обрезан на {self.epic_scope_max} задачах — '
                          f'поднимите params.epic_scope_max')
                break
        for e in epics:
            if e['epicKey']:
                e['scope'] = by_epic.get(e['epicKey'], [])

    def build_metrics(self, sprints, per_sprint):
        sprint_rows, all_closed, velocity = [], [], []
        for s in sprints:
            rows = []
            counts = self.rules.empty_counts()
            for i in per_sprint[s['id']]:
                f = i['fields']
                counts[self.bucket(f['status']['name'], self.cats.get(str(f['status']['id'])) or '')] += 1
                lead, cycle, _ = lead_cycle(i, self.cats, self.rules)
                rows.append({'lead': lead, 'cycle': cycle,
                             'story': f['issuetype']['name'] in self.story_types,
                             'subtask': bool(f['issuetype'].get('subtask')),
                             'done': lead is not None})
            closed = [r for r in rows if r['done']]
            all_closed += closed
            sprint_rows.append({
                'name': s['name'], 'total': len(rows), 'closed': len(closed),
                'open': len(rows) - len(closed),
                'throughputPct': round(100 * len(closed) / len(rows)) if rows else 0,
                'lead': stats([r['lead'] for r in closed]),
                'cycle': stats([r['cycle'] for r in closed]),
                'leadStory': stats([r['lead'] for r in closed if r['story']]),
                'leadTask': stats([r['lead'] for r in closed if not r['story'] and not r['subtask']]),
                'points': sorted(r['lead'] for r in closed if r['lead'] is not None),
            })
            velocity.append({'name': s['name'], 'planned': sum(counts.values()),
                             'done': counts['done'], 'split': counts})

        metrics = {'sprints': sprint_rows, 'overall': {
            'lead': stats([r['lead'] for r in all_closed]),
            'cycle': stats([r['cycle'] for r in all_closed]),
            'leadStory': stats([r['lead'] for r in all_closed if r['story']]),
            'leadTask': stats([r['lead'] for r in all_closed if not r['story'] and not r['subtask']]),
            'total': sum(s['total'] for s in sprint_rows), 'closed': len(all_closed)}}
        vel = {'sprints': velocity, 'unit': 'задач',
               'avgDone': round(sum(v['done'] for v in velocity) / len(velocity), 1)}
        return metrics, vel

    def build_output(self, sprints, per_sprint, active, with_comments=None):
        """Выработка участников по спринтам: задачи и Story Points по статусу на конец
        спринта (у активного — на сейчас), по исполнителю на тот же момент. Подзадачи не
        считаются: оценка живёт на задаче. Lead Time участника — медиана его закрытых."""
        out, leads = [], {}
        comments = {i['key']: (i['fields'].get('comment') or {}).get('comments') or []
                    for s in sprints for i in (with_comments or {}).get(s['id'], [])}
        for s in sprints:
            current = s['id'] == active['id']
            end = self.now if current else parse(s.get('completeDate') or s.get('endDate') or self.now.isoformat())
            begin = parse(s['startDate']) if s.get('startDate') else None
            members, items = {}, {}
            for i in per_sprint[s['id']]:
                f = i['fields']
                if f['issuetype'].get('subtask'):
                    continue
                st = value_at(i, 'status', end) if not current else None
                name, sid = st if st and st[0] else (f['status']['name'], f['status']['id'])
                bucket = self.bucket(name, self.cats.get(str(sid)) or '')
                who = value_at(i, 'assignee', end) if not current else None
                who = who[0] if who else (f.get('assignee') or {}).get('displayName')
                who = who or 'Не назначен'
                sp = f.get(self.sp_id) if self.sp_id else None
                sp = sp if isinstance(sp, (int, float)) else 0
                row = members.setdefault(who, {b: [0, 0] for b in self.rules.empty_counts()})
                row[bucket][0] += 1
                row[bucket][1] += sp
                # задачи участника: что пошло в зачёт и что нет, с движением статусов и комментариями
                items.setdefault(who, []).append({
                    'key': i['key'], 'title': f.get('summary') or '', 'status': name, 'bucket': bucket,
                    'sp': sp, 'history': status_history(i, end, begin), 'comments': [
                        {'at': c['created'][:16], 'by': (c.get('author') or {}).get('displayName'),
                         'body': (c.get('body') or '')[:400]}
                        for c in comments.get(i['key'], [])
                        if parse(c['created']) <= end and (not begin or parse(c['created']) >= begin)][-5:]})
                lead, _, _ = lead_cycle(i, self.cats, self.rules)
                if lead is not None:
                    leads.setdefault(who, {})[i['key']] = lead
            out.append({'name': s['name'], 'current': current,
                        'start': (s.get('startDate') or '')[:10] or None, 'end': (s.get('endDate') or '')[:10] or None,
                        'members': [{'name': who, 'split': {b: [n, round(sp, 1)] for b, (n, sp) in row.items()},
                                     'items': items.get(who, [])}
                                    for who, row in sorted(members.items())]})
        lead_by = {who: stats(list(v.values())) for who, v in leads.items()}
        return {'unit': 'SP' if self.sp_id else 'задач', 'field': self.sp_id, 'sprints': out,
                'lead': {who: {'median': st['median'], 'count': st['count']} for who, st in lead_by.items() if st}}

    def build_burndown(self, active, issues):
        start, end = parse(active['startDate']), parse(active['endDate'])
        members = []
        for i in issues:
            entered = left = None
            for h in sorted(i.get('changelog', {}).get('histories', []), key=lambda x: x['created']):
                for it in h['items']:
                    if it['field'].lower() != 'sprint':
                        continue
                    was = active['name'] in (it.get('fromString') or '')
                    now_in = active['name'] in (it.get('toString') or '')
                    if now_in and not was:
                        entered = parse(h['created'])
                    if was and not now_in:
                        left = parse(h['created'])
            _, _, done_at = lead_cycle(i, self.cats, self.rules)
            members.append({'entered': entered or start, 'left': left, 'doneAt': done_at})

        days, cur = [], start
        today = self.now.date().isoformat()
        while cur <= end:
            scope = closed_n = 0
            for m in members:
                if m['entered'] > cur or (m['left'] and m['left'] <= cur):
                    continue
                scope += 1
                if m['doneAt'] and m['doneAt'] <= cur:
                    closed_n += 1
            days.append({'date': cur.date().isoformat(), 'scope': scope,
                         'remaining': scope - closed_n, 'closed': closed_n,
                         'weekend': cur.weekday() >= 5, 'future': cur.date().isoformat() > today})
            cur += timedelta(days=1)
        return {'sprintName': active['name'], 'start': start.date().isoformat(),
                'end': end.date().isoformat(), 'days': days}

    def build_control(self, sprints, per_sprint):
        """Точки — закрытые за control_days (Cycle Time). Зона риска — НЕзакрытые задачи,
        которые идут дольше медианы своей группы."""
        since = self.now - timedelta(days=self.control_days)
        closed_by_group = {'stories': {}, 'subtasks': {}}
        open_by_group = {'stories': [], 'subtasks': []}

        for s in sprints:
            for i in per_sprint[s['id']]:
                f = i['fields']
                grp = 'subtasks' if f['issuetype'].get('subtask') else 'stories'
                lead, cycle, done_at = lead_cycle(i, self.cats, self.rules)
                category = self.cats.get(str(f['status']['id'])) or ''
                if done_at and cycle is not None and done_at >= since:
                    closed_by_group[grp][i['key']] = {
                        'key': i['key'], 'title': f['summary'],
                        'status': f['status']['name'], 'category': category,
                        'doneAt': done_at.date().isoformat(), 'cycle': cycle}
                    continue
                started = in_progress_since(i, self.cats, self.rules)
                if started:
                    open_by_group[grp].append({
                        'key': i['key'], 'title': f['summary'],
                        'status': f['status']['name'], 'category': category,
                        'assignee': (f.get('assignee') or {}).get('displayName'),
                        'elapsed': round((self.now - started).total_seconds() / 86400, 2)})

        def chart(group):
            points = sorted(closed_by_group[group].values(), key=lambda p: p['doneAt'])
            if not points:
                return {'points': [], 'risks': [], 'days': self.control_days}
            vals = [p['cycle'] for p in points]
            mean, median = statistics.mean(vals), statistics.median(vals)
            sd = statistics.pstdev(vals)
            limit = round(mean + sd, 2)
            for p in points:
                p['outlier'] = p['cycle'] > limit
            seen_risk = {}
            for r in open_by_group[group]:
                if r['elapsed'] > median and r['key'] not in seen_risk:
                    seen_risk[r['key']] = r
            risks = sorted(seen_risk.values(), key=lambda r: (-r['elapsed'], r['key']))
            return {'points': points, 'risks': risks, 'days': self.control_days,
                    'mean': round(mean, 1), 'median': round(median, 1), 'sd': round(sd, 1),
                    'limit': limit, 'outliers': sum(1 for p in points if p['outlier']),
                    'today': self.now.date().isoformat()}

        return {'stories': chart('stories'), 'subtasks': chart('subtasks'),
                'days': self.control_days}

    def build_logs(self, sprints, per_sprint, with_comments, active=None):
        if self.activity_days:
            since = self.now - timedelta(days=self.activity_days)
        else:
            since = parse(active['startDate']) if active and active.get('startDate') else self.now - timedelta(days=14)
        days = max(1, -(-int((self.now - since).total_seconds()) // 86400))
        events, seen = [], set()
        for s in sprints:
            for i in per_sprint[s['id']]:
                f = i['fields']
                for h in i.get('changelog', {}).get('histories', []):
                    when = parse(h['created'])
                    if when < since:
                        continue
                    for it in h['items']:
                        if it['field'] != 'status':
                            continue
                        uid = f"st:{h['id']}:{i['key']}"
                        if uid in seen:
                            continue
                        seen.add(uid)
                        events.append({'kind': 'status', 'key': i['key'], 'title': f['summary'],
                                       'author': (h.get('author') or {}).get('displayName') or 'Система',
                                       'at': when.isoformat(),
                                       'from': it.get('fromString') or '—',
                                       'to': it.get('toString') or '—',
                                       'toCat': self.cats.get(str(it.get('to'))) or ''})
            for i in with_comments[s['id']]:
                f = i['fields']
                created = parse(f['created'])
                if created >= since and f'cr:{i["key"]}' not in seen:
                    seen.add(f'cr:{i["key"]}')
                    events.append({'kind': 'created', 'key': i['key'], 'title': f['summary'],
                                   'author': (f.get('creator') or {}).get('displayName') or 'Система',
                                   'at': created.isoformat(),
                                   'issueType': f['issuetype']['name']})
                for c in (f.get('comment') or {}).get('comments', []):
                    when = parse(c['created'])
                    if when < since or f'cm:{c["id"]}' in seen:
                        continue
                    seen.add(f'cm:{c["id"]}')
                    body = ' '.join((c.get('body') or '').split())
                    events.append({'kind': 'comment', 'key': i['key'], 'title': f['summary'],
                                   'author': (c.get('author') or {}).get('displayName') or 'Система',
                                   'at': when.isoformat(),
                                   'body': body[:160] + '…' if len(body) > 160 else body})
        # ключ сортировки со вторичным полем: одинаковые метки времени не должны
        # переставляться между запусками (НФТ-1)
        events.sort(key=lambda e: (e['at'], e['key'], e['kind']), reverse=True)
        authors, kinds = {}, {}
        for e in events:
            authors[e['author']] = authors.get(e['author'], 0) + 1
            kinds[e['kind']] = kinds.get(e['kind'], 0) + 1
        return {'events': events, 'days': days, 'since': since.date().isoformat(), 'kinds': kinds,
                'authors': sorted(authors.items(), key=lambda x: (-x[1], x[0]))}


def read_request(stream):
    raw = stream.read()
    if not raw.strip():
        raise ConfigProblem('на stdin не пришёл JSON-запрос (см. contract/PROTOCOL.md)')
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigProblem(f'запрос на stdin не разбирается как JSON: {exc}') from exc
    if req.get('protocol') != PROTOCOL:
        raise ConfigProblem(f'сборщик знает protocol {PROTOCOL}, в запросе {req.get("protocol")!r}')
    for field in ('team', 'now'):
        if field not in req:
            raise ConfigProblem(f'в запросе нет поля {field}')
    for field in ('slug', 'name', 'board'):
        if field not in (req.get('team') or {}):
            raise ConfigProblem(f'в запросе нет team.{field}')
    return req


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--record', default=None, help='каталог для сырых ответов JIRA')
    ap.add_argument('--replay', default=None, help='каталог с ответами: работать без сети')
    args = ap.parse_args(argv)

    started = datetime.now()
    try:
        req = read_request(sys.stdin)
        params = req.get('params') or {}
        rules = load_rules(params)
        record = args.record or params.get('record')
        replay = args.replay or params.get('replay')
        jira_spec = req.get('jira') or {}
        base = (jira_spec.get('url') or '').rstrip('/')
        if not base and not replay:
            raise ConfigProblem('в запросе нет jira.url')
        token_env = params.get('token_env', 'JIRA_PERSONAL_TOKEN')
        token = os.environ.get(token_env, '')
        if not token and not replay:
            raise JiraProblem(f'нет токена в переменной окружения {token_env}')
        if token:
            try:
                token.encode('latin-1')
            except UnicodeEncodeError:
                raise ConfigProblem(
                    f'в {token_env} есть символы вне latin-1 — такой заголовок нельзя отправить. '
                    f'Похоже, в переменную попал не токен: скопируйте его заново.') from None
        jira = Jira(base or 'https://replay.invalid', token, jira_spec.get('caBundle'),
                    record=record, replay=replay)
        collector = Collector(jira, req, rules)
        data = collector.collect()
    except ConfigProblem as exc:
        log(f'ошибка конфигурации: {exc}')
        return EXIT_CONFIG
    except JiraProblem as exc:
        log(f'JIRA: {exc}')
        return EXIT_JIRA
    except KeyError as exc:
        log(f'неожиданная форма ответа JIRA: нет поля {exc}')
        return EXIT_ERROR

    # на replay длительность не измеряется: иначе прогон по одним и тем же
    # фикстурам давал бы разный stdout, а НФТ-1 требует побайтового совпадения
    duration = 0 if replay else int((datetime.now() - started).total_seconds() * 1000)
    data['_meta'] = {
        'collector': NAME, 'version': VERSION, 'protocol': PROTOCOL,
        'collectedAt': req['now'], 'requests': jira.requests,
        'durationMs': duration,
        'warnings': collector.warnings,
    }
    # sort_keys — часть детерминизма: одинаковый вход даёт побайтово одинаковый stdout
    json.dump(data, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write('\n')
    m = data['metrics']['overall']
    log(f'эпиков {len(data["epics"])} | закрыто {m["closed"]}/{m["total"]} | '
        f'событий {len(data["logs"]["events"])} | запросов {jira.requests}')
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
