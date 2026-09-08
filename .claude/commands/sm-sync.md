---
description: "Стадия 0 — ресинк контекста спринта + подтягивание отсутствий. Один вопрос за раз. STOP."
---
# /sm-sync {sprint}
Роль: Context Builder. Прочитай `.claude/domain-profile.md`, `SKILL.md`, `resources/sync_questions.md`, `resources/availability.md`.
Подтяни: срез SPRINT-ROADMAP, ФАКТ прошлого спринта (**нет ФАКТ → cold-start**), ростер+capacity, реестр отсутствий (`availability.registry`; проверь `updated` ≤ старта).
ФАКТ собран навыком `sprint-result` → carryover бери из блока «Перенос в {sprint} и следующие шаги» (поимённо, с процентом и причиной), риски — из `Причина:`/`Блокатор:` строк < 100% и блока «Изменения в процессе спринта». Контракт — `skills/sprint-result/resources/handoff.md`. **Velocity в ФАКТ нет** (SP не переносятся, решение Д3) → ёмкость по fallback `sp_per_person_sprint` + `[УТОЧНИТЬ velocity]`, см. открытый вопрос О9.
Проведи ресинк-диалог Q1–Q7 (`sync_questions.md`) **по одному вопросу за раз**. Отсутствия — из реестра, подтверди дельту у PO.
Выход: `{sprint_workspace}/sprint-context.md` (актуальные KR, ростер+ёмкости с отпусками, carryover, внеплановые, риски, открытые `[УТОЧНИТЬ]`). STOP.
