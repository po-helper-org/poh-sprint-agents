---
description: "Отчёт по факту спринта: запустить runner → интерпретация ИИ (sprint-insights) → сводка → STOP. Данные собирают сборщики, не модель."
---
# /actual-sprint {команда?}

Роль: Sprint Reporter. Прочитай `.claude/skills/actual-sprint/SKILL.md` и следуй ему.

1. Сбор — одна команда:

```bash
python3 .claude/skills/actual-sprint/runner/run.py run --config sprint-report.config.toml
```

Если `{команда}` передана — добавь `--only <slug>`. Слаг берётся из конфига; команды не в конфиге не существует — не угадывай доску и не подставляй id.

2. Сбор прошёл — **сразу интерпретация ИИ**, в этой же генерации (иначе она потеряется): `python3 .claude/skills/sprint-insights/insights.py facts` (с `--team <slug>` при `--only`) → по `.claude/skills/sprint-insights/SKILL.md` запиши `reports/sprint-insights.json`, а поле `interpretation` каждой команды — **по отдельному промту** `.claude/skills/sprint-insights/prompts/interpretation.md` → `python3 .claude/skills/sprint-insights/insights.py apply`. Есть `✗` — поправь файл и повтори `apply`. Сбор упал — шаг пропускаешь.

3. Показать сводку runner (по каждой команде — доска, спринт, эпики, закрыто/всего, события, запросы, время; затем схема, инварианты, предупреждения, заметки), строку `apply` про интерпретацию и путь к файлу. **STOP.**

При ошибке сначала `run.py doctor` — он проверяет стенд без похода в JIRA. Таблица «сообщение → причина → действие» — `docs/actual-sprint-debug.md`.

Данные ты не собираешь. Ни MCP, ни прямых запросов к трекеру, ни чисел по памяти: при любой ошибке показываешь её и следующий шаг — `/collector-validate <slug>`, VPN, токен, `/sprint-setup`. Конфига нет → `/sprint-setup`.

Выход: `sprint-report.html` (путь задан в `output` конфига) — одна самодостаточная страница на все команды, переключатель вкладок в шапке. Не публиковать как Artifact без явной просьбы.
