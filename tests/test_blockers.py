"""Блокаторы спринта: наложение runner'а «что стоит и сколько» (раздел «✋ Блокаторы» отчёта PO).

Блокатор — задача спринта, которая стоит:
  · «в ожидании» — статус в бакете blocked; стоит с последней смены статуса;
  · «без движения» — задача в работе/тесте/ревью, по которой 3+ рабочих дня
    ни смены статуса, ни комментария (у истории считается и движение её подзадач).
Дни — рабочие (пн–пт) от начала стоянки до дня сбора. Данные вымышленные.
"""
import unittest

import support  # noqa: F401  — пути runner и contract

import blockers as bl  # noqa: E402
import build as build_mod  # noqa: E402

NOW = '2026-09-18T10:00:00+03:00'   # пятница


def story(key, status, changed=None, assignee='Иванов Пётр Сергеевич', events=(), subtasks=(),
          category='В работе', title=None):
    return {'key': key, 'title': title or f'Задача {key}', 'status': status, 'category': category,
            'statusChanged': changed, 'assignee': assignee, 'priority': None,
            'events': list(events), 'subtasks': list(subtasks)}


def sub(key, status, changed=None, assignee='Петрова Анна', category='В работе'):
    return {'key': key, 'summary': f'Подзадача {key}', 'status': status, 'category': category,
            'statusChanged': changed, 'assignee': assignee, 'priority': None}


def team(*epics, status_map=None):
    return {'slug': 'team-a', 'team': 'Команда А', 'sprintName': 'S1', 'jiraBase': 'https://jira.example',
            'epics': list(epics), 'statusMap': status_map or {},
            '_meta': {'collectedAt': NOW}}


def epic(key, *stories, title=None):
    return {'rowId': key or 'no-epic', 'epicKey': key, 'epicTitle': title or (f'Инициатива {key}' if key else None),
            'stories': list(stories), 'scope': []}


def comment(key, at, by='Сидоров И.', body='жду ответа'):
    return {'at': at, 'kind': 'comment', 'key': key, 'by': by, 'body': body}


def status_ev(key, at, frm, to):
    return {'at': at, 'kind': 'status', 'key': key, 'by': 'Иванов П.', 'from': frm, 'to': to, 'done': False}


class WorkdaysTest(unittest.TestCase):
    def test_weekend_not_counted(self):
        # пт → пн = 1 рабочий день; пн → пн = 5
        self.assertEqual(bl.workdays('2026-09-11', '2026-09-14'), 1)
        self.assertEqual(bl.workdays('2026-09-14', '2026-09-21'), 5)
        self.assertEqual(bl.workdays('2026-09-18', '2026-09-18'), 0)


