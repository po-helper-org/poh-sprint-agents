#!/usr/bin/env python3
"""Снимок задач команды для отчёта по блокерам: JIRA → один JSON без модели.

Два транспорта, одна форма снимка:
  - mcp  — скрипт сам говорит с MCP-сервером Atlassian по stdio (mcp-atlassian,
           инструмент jira_search). Для окружений, где JIRA разрешена только через
           официальный MCP: данные везёт скрипт, а не агент.
  - rest — GET /rest/api/2/search с личным токеном, проверка TLS включена всегда,
           корпоративный CA — через jira.ca_bundle. Есть replay для тестов.

Только чтение: ни один транспорт не умеет писать в JIRA.

Задача снимка:
  {key, summary, type, subtask, status, assignee, parent, created, resolved,
   statusLog: [{at, from, to, author}], comments: [{at, author, body}],
   links: [{label, key, summary, status}]}
label — как связь читается от этой задачи: «is blocked by», «depends on», …
"""
import hashlib
import json
import os
import select
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

FIELDS = 'summary,status,issuetype,assignee,parent,created,resolutiondate,issuelinks,comment'
PAGE = 50
MCP_TIMEOUT = 180
MCP_PROTOCOL = '2025-06-18'


class SourceError(Exception):
    """JIRA или MCP недоступны, ответ не той формы. Текст готов к показу человеку."""


def period_jql(jql, date_from, date_to):
    """Задачи, которые могли стоять в периоде: менялись после его начала или ещё
    не решены (простояли весь квартал без единой правки), созданы до конца.
    Порядок — по ключу: снимок воспроизводим."""
    return (f'({jql}) AND (updated >= "{date_from}" OR resolution is EMPTY) '
            f'AND created <= "{date_to} 23:59" ORDER BY key ASC')


# ------------------------------------------------------------------ нормализация

def _name(obj, *fields):
    if not isinstance(obj, dict):
        return obj if isinstance(obj, str) else None
    for f in fields:
        if obj.get(f):
            return obj[f]
    return None


def _link(raw, inward_key, outward_key, other_fields):
    kind = raw.get('type') or {}
    if raw.get(inward_key):
        other, label = raw[inward_key], kind.get('inward')
    elif raw.get(outward_key):
        other, label = raw[outward_key], kind.get('outward')
    else:
        return None
    fields = other_fields(other)
    return {'label': label, 'key': other.get('key'), 'summary': fields.get('summary', ''),
            'status': _name(fields.get('status'), 'name')}


def from_mcp_issue(raw):
    """Задача из ответа jira_search mcp-atlassian (поля уже «расплющены»)."""
    log = []
    for entry in raw.get('changelogs') or []:
        for item in entry.get('items') or []:
            if item.get('field') == 'status':
                log.append({'at': entry.get('created'), 'from': item.get('from_string'),
                            'to': item.get('to_string'),
                            'author': _name(entry.get('author'), 'display_name', 'name')})
    links = [_link(ln, 'inward_issue', 'outward_issue', lambda o: o.get('fields') or {})
             for ln in raw.get('issuelinks') or []]
    parent = raw.get('parent') or {}
    return {
        'key': raw['key'], 'summary': raw.get('summary', ''),
        'type': _name(raw.get('issue_type'), 'name'), 'subtask': bool(parent.get('key')),
        'status': _name(raw.get('status'), 'name'),
        'assignee': _name(raw.get('assignee'), 'display_name', 'name'),
        'parent': parent.get('key'), 'created': raw.get('created'), 'resolved': raw.get('resolutiondate'),
        'statusLog': log,
        'comments': [{'at': c.get('created'), 'author': _name(c.get('author'), 'display_name', 'name'),
                      'body': c.get('body', '')} for c in raw.get('comments') or []],
        'links': [ln for ln in links if ln],
    }


