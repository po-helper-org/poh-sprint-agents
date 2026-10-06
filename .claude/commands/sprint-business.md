---
description: "Бизнес-отчёт «ФАКТ | спринт» для комитета: данные из общего снимка (при необходимости — runner actual-sprint) → факты → агент пишет reports/sprint-business.json → business.py apply собирает reports/sprint-business.html → STOP."
---
# /sprint-business {команды?}

Роль: PO, готовящий отчёт о продвижении за спринт для управляющего комитета и бизнес-заказчиков. Прочитай `.claude/skills/sprint-business/SKILL.md` и следуй ему.

1. Данные: есть `reports/sprint-report.data.json` и свежие не просили — работай по нему. Иначе — `python3 .claude/skills/actual-sprint/runner/run.py run --config sprint-report.config.toml` (сборщики, не ты; `--only <slug>`, если команда передана).
2. `python3 .claude/skills/sprint-business/business.py facts` (с `--team <slug>`, если команда одна).
3. Запиши `reports/sprint-business.json`: цели OBJ и KR эпиков — только из OKR/roadmap PO (откуда — в `goalsSource`), Sprint Goal по KR; по строке-направлению (эпик, `no-epic` — вне эпиков) — итог спринта одним предложением, блокер и следующий шаг (`streams.*.done/blocker/next`); блокеры заблокированных историй (`rows.*.blocker`); планы в четыре колонки (`take`, `finish`, `maybe`, `escalate`); квартальные риски. Цифры и ключи задач — только из фактов, `dataHash` — как в фактах.
4. `python3 .claude/skills/sprint-business/business.py apply`. Есть `✗` — поправь файл и повтори.
5. В чат — одна строка: команды и путь к `reports/sprint-business.html`. **STOP.**

Данные ты не собираешь и не пересчитываешь: ни MCP, ни запросов к трекеру, ни чисел по памяти. Технический отчёт для техлидов — `/actual-sprint` (на странице — кнопка «Для техлидов»).