class BlockersTest(unittest.TestCase):
    def test_waiting_status_is_blocker_since_status_change(self):
        t = team(epic('E-1', story('A-1', 'В ожидании', changed='2026-09-04T12:00:00+03:00')))
        got = bl.team_blockers(t)
        self.assertEqual([(b['key'], b['why'], b['days']) for b in got['items']], [('A-1', 'wait', 10)])
        b = got['items'][0]
        self.assertEqual((b['kind'], b['epicKey'], b['epicTitle'], b['rowId']), ('story', 'E-1', 'Инициатива E-1', 'E-1'))
        self.assertEqual(b['assignee'], 'Иванов Пётр Сергеевич')
        self.assertEqual(b['since'], '2026-09-04')
        self.assertEqual(b['url'], 'https://jira.example/browse/A-1')

    def test_status_map_wins_over_rules(self):
        """Карта статусов команды (statusMap) решает, что такое blocked — как на странице."""
        t = team(epic('E-1', story('A-1', 'Нужна информация', changed='2026-09-10T12:00:00+03:00')),
                 status_map={'Нужна информация': 'blocked'})
        self.assertEqual([b['key'] for b in bl.team_blockers(t)['items']], ['A-1'])

    def test_stale_after_three_workdays_without_moves_or_comments(self):
        t = team(epic('E-1',
                      story('A-1', 'В работе', changed='2026-09-14T10:00:00+03:00'),            # 4 дня — стоит
                      story('A-2', 'В работе', changed='2026-09-16T10:00:00+03:00'),            # 2 дня — нет
                      story('A-3', 'Ревью', changed='2026-09-08T10:00:00+03:00',
                            events=[comment('A-3', '2026-09-17T09:00')]),                       # свежий комментарий — нет
                      story('A-4', 'Бэклог', changed='2026-08-01T10:00:00+03:00', category='К выполнению')))
        got = bl.team_blockers(t)['items']
        self.assertEqual([(b['key'], b['why'], b['days']) for b in got], [('A-1', 'stale', 4)])

    def test_story_moves_with_its_subtasks(self):
        """История «в работе» не стоит, пока движутся её подзадачи; подзадача — по своим событиям."""
        t = team(epic('E-1', story('A-1', 'В работе', changed='2026-09-01T10:00:00+03:00',
                                   events=[status_ev('A-2', '2026-09-17T11:00', 'Бэклог', 'В работе')],
                                   subtasks=[sub('A-2', 'В работе', changed='2026-09-17T11:00:00+03:00'),
                                             sub('A-3', 'Приостановлена', changed='2026-09-11T11:00:00+03:00')])))
        got = bl.team_blockers(t)['items']
        self.assertEqual([(b['key'], b['kind'], b['why'], b['days']) for b in got], [('A-3', 'subtask', 'wait', 5)])
        self.assertEqual(got[0]['title'], 'Подзадача A-3')
        self.assertEqual(got[0]['assignee'], 'Петрова Анна')

    def test_story_with_open_subtasks_is_not_counted_twice(self):
        """Стоят подзадачи — в списке они; история с открытыми подзадачами «без движения» не дублирует их дни."""
        t = team(epic('E-1', story('A-1', 'В работе', changed='2026-09-01T10:00:00+03:00',
                                   subtasks=[sub('A-2', 'В работе', changed='2026-09-08T11:00:00+03:00')])))
        got = bl.team_blockers(t)
        self.assertEqual([(b['key'], b['why']) for b in got['items']], [('A-2', 'stale')])
        self.assertEqual(got['byEpic'][0]['days'], 8)

    def test_story_stale_when_all_subtasks_done(self):
        t = team(epic('E-1', story('A-1', 'Ревью', changed='2026-09-01T10:00:00+03:00',
                                   subtasks=[sub('A-2', 'Готово', changed='2026-09-02T11:00:00+03:00', category='Выполнено')])))
        self.assertEqual([(b['key'], b['days']) for b in bl.team_blockers(t)['items']], [('A-1', 12)], 'движение — последнее у истории и её подзадач (02.09)')

    def test_done_never_blocks(self):
        t = team(epic('E-1', story('A-1', 'Закрыт', changed='2026-08-01T10:00:00+03:00', category='Выполнено')))
        self.assertEqual(bl.team_blockers(t)['items'], [])

    def test_sorted_longest_first_with_last_comment(self):
        t = team(epic('E-1',
                      story('A-1', 'В ожидании', changed='2026-09-16T10:00:00+03:00',
                            events=[comment('A-1', '2026-09-16T11:00', body='ждём доступ от ИБ')]),
                      story('A-2', 'В ожидании', changed='2026-08-28T10:00:00+03:00')))
        got = bl.team_blockers(t)['items']
        self.assertEqual([b['key'] for b in got], ['A-2', 'A-1'])
        self.assertEqual(got[1]['comment'], {'by': 'Сидоров И.', 'at': '2026-09-16T11:00', 'text': 'ждём доступ от ИБ'})
        self.assertIsNone(got[0]['comment'])

    def test_unknown_start_kept_without_days(self):
        t = team(epic('E-1', story('A-1', 'В ожидании', changed=None)))
        got = bl.team_blockers(t)['items']
        self.assertEqual([(b['key'], b['days']) for b in got], [('A-1', None)])

    def test_summary_by_initiative_and_person(self):
        t = team(epic('E-1', story('A-1', 'В ожидании', changed='2026-09-11T10:00:00+03:00'),                 # 5
                      story('A-2', 'В ожидании', changed='2026-09-15T10:00:00+03:00', assignee='Петрова Анна')),  # 3
                 epic(None, story('A-3', 'В ожидании', changed='2026-09-17T10:00:00+03:00', assignee=None)))  # 1
        got = bl.team_blockers(t)
        self.assertEqual(got['byEpic'], [
            {'key': 'E-1', 'title': 'Инициатива E-1', 'rowId': 'E-1', 'count': 2, 'days': 8},
            {'key': None, 'title': 'Без эпика', 'rowId': 'no-epic', 'count': 1, 'days': 1}])
        self.assertEqual(got['byPerson'], [
            {'name': 'Иванов Пётр Сергеевич', 'count': 1, 'days': 5},
            {'name': 'Петрова Анна', 'count': 1, 'days': 3},
            {'name': 'Не назначен', 'count': 1, 'days': 1}])
        self.assertEqual((got['asOf'], got['staleDays']), ('2026-09-18', 3))


class OverlayTest(unittest.TestCase):
    def test_attached_and_outside_digest(self):
        """Блокаторы — наложение runner'а: инсайды не «устаревают» от их пересчёта."""
        t = team(epic('E-1', story('A-1', 'В ожидании', changed='2026-09-04T12:00:00+03:00')))
        before = build_mod.team_digest(t)
        build_mod.attach_blockers([t])
        self.assertEqual([b['key'] for b in t['blockers']['items']], ['A-1'])
        self.assertEqual(build_mod.team_digest(t), before)

    def test_broken_team_does_not_break_page(self):
        """Чужой сборщик без событий и дат — пустой раздел, а не упавшая сборка."""
        t = {'slug': 'x', 'epics': [{'rowId': 'r', 'stories': [{'key': 'B-1', 'status': 'В ожидании'}]}],
             '_meta': {}}
        build_mod.attach_blockers([t])
        self.assertEqual(t['blockers']['items'][0]['key'], 'B-1')
        self.assertIsNone(t['blockers']['items'][0]['days'])


if __name__ == '__main__':
    unittest.main()