def from_rest_issue(raw):
    """Задача из /rest/api/2/search?expand=changelog."""
    f = raw.get('fields') or {}
    log = []
    for entry in (raw.get('changelog') or {}).get('histories') or []:
        for item in entry.get('items') or []:
            if item.get('field') == 'status':
                log.append({'at': entry.get('created'), 'from': item.get('fromString'),
                            'to': item.get('toString'),
                            'author': _name(entry.get('author'), 'displayName', 'name')})
    links = [_link(ln, 'inwardIssue', 'outwardIssue', lambda o: o.get('fields') or {})
             for ln in f.get('issuelinks') or []]
    itype = f.get('issuetype') or {}
    return {
        'key': raw['key'], 'summary': f.get('summary', ''), 'type': itype.get('name'),
        'subtask': bool(itype.get('subtask') or (f.get('parent') or {}).get('key')),
        'status': _name(f.get('status'), 'name'),
        'assignee': _name(f.get('assignee'), 'displayName', 'name'),
        'parent': (f.get('parent') or {}).get('key'), 'created': f.get('created'),
        'resolved': f.get('resolutiondate'), 'statusLog': log,
        'comments': [{'at': c.get('created'), 'author': _name(c.get('author'), 'displayName', 'name'),
                      'body': c.get('body', '')} for c in (f.get('comment') or {}).get('comments') or []],
        'links': [ln for ln in links if ln],
    }


# ------------------------------------------------------------------ транспорты

class McpTransport:
    """Клиент MCP по stdio: initialize → tools/call jira_search постранично."""

    name = 'mcp'
    jira_base = None

    def __init__(self, cmd, timeout=MCP_TIMEOUT):
        self.cmd = list(cmd)
        self.timeout = timeout
        self.proc = None
        self.seq = 0

    def __enter__(self):
        try:
            # бинарный канал без буфера: строки собираем сами, иначе select не видит
            # ответ, который уже прочитан в буфер вместе с нотификацией
            self.proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, bufsize=0)
        except OSError as exc:
            raise SourceError(f'MCP-сервер не запустился ({" ".join(self.cmd)}): {exc.strerror}') from exc
        self.buf = b''
        try:
            self._handshake()
        except BaseException:
            self.__exit__()
            raise
        return self

    def _handshake(self):
        self._call('initialize', {'protocolVersion': MCP_PROTOCOL, 'capabilities': {},
                                  'clientInfo': {'name': 'sprint-blockers', 'version': '1'}})
        self._send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def __exit__(self, *exc):
        if not self.proc:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass

    def _send(self, msg):
        try:
            self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8'))
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise SourceError('MCP-сервер закрыл соединение') from exc

    def _line(self, method, deadline):
        """Следующая строка ответа сервера; ждём не дольше deadline."""
        while b'\n' not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.proc.stdout], [], [], left)[0]:
                raise SourceError(f'MCP-сервер не ответил на {method} за {self.timeout} с')
            chunk = os.read(self.proc.stdout.fileno(), 65536)
            if not chunk:
                raise SourceError(f'MCP-сервер завершился, не ответив на {method}. Причину покажет '
                                  f'ручной запуск: {" ".join(self.cmd)}')
            self.buf += chunk
        line, self.buf = self.buf.split(b'\n', 1)
        return line

    def _call(self, method, params):
        self.seq += 1
        self._send({'jsonrpc': '2.0', 'id': self.seq, 'method': method, 'params': params})
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                msg = json.loads(self._line(method, deadline))
            except ValueError:
                continue
            if not isinstance(msg, dict) or msg.get('id') != self.seq:
                continue
            if 'error' in msg:
                err = msg['error']
                raise SourceError(f'MCP {method}: {err.get("message", err) if isinstance(err, dict) else err}')
            return msg.get('result') or {}

    def search(self, jql, start):
        res = self._call('tools/call', {'name': 'jira_search', 'arguments': {
            'jql': jql, 'fields': FIELDS, 'expand': 'changelog', 'limit': PAGE, 'start_at': start}})
        text = ''.join(c.get('text', '') for c in res.get('content') or [] if c.get('type') == 'text')
        if res.get('isError'):
            raise SourceError(f'MCP jira_search: {text[:300]}')
        try:
            page = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SourceError(f'MCP jira_search вернул не JSON: {text[:200]}') from exc
        issues = page.get('issues') or []
        if issues and not self.jira_base:
            url = issues[0].get('browse_url') or ''
            self.jira_base = url.split('/browse/')[0] or None
        return page.get('total', 0), [from_mcp_issue(i) for i in issues]


