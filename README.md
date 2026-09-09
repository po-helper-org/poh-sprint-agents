# poh-sprint-agents

Автономный скрам-мастер-агент.

- `sprint-planner` (slice 1): спринт → согласованный vault-ПЛАН + операционный контракт + гейт консенсуса.
- `sprint-result` (slice 2): закрытие спринта → `ФАКТ-{sprint}.md` + отчётная HTML-колода для бизнеса (команда → стрим → строки). Правки собираются на самой колоде.

## Установка

Два способа, не взаимоисключающие:

- **В проект под Claude Code:** `bash install.sh [target-проект]` — копирует навыки и команды (non-destructive), кладёт `domain-profile.md` из шаблона.
- **В DeepSeek Harness:** `bash dsh/install.sh --harness /путь/к/harness --workspace /путь/к/воркспейсу` — подключает навыки как skill-root, вызов из чата. Демо-сценарий: `dsh/README.md`.

## Команды (STOP после каждой)
**Планирование:** `/sm-sync` → `/sm-goal` → `/sm-decompose` → `/sm-load` → `/sm-deliver` → `/sm-consensus`

**Отчёт:** `/sprint-result` → правки на колоде → `/sr-revise` → `/sr-final`
(`/sr-html` — сервисная пересборка колоды)

Контур замкнут: незакрытые строки отчёта уходят кандидатами в carryover, `/sm-sync` следующего спринта читает их из того же файла.

## Документы
- Видение: `VISION.md`
- БФТ: `docs/bft-sprint-planner-slice1.md` · `docs/bft-sprint-result-slice1.md`
- Дизайн: `docs/superpowers/specs/2026-07-17-sprint-planner-slice1-design.md` · `docs/superpowers/specs/2026-09-08-sprint-result-html-design.md`
- Формат отчёта: `docs/reference/sprint-report-deck-reference.md` (эталонная колода, обезличено) · `docs/reference/sprint-report-reference.md` (разбор исходной `.pptx`)

## Проверки
```
python3 .claude/skills/sprint-result/scripts/check_report_structure.py   ФАКТ-{sprint}.md
python3 .claude/skills/sprint-result/scripts/sprint-report-style-lint.py ФАКТ-{sprint}.md
bash   .claude/skills/sprint-result/scripts/test-sprint-report-html.sh
bash   dsh/test-contract.sh
```
Оба валидатора прогоняются до сборки колоды и повторно до финализации.
