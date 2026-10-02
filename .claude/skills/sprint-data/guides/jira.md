# Сборщик для JIRA: как получить JSON команды

Руководство для автора сборщика. Готовая рабочая реализация всего, что здесь описано, — базовый сборщик `.claude/skills/actual-sprint/templates/python/collector.py` (Python 3.9+, только stdlib). Это и есть пример кода: каждая секция ниже ссылается на его функцию. Свой сборщик пишут, только когда правил в `params` не хватает (`/collector-new`), и пишут его, повторяя эти алгоритмы.

Что должно получиться — `reference/fields.md` (каждое поле, тип, откуда берётся, где показывается) и `actual-sprint/contract/team.schema.json` (форма, её проверяет runner). Как сборщик запускается — `actual-sprint/contract/PROTOCOL.md`.

## 0. Подключение

| Что | Как |
|---|---|
| Адрес | `jira.url` из запроса на stdin (runner берёт его из переменной окружения, имя — `jira.url_env` конфига). |
| Токен | только из переменной окружения (`JIRA_PERSONAL_TOKEN` или `token_env` конфига), заголовок `Authorization: Bearer <PAT>` — JIRA Server / Data Center. В stdout, stderr и record-дампы не попадает никогда. |
| TLS | проверка включена всегда; корпоративный CA — файлом из `jira.caBundle` (`ssl.create_default_context(cafile=…)`). |
| Методы | только GET. Ни одного запроса, меняющего трекер. |
| Время | «сейчас» — только `now` из запроса, не системные часы. |
| Ошибки | нет сети / 401 / 403 / сертификат — код выхода `3` и понятная причина; конфиг — `2`; прочее — `1`. |
| Запросы | пакетно: на спринт, на пачку эпиков, на пачку родителей. Никогда — на задачу. Счётчик — в `_meta.requests`. |
| Воспроизводимость | `--record <dir>` сохраняет сырые ответы, `--replay <dir>` работает из них без сети (класс `Jira` в базовом сборщике). На этом стоят тесты и сверка после правок. |

## 1. Справочники — по одному запросу

| Запрос | Зачем | Функция |
|---|---|---|
| `GET /rest/api/2/status` | карта «id статуса → категория» (`statusCategory.name`). В changelog имена статусов приходят на языке workflow (`Closed`), а `/status` отдаёт локализованные; сопоставлять только по **id** (`item.from` / `item.to`). | `status_categories` |
| `GET /rest/api/2/field` | id поля связи с эпиком («Ссылка на эпик» / «Epic Link») и поля Story Points («Story Points», «Story point estimate»). Id различается между инстансами — не угадывать; не нашли — `params.epic_link_field` / `params.sp_field`. | `epic_link_field`, `sp_field` |
| `GET /rest/agile/1.0/board/{id}` | имя доски для шапки. 404 — доски нет или токену не видно: код `2`. | `board_name` |

## 2. Спринты

`GET /rest/agile/1.0/board/{boardId}/sprint?state=closed,active` **с пагинацией** (`startAt`, `isLast`): у досок с длинной историей первая страница — самые старые спринты, активный в неё не попадает. Оставить `originBoardId == boardId` (в ответ попадают чужие спринты), отсортировать по `startDate`. Якорь — активный спринт (нет активного — последний закрытый); `params.sprints_back` (по умолчанию 3) спринтов отсчитываются **от него**. Нужны `name`, `startDate`, `endDate`, `completeDate`. → `collect`.

## 3. Задачи спринтов — два прохода на спринт

```
GET /rest/agile/1.0/sprint/{id}/issue
    ?fields=key,summary,status,issuetype,created,creator,assignee,subtasks,priority,<поле эпика>,<поле SP>
    &expand=changelog&maxResults=200&startAt=…
GET /rest/agile/1.0/sprint/{id}/issue?fields=key,summary,issuetype,created,creator,comment
```

Первый проход — поля и история изменений (changelog), второй — комментарии и автор создания: в ответе с `expand=changelog` комментариев нет. Список спринта включает подзадачи — их исполнитель, даты и история берутся отсюда же, без запроса на подзадачу. → `Jira.sprint_issues`.

Всё дальнейшее считается из этих ответов, плюс три пакетных поиска для эпиков.

## 4. Секции JSON: откуда и как