def _mcp_sprints(self, board):
    out, start = [], 0
    while True:
        res = self._call('tools/call', {'name': 'jira_get_sprints_from_board', 'arguments': {
            'board_id': str(board), 'limit': PAGE, 'start_at': start}})
        text = ''.join(c.get('text', '') for c in res.get('content') or [] if c.get('type') == 'text')
        if res.get('isError'):
            raise SourceError(f'MCP jira_get_sprints_from_board: {text[:300]}')
        try:
            page = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SourceError(f'MCP jira_get_sprints_from_board вернул не JSON: {text[:200]}') from exc
        out += [{'id': str(sp.get('id')), 'name': sp.get('name'), 'state': sp.get('state'),
                 'start': sp.get('start_date'), 'end': sp.get('end_date')} for sp in page]
        start += len(page)
        if not page:
            return out


McpTransport.sprints = _mcp_sprints


class RestTransport:
    """GET-клиент JIRA: TLS всегда, токен в заголовке, replay для тестов."""

    name = 'rest'

    def __init__(self, base, token, ca_bundle=None, replay=None):
        self.base = (base or '').rstrip('/')
        self.jira_base = self.base or None
        self.token = token
        self.replay = Path(replay) if replay else None
        try:
            self.ctx = ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle else None)
        except OSError as exc:
            raise SourceError(f'не читается CA-бандл {ca_bundle}: {exc.strerror}') from exc

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @staticmethod
    def replay_key(path, params):
        canon = path + '?' + urllib.parse.urlencode(sorted(params.items()))
        return hashlib.sha1(canon.encode()).hexdigest()[:16], canon

    def get(self, path, **params):
        if self.replay:
            key, canon = self.replay_key(path, params)
            fixture = self.replay / f'{key}.json'
            if not fixture.is_file():
                raise SourceError(f'в replay нет ответа на GET {canon} (файл {fixture.name})')
            return json.loads(fixture.read_text(encoding='utf-8'))
        url = self.base + path + '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + self.token})
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise SourceError(f'JIRA не авторизует запрос (HTTP {exc.code}) — проверьте токен') from exc
            raise SourceError(f'JIRA вернула HTTP {exc.code} на {path}') from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise SourceError('сертификат JIRA не проверился — укажите корпоративный CA в '
                                  'jira.ca_bundle; проверку не отключаем') from exc
            raise SourceError(f'JIRA недоступна ({exc.reason}) — проверьте VPN и адрес') from exc

    def search(self, jql, start):
        page = self.get('/rest/api/2/search', jql=jql, fields=FIELDS, expand='changelog',
                        startAt=start, maxResults=PAGE)
        return page.get('total', 0), [from_rest_issue(i) for i in page.get('issues') or []]


    def sprints(self, board):
        out, start = [], 0
        while True:
            page = self.get(f'/rest/agile/1.0/board/{board}/sprint', startAt=start, maxResults=PAGE)
            values = page.get('values') or []
            out += [{'id': str(sp.get('id')), 'name': sp.get('name'), 'state': sp.get('state'),
                     'start': sp.get('startDate'), 'end': sp.get('endDate')} for sp in values]
            start += len(values)
            if page.get('isLast', True) or not values:
                return out


def board_jql(transport, board, date_from, date_to):
    """Задачи команды по умолчанию — спринты её доски, шедшие в периоде."""
    ids = []
    for sp in transport.sprints(board):
        if sp['state'] == 'future' or not sp.get('start'):
            continue
        start, end = sp['start'][:10], (sp.get('end') or '9999-12-31')[:10]
        if start <= date_to and (end >= date_from or sp['state'] == 'active'):
            ids.append(sp['id'])
    if not ids:
        raise SourceError(f'у доски {board} нет спринтов в периоде {date_from} – {date_to}: '
                          f'задайте params.blockers.jql')
    return f'sprint in ({", ".join(ids)})'


def fetch(transport, jql, date_from, date_to, team, now):
    """Все задачи периода постранично → снимок."""
    query = period_jql(jql, date_from, date_to)
    issues, start = [], 0
    while True:
        total, page = transport.search(query, start)
        issues.extend(page)
        start += len(page)
        if not page or start >= total:
            break
    seen = {}
    for it in issues:
        seen[it['key']] = it
    return {'version': 1, 'team': team, 'jql': query, 'fetchedAt': now, 'transport': transport.name,
            'jiraBase': getattr(transport, 'jira_base', None), 'issues': list(seen.values())}
