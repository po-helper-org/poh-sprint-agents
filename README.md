# poh-sprint-agents

Автономный скрам-мастер-агент.

- Навык `sprint-planner` (slice 1): спринт → согласованный vault-ПЛАН + операционный контракт + гейт консенсуса.
- Навык `sprint-sync`: актуальное состояние спринта из JIRA → HTML-страница + краткий отчёт таблицей.

## Установка
`bash install.sh [target-проект]` — копирует навыки и команды (non-destructive), кладёт `domain-profile.md` из шаблона.

## Планирование (STOP после каждой стадии)
`/sm-sync` → `/sm-goal` → `/sm-decompose` → `/sm-load` → `/sm-deliver` → `/sm-consensus`

## Синк с JIRA
`/sprint-sync [{sprint}]` — читает секцию `## jira` доменного профиля, выгружает активный спринт доски (или свой JQL) и отдаёт:

- `sprint-sync-{sprint}.html` — страница состояния: прогресс, «Требует внимания», карточки исполнителей, итоговая таблица;
- краткий отчёт текстом в чат и файлом: `Команда · История · Что сделано · Что осталось`.

Доступ — через окружение: `JIRA_TOKEN` (Server/DC) либо `JIRA_EMAIL` + `JIRA_API_TOKEN` (Cloud); корпоративный CA — `JIRA_CA_BUNDLE`. Только GET-запросы: навык ничего не пишет в трекер. Нет ключей или `base_url` → команда называет недостающее и останавливается, состояние спринта не выдумывается.

Прогон без агента:

```bash
python3 .claude/skills/sprint-sync/scripts/sprint_sync.py --sprint 2026Q3-S7
python3 .claude/skills/sprint-sync/scripts/sprint_sync.py --from-json tests/fixtures/jira-sample/sprint-2026Q3-S7.json --out-dir /tmp/sync   # офлайн-демо
```

## Тесты
`python3 -m pytest tests/ -q` — структурный валидатор ПЛАН и офлайн-тесты sprint-sync (сеть не нужна).

## Документы
- Видение: `VISION.md`
- БФТ: `docs/bft-sprint-planner-slice1.md`
- Дизайн планирования: `docs/superpowers/specs/2026-07-17-sprint-planner-slice1-design.md`
- Дизайн синка: `docs/superpowers/specs/2026-09-15-sprint-sync-design.md`