### `epics[]`, `stories[]`, `subtasks[]` → `build_epics`
- История — задача, чей `issuetype.name` входит в `params.story_types`. Задачи и баги в таблицу эпиков не идут, но идут в метрики и графики.
- Ключ эпика — из поля связи в полях истории. Названия, приоритеты и срок эпиков — **одним** поиском на пачку (`params.epic_batch`, 50): `GET /rest/api/2/search?jql=key in (A-1,A-2,…)&fields=summary,priority,duedate`. `duedate` → `epicDue`. Эпик не отдался (нет прав, удалён) — `epicTitle` = ключ и предупреждение, не `null`.
- Истории без эпика — в один псевдо-эпик `rowId: "no-epic"`, `epicKey: null`, `epicTitle: "Без эпика"`. Не выбрасывать.
- `status` — `status.name` как есть; `category` — категория по id статуса из справочника.
- `statusChanged` — самый поздний `histories[].created` среди записей с `field == "status"`; смен не было — `fields.created`. Не `fields.updated`: он двигается от любой правки.
- `assignee` — `assignee.displayName`, нет — `null`. `priority` — `priority.name`, нет — `null`.
- Подзадачи — из вложенного `fields.subtasks` (ключ, `summary`, статус); `statusChanged` и `assignee` — из той же задачи в списке спринта.

```python
def last_status_change(issue):
    last = None
    for h in issue.get('changelog', {}).get('histories', []):
        for it in h['items']:
            if it['field'] == 'status' and (last is None or h['created'] > last):
                last = h['created']
    return last or issue['fields']['created']
```

### `stories[].events` → `attach_story_events`
Вся жизнь истории и её подзадач, за всё время: `created` (из `fields.created` + `creator`), каждая смена статуса из changelog (`from`, `to`, `done` — новый статус в категории «закрыто»), каждый комментарий (из второго прохода, тело до 400 знаков). Сортировка по `at` по возрастанию.

### `epics[].scope` → `build_scope`, `scope_subtask_dates`
Весь объём эпика, не только спринт — для «Весь эпик» и сгорания эпика.
```
GET /rest/api/2/search?jql=cf[10101] in (A-1,A-2,…) ORDER BY Rank ASC
    &fields=summary,status,issuetype,assignee,priority,subtasks,created,resolutiondate,<поле эпика>,<поле SP>
    &startAt=…&maxResults=100
GET /rest/api/2/search?jql=parent in (A-5,A-9,…)&fields=status,created,resolutiondate
```
Подзадачи в первом поиске пропускаются (`issuetype.subtask`), их даты и исполнитель — вторым, по родителям (`fields=status,created,resolutiondate,assignee`): в заглушке подзадачи у задачи исполнителя нет. `sprint` — имя спринта отчёта, в котором задача была (из выгрузок п. 3), `inSprint` — она в активном. `doneAt` — `resolutiondate` только у задачи в бакете `done`. `sp` — число из поля SP или `null`. Предел — `params.epic_scope_max` (2000) с предупреждением.

### `metrics`, `velocity` → `build_metrics`, `lead_cycle`
По каждой задаче спринта (истории, задачи, баги, подзадачи) — проход по changelog по возрастанию:
```python
for h in sorted(histories, key=lambda x: x['created']):
    for it in h['items']:
        if it['field'] != 'status': continue
        cat = cats[str(it['to'])]
        if is_progress(cat) and start_at is None: start_at = h['created']   # начало Cycle
        if is_done(cat): done_at = h['created']                            # закрытие
        elif done_at is not None: done_at = None                           # переоткрыли
# закрыта, только если текущая категория — «закрыто» и done_at есть
lead  = done_at - fields.created
cycle = done_at - start_at   # нет start_at (сразу в закрыто) → cycle нет, не ноль
```
По спринту: `total`, `closed`, `open`, `throughputPct`, статистики `lead` / `cycle` / `leadStory` / `leadTask` (`{mean, median, count}`, пустая выборка — `null`), `points` — Lead Time каждой закрытой. `velocity.sprints[]`: `planned` — все задачи спринта, `done` — в бакете `done`, `split` — число по шести бакетам текущих статусов (сумма = `planned`).

### `burndown` → `build_burndown`
По дням активного спринта (`startDate`..`endDate`). Объём дня пересчитывается из changelog поля `Sprint`: `fromString` / `toString` содержат имена спринтов — так видно, когда задачу внесли и когда вынесли. `closed` — закрытые к концу дня (по `lead_cycle`), `remaining = scope − closed`, `weekend` — суббота и воскресенье, `future` — дата позже `now`.

