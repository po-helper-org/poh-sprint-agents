# Расширение «Груминг» (params.groom, сборщик 1.12.0+)

Необязательное расширение объекта команды. Читает его только отчёт «Груминг»
([poh-sprint-report](https://github.com/po-helper-org/poh-sprint-report), `python -m sprint_report grooming`);
отчёт спринта и схема `team.schema.json` его не видят. Без `params.groom = true` сборщик не делает ни одного
лишнего запроса и ключа `groom` не отдаёт.

| Поле | Что |
|---|---|
| `groom.quarterField` | id поля «квартал исполнения» (`params.quarter_field` или по имени из `quarter_names`); `null` — не найдено, колонка квартала пустая |
| `groom.epics[]` | незакрытые эпики доски (`/rest/agile/1.0/board/{id}/epic?done=false`), которых нет среди `epics` спринта: `rowId`, `epicKey`, `epicTitle`, `epicPriority`, `epicDue`, `stories: []`, `scope[]` |
| `groom.cards{ключ эпика}` | карточка каждого незакрытого эпика (и спринтового, и вне спринта): `title`, `status`, `category`, `priority`, `assignee`, `due`, `quarter`, `labels[]`, `updated` |
| `epics[].scope[]`, `groom.epics[].scope[]` | к полям объёма эпика добавляются: `quarter` (текст значения поля), `labels[]`, `updated` (YYYY-MM-DD), `links[]` — `{type, key, status}`, где `type` — как Jira называет связь со стороны задачи («is blocked by», «blocks», «relates to») |

`params.groom_max` (3000) — потолок задач объёма эпиков за запуск; `params.epic_scope` при `groom` включается сам.
Стоимость: +1 запрос на пачку эпиков (карточки), +1–2 на 100 задач объёма вне спринта, +1 на страницу эпиков доски.

`groom` не попадает в HTML-страницы отчётов (`build.render` его вырезает) и не входит в дайджест данных команды
(`OVERLAY_FIELDS`): правки «Груминга» не делают инсайды «устаревшими», страница не тяжелеет. Читают его только
`sprint-report.data.json` и poh-sprint-report.
