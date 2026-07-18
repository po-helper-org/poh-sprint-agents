---
description: "Стадия 0 — ресинк контекста спринта + подтягивание отсутствий. Один вопрос за раз. STOP."
---
# /sm-sync {sprint}
Роль: Context Builder. Прочитай `.claude/domain-profile.md`, `SKILL.md`, `resources/sync_questions.md`, `resources/availability.md`.
Подтяни: срез SPRINT-ROADMAP, ФАКТ прошлого спринта (carryover+velocity; **нет ФАКТ → cold-start**), ростер+capacity, реестр отсутствий (`availability.registry`; проверь `updated` ≤ старта).
Проведи ресинк-диалог Q1–Q7 (`sync_questions.md`) **по одному вопросу за раз**. Отсутствия — из реестра, подтверди дельту у PO.
Выход: `{sprint_workspace}/sprint-context.md` (актуальные KR, ростер+ёмкости с отпусками, carryover, внеплановые, риски, открытые `[УТОЧНИТЬ]`). STOP.