### `control` → `build_control`
Две независимые выборки: истории (всё не-подзадачи) и подзадачи. Окно — с начала первого спринта отчёта (`params.control_days` задаёт его в днях явно): слайд «Сроки» показывает все спринты отчёта. `points[]` — закрытые в окне с `cycle` и `doneAt`, по возрастанию `doneAt`, дедуп по ключу; `mean`, `median`, `sd` (σ генеральной совокупности), `limit = mean + sd`, `outlier = cycle > limit`. `risks[]` — незакрытые, взятые в работу, у которых `elapsed = now − начало работы` больше медианы своей выборки.

### `output` → `build_output`, `value_at`, `status_history`, `status_intervals`
Выработка участников по спринтам отчёта, без подзадач. Для закрытого спринта статус и исполнитель — **на его конец** (`completeDate`, иначе `endDate`), восстановленные из changelog; для активного — текущие:
```python
def value_at(issue, field, moment):
    changes = sorted((h['created'], it) for h in histories for it in h['items'] if it['field'] == field)
    before = [it for at, it in changes if at <= moment]
    if before: return before[-1]['toString']
    return changes[0][1]['fromString'] if changes else None   # None → текущее значение
```
`split[bucket] = [задач, SP]`; `items[]` — задачи участника с историей статусов и до пяти комментариев **в границах спринта**; `lead[имя]` — медиана Lead Time его закрытых. `timeInStatus` — по всем задачам и подзадачам спринта: интервалы статусов из changelog (`status_intervals`), обрезанные границами спринта, среднее число дней на задачу, побывавшую в бакете, — для `blocked`, `progress`, `review`, `testing`. `start` / `end` — даты спринта.

### `logs` → `build_logs`
Окно — с начала активного спринта (`params.activity_days` задаёт его в днях явно). Смены статуса из changelog (`st:{history.id}:{key}`), комментарии и создание задач из второго прохода (`cm:{comment.id}`, `cr:{key}`) — дедуп по этим ключам, автор отсутствует → «Система», комментарий до 160 знаков. Сортировка по `at` по убыванию со вторичным ключом (ключ задачи, вид) — иначе одинаковые метки времени переставляются между запусками. `kinds` и `authors` — счётчики по тем же событиям.

### `statusMap`, `_meta`
`statusMap` — каждый встреченный статус → бакет по `contract/status_rules.json` и `params.status_buckets` (`contract/buckets.py`). Статус, ушедший в `progress` по умолчанию, — предупреждение. `_meta` дописывается в конце: `collector`, `version`, `protocol`, `collectedAt` = `now`, `requests`, `durationMs`, `warnings`.

## 5. Бюджет запросов

`3` справочника + страницы спринтов + `2 × sprints_back × ⌈задач спринта / 200⌉` + `⌈эпиков / 50⌉` (названия) + страницы объёма эпиков (`⌈задач эпиков / 100⌉` на пачку) + страницы подзадач объёма. Типичная команда — 15–40 запросов, 5–15 секунд. Таймаут runner — 300 с.

## 6. JIRA Cloud

Базовый сборщик написан под Server / Data Center. Для Cloud меняются три места (точки `# TEAM RULE:` своего сборщика):
- авторизация — `Basic base64(email:api_token)` вместо `Bearer`;
- эпик — поле `parent` у задач в team-managed проектах (вместо «Epic Link»), в JQL — `parent in (…)`;
- поиск — `GET /rest/api/3/search/jql` с `nextPageToken` вместо `startAt` у `/rest/api/2/search`; описание и комментарии в ADF (JSON), текст надо извлечь.

Agile API (`/rest/agile/1.0/...`) у Cloud тот же.

## 7. Ловушки

- **Без VPN** корпоративный хост резолвится в публичный адрес, запросы висят до таймаута. Отдать код `3` и «проверьте VPN/токен», а не молчать.
- **Проверку TLS не отключать.** По соединению идёт личный токен.
- **Категория статуса не заменяет бакет.** «Ожидает тестирование» — очередь, а не тесты. Правила — `contract/status_rules.json`, переопределения команды — `params.status_buckets`.
- **Переоткрытие** сбрасывает дату закрытия.
- **Детерминизм.** `json.dump(..., sort_keys=True)`, стабильный порядок массивов, время только из `now`: одинаковый вход — побайтово одинаковый stdout.
- **Поле SP** заполнено не у всех задач: без оценки — `0` в выработке (`output`) и `null` в объёме (`scope`), не выдумывать.
- **Окно данных = период спринта.** История и комментарии задач участника, лента — в границах спринта; хронология истории (`events`) — за всё время.
