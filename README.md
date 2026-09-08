# poh-sprint-agents

Автономный скрам-мастер-агент.

- `sprint-planner` (slice 1): спринт → согласованный vault-ПЛАН + операционный контракт + гейт консенсуса.
- `sprint-result` (slice 2): закрытие спринта → `ФАКТ-{sprint}.md` + отчётная `.html`-страница для бизнеса. Правки собираются на самой странице.

## Установка
`bash install.sh [target-проект]` — копирует навык и команды (non-destructive), кладёт `domain-profile.md` из шаблона.

## Команды (STOP после каждой)
**Планирование:** `/sm-sync` → `/sm-goal` → `/sm-decompose` → `/sm-load` → `/sm-deliver` → `/sm-consensus`

**Отчёт:** `/sprint-result` → правки на странице → `/sr-revise` → `/sr-final`
(`/sr-html` — сервисная пересборка страницы)

Контур замкнут: незакрытые строки отчёта уходят кандидатами в carryover, `/sm-sync` следующего спринта читает их из того же файла.

## Документы
- Видение: `VISION.md`
- БФТ: `docs/bft-sprint-planner-slice1.md` · `docs/bft-sprint-result-slice1.md`
- Дизайн: `docs/superpowers/specs/2026-07-17-sprint-planner-slice1-design.md` · `docs/superpowers/specs/2026-09-08-sprint-result-html-design.md`
- Формат отчёта: `docs/reference/sprint-report-reference.md` (разбор референса, обезличено) · `docs/reference/sprint-report-page-mockup.html` (макет страницы)

## Проверки
```
python3 .claude/skills/sprint-result/scripts/check_report_structure.py ФАКТ-{sprint}.md
bash .claude/skills/sprint-result/scripts/test-sprint-report-html.sh
```
