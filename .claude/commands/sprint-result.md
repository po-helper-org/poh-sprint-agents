---
description: "Отчёт по спринту для бизнеса: ресинк факта → ФАКТ-{sprint}.md + HTML-колода. Два STOP."
---
# /sprint-result {sprint}
Роль: Fact Collector → Report Builder. Прочитай `.claude/domain-profile.md`, `SKILL.md`, `resources/resync_questions.md`, `resources/readiness_ladder.md`, `resources/report_structure.md`, `resources/writing_register.md`, `resources/fact_gates.md`, `examples/ideal_sprint_report.md`.

**Стадия 0.** Подтяни `ПЛАН-{sprint}.md`, `operational-contract-{sprint}.md`, ФАКТ прошлого спринта (**нет ПЛАН → cold-start**, зафиксируй один раз в шапке). Проведи ресинк Ф1–Ф8 (`resync_questions.md`) **по одному вопросу за раз**. Не спрашивай процент — спрашивай состояние, процент выводи по лестнице и предлагай PO на подтверждение. Черновик → `{sprint_workspace}/sprint-fact-context.md`. STOP.

**Стадия 1.** Приведи контекст к структуре `report_structure.md`: команда → стрим → строки, затем изменения, демо, метрики, итоги. Текст — в регистре caveman ultra + anti-slop. Прогони 9 гейтов + Светофор: 🔴 (гейт 1–5) → назад на ресинк, запись блокируется; **гейт 5 блокирует всегда**.

Запиши `{sprint_report_doc}`, затем **до сборки колоды** прогони оба валидатора:
```
python3 .claude/skills/sprint-result/scripts/check_report_structure.py   {sprint_report_doc}
python3 .claude/skills/sprint-result/scripts/sprint-report-style-lint.py {sprint_report_doc}
```
Ненулевой код структурного — правь документ и повтори. Стилевой на этой стадии — 🟡: перечисли PO, что подсветил, и продолжай.

Собери колоду: `python3 .claude/skills/sprint-result/scripts/sprint-report-html.py {sprint_report_doc} --link-whitelist {publication.link_whitelist}`. Отдай PO путь к `.html` и скажи, что правки собираются на самой колоде. STOP.
