# Сборщик для другой системы: YouTrack, GitLab, Azure DevOps, Linear, своя БД

Отчёты не знают про JIRA: они читают JSON команды по `actual-sprint/contract/team.schema.json`. Любой трекер, в котором есть спринты (итерации), задачи с историей статусов и исполнители, даёт тот же JSON — нужен свой сборщик по протоколу (`actual-sprint/contract/PROTOCOL.md`). Каждое поле, его тип, смысл и где его показывают — `reference/fields.md`.

## Правило остаётся тем же
JSON собирает **скрипт**, подключённый к системе-источнику: один и тот же вход (`now` + ответы системы) даёт один и тот же JSON. Модель данных не собирает и не правит.

MCP-сервер трекера (или любой другой инструмент агента) уместен, чтобы **разведать** систему и **сверить** результат: найти доску и поля, посмотреть, как называются статусы, проверить выборку из `run.py validate`. Отчётные данные через MCP не собираются: сводка, собранная моделью вызовами инструментов, невоспроизводима и непроверяема. Если до системы есть только MCP, сборщик ходит в тот же API, который оборачивает MCP-сервер (у большинства это REST с токеном), — скриптом.

## Соответствие понятий

| В контракте | JIRA | YouTrack | GitLab | Azure DevOps | Linear |
|---|---|---|---|---|---|
| доска (`boardId`) | agile-доска | agile board | группа / проект + итерации | team + area path | team |
| спринт | sprint | sprint | iteration | iteration | cycle |
| эпик (`epics[]`) | Epic | эпик / родительская задача | epic | Epic / Feature | project |
| история (`stories[]`) | Story | задача верхнего уровня | issue | User Story / PBI | issue |
| подзадача (`subtasks[]`) | Sub-task | подзадача | task в issue | Task | sub-issue |
| `status` / `category` | status / statusCategory | State / isResolved | label или state | State / StateCategory | state / type |
| история статусов | changelog | activities | resource state events | revisions | issue history |
| комментарии | comment | comments | notes | comments | comments |
| Story Points | поле SP | Story points | weight | Story Points / Effort | estimate |

`category` должна попадать в набор `contract/status_rules.json` (`categories`) или в `params.categories` команды; три смысла — «к выполнению», «в работе», «выполнено». Бакет (`open / blocked / progress / testing / review / done`) сборщик кладёт в `statusMap`, правила — `contract/buckets.py` или своя таблица.

## С чего начинать: обязательное ядро
Схема требует: `slug`, `team`, `boardId`, `boardName`, `boardUrl`, `jiraBase`, `sprintName`, `epics`, `metrics`, `burndown`, `control`, `velocity`, `logs`, `_meta`. Без них runner не соберёт страницу.

Ссылки на задачи страницы строят как `jiraBase + "/browse/" + key`. У другой системы адрес задачи устроен иначе — `jiraBase` должен указывать на адрес, где этот путь откроет задачу (например, внутренний редирект); иначе ссылки будут вести в никуда, а цифры останутся верными.

Необязательные секции добавляют экраны — `reference/render.md` говорит, какой экран от какого поля зависит, а `run.py check <файл>` печатает это покрытие по готовому JSON:
- `output` — команда в отчёте PO, операционный слайд, «Сроки» (время в статусах);
- `epics[].scope` + `epicDue` — «Весь эпик» и сгорание эпика;
- `stories[].events` — календарь и хронология истории в презентации;
- `stories[].assignee`, `statusChanged`, `subtasks[].assignee` — инициалы, возраст статуса, распределение по участникам.

## Порядок работы
1. Разведать систему: как получить спринты доски, задачи спринта с историей статусов и комментариями, поле оценки. Записать в `params` всё, что различается между командами.
2. Скопировать за основу базовый сборщик (`run.py new <slug>`) и заменить класс доступа и разбор ответов, сохранив построение секций, — или написать свой на любом языке по протоколу.
3. Включить запись ответов (`--record`) и прогонять по ним (`--replay`), пока `run.py validate <slug>` не даст схему ✓ и все инварианты.
4. `run.py check <выход.json>` — покрытие экранов: какие слайды останутся пустыми и каких полей для них нет.
5. Сверить выборку с системой (`/collector-validate`), подтвердить у PO и записать хеш (`run.py lock`).
