---
description: "Инсайды ИИ по графикам отчёта: факты из снимка скриптом → агент пишет reports/sprint-insights.json → apply проверяет и встраивает в страницу → STOP."
---
# /sprint-insights {команда?}

Роль: аналитик спринта для PO и техлида. Прочитай `.claude/skills/sprint-insights/SKILL.md` и следуй ему.

1. `python3 .claude/skills/sprint-insights/insights.py facts` (с `--team <slug>`, если команда передана; слаг — из конфига, не угадывай).
2. По фактам запиши `reports/sprint-insights.json`: 1–3 инсайда на график, цифры и ключи задач — только из фактов, `dataHash` — как в фактах.
3. `python3 .claude/skills/sprint-insights/insights.py apply`. Есть `✗` — поправь файл и повтори. `⚠` про число — замени на число из фактов.
4. В чат — одна строка: для каких команд записаны инсайды и путь к странице. **STOP.**

Данные ты не собираешь и не пересчитываешь: ни MCP, ни запросов к трекеру, ни чисел по памяти.
