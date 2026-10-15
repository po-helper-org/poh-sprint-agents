#!/usr/bin/env python3
"""Поддельный MCP-сервер Atlassian по stdio: отвечает на jira_search страницами.

Форма задачи повторяет то, что отдаёт mcp-atlassian 3.4 (поля «расплющены»,
changelogs / comments / issuelinks). Задачи и люди вымышленные. Аргументы
последнего вызова пишутся в файл из FAKE_MCP_LOG — тест проверяет JQL.
"""
import json
import os
import sys

PAGE_SIZE = 2


def issue(n, status, log=(), comments=(), links=(), parent=None):
    return {
        'id': str(1000 + n), 'key': f'DEMO-{n}', 'summary': f'Задача {n}',
        'browse_url': f'https://jira.demo-workspace.local/browse/DEMO-{n}',
        'status': {'name': status, 'category': 'В работе'}, 'issue_type': {'name': 'История'},
        'assignee': {'display_name': 'Участник А', 'name': 'a'},
        'created': '2026-06-01 10:00:00 MSK',
        'parent': {'key': parent} if parent else None,
        'changelogs': [{'created': at, 'author': {'display_name': 'Участник А'},
                        'items': [{'field': 'status', 'from_string': a, 'to_string': b}]}
                       for at, a, b in log],
        'comments': [{'created': at, 'author': {'display_name': 'Участник Б'}, 'body': body}
                     for at, body in comments],
        'issuelinks': list(links),
    }


ISSUES = [
    issue(1, 'В ожидании', log=[('2026-09-23T10:00:00.000000+03:00', 'In progress', 'On Hold')],
          comments=[('2026-09-23T10:01:00.000+0300', 'Ждём данные от партнёра')],
          links=[{'type': {'name': 'Blocks', 'inward': 'is blocked by', 'outward': 'blocks'},
                  'inward_issue': {'key': 'OTHER-7', 'fields': {'summary': 'Стенд партнёра',
                                                                'status': {'name': 'Открыто'}}}}]),
    issue(2, 'Закрыт', log=[('2026-07-01T10:00:00+03:00', 'Open', 'In progress'),
                            ('2026-07-20T10:00:00+03:00', 'In progress', 'Closed')]),
    issue(3, 'Закрыт', parent='DEMO-1'),
]


def reply(msg_id, result):
    line = json.dumps({'jsonrpc': '2.0', 'id': msg_id, 'result': result}, ensure_ascii=False) + '\n'
    if os.environ.get('FAKE_MCP_BATCH'):
        # как настоящий сервер: лог-нотификация и ответ одной записью в канал
        note = json.dumps({'jsonrpc': '2.0', 'method': 'notifications/message',
                           'params': {'level': 'info', 'data': 'ok'}}) + '\n'
        line = note + line
    sys.stdout.write(line)
    sys.stdout.flush()


for line in sys.stdin:
    msg = json.loads(line)
    if 'id' not in msg:
        continue
    if msg['method'] == 'initialize':
        reply(msg['id'], {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'fake-atlassian', 'version': '0'}})
    elif msg['method'] == 'tools/call':
        args = msg['params']['arguments']
        if os.environ.get('FAKE_MCP_LOG'):
            with open(os.environ['FAKE_MCP_LOG'], 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(args, ensure_ascii=False) + '\n')
        if os.environ.get('FAKE_MCP_FAIL'):
            reply(msg['id'], {'isError': True, 'content': [{'type': 'text', 'text': 'Unauthorized'}]})
            continue
        if msg['params']['name'] == 'jira_get_sprints_from_board':
            sprints = [{'id': '10', 'name': 'Спринт 1', 'state': 'closed',
                        'start_date': '2026-05-01T10:00:00.000+03:00', 'end_date': '2026-05-14T10:00:00.000+03:00'},
                       {'id': '11', 'name': 'Спринт 2', 'state': 'closed',
                        'start_date': '2026-06-25T10:00:00.000+03:00', 'end_date': '2026-07-08T10:00:00.000+03:00'},
                       {'id': '12', 'name': 'Спринт 3', 'state': 'active',
                        'start_date': '2026-10-08T10:00:00.000+03:00', 'end_date': '2026-10-21T10:00:00.000+03:00'},
                       {'id': '13', 'name': 'Спринт 4', 'state': 'future'}]
            start = args.get('start_at', 0)
            reply(msg['id'], {'content': [{'type': 'text', 'text': json.dumps(sprints[start:start + 3])}],
                              'isError': False})
            continue
        start = args.get('start_at', 0)
        page = {'total': len(ISSUES), 'start_at': start, 'max_results': args['limit'],
                'issues': ISSUES[start:start + PAGE_SIZE]}
        reply(msg['id'], {'content': [{'type': 'text', 'text': json.dumps(page, ensure_ascii=False)}],
                          'isError': False})
