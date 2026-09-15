---
description: "Синк с JIRA — актуальное состояние спринта: HTML-страница + краткая таблица Команда/История/Что сделано/Что осталось. Read-only. STOP."
---
# /sprint-sync [{sprint}]
Роль: Sync Reporter. Прочитай `.claude/domain-profile.md` (секция `## jira`), `SKILL.md` навыка `sprint-sync`, `resources/jira_mapping.md`, `resources/report_format.md`.
Проверь доступ: `JIRA_TOKEN` (Server/DC) либо `JIRA_EMAIL` + `JIRA_API_TOKEN` (Cloud) и `jira.base_url`. Чего-то нет → назови недостающее и STOP: состояние спринта не выдумывается.
Выгрузи (только GET): `python3 .claude/skills/sprint-sync/scripts/sprint_sync.py --sprint {sprint}`. Ошибка 401/403/404 → покажи сообщение скрипта, не повторяй прогон вслепую.
Выведи в чат: строку прогресса, таблицу `Команда · История · Что сделано · Что осталось`, блок «Требует внимания», путь к HTML. Цифры — из вывода скрипта, без пересчёта.
Добавь 2–4 строки трактовки: где расхождение с ПЛАН-{sprint}, что под риском Sprint Goal. Каждое утверждение ← строка отчёта. STOP.
