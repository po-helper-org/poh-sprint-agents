# poh-sprint-agents

Автономный скрам-мастер-агент. Навык `sprint-planner` (slice 1): спринт → согласованный vault-ПЛАН + операционный контракт + гейт консенсуса.

## Установка
`bash install.sh [target-проект]` — копирует навык и команды (non-destructive), кладёт `domain-profile.md` из шаблона.

## Команды (STOP после каждой)
`/sm-sync` → `/sm-goal` → `/sm-decompose` → `/sm-load` → `/sm-deliver` → `/sm-consensus`

## Коннектор к корпоративной JIRA

`plugins/dsh-plugin-sprint` — раздел **«Управление спринтами»** для DeepSeek
Harness: встроенный коннектор к корпоративной JIRA вместо MCP-моста. Доступы и
промт подключения задаются в «Настройки → Плагины», подключение проверяется
кнопкой, а модель получает инструменты `jira_current_stories`, `jira_search`,
`jira_issue` и ходит в трекер напрямую. Только чтение: записи в JIRA нет.

`cd plugins/dsh-plugin-sprint && npm install && npm run build` — дальше
`link:`-зависимость в профиле харнесса, см.
[README раздела](plugins/dsh-plugin-sprint/README.md).

## Документы
- Видение: `VISION.md`
- БФТ: `docs/bft-sprint-planner-slice1.md`
- Дизайн: `docs/superpowers/specs/2026-07-17-sprint-planner-slice1-design.md`
- БФТ коннектора JIRA: `docs/bft-jira-connector.md`
- Демо коннектора (11 шагов): `docs/HOWTODEMO-jira.md`
