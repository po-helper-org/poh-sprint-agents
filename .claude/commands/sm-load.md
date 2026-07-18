---
description: "Стадия 3 — capacity с отпусками, SP до ёмкости, операционный контракт, риски. STOP."
---
# /sm-load {sprint}
Роль: Capacity Balancer. Вход: `sprint-stories.md`. Прочитай `.claude/domain-profile.md`, `resources/sprint_standards.md`, `resources/availability.md`, `resources/operational_contract.md`, `examples/ideal_operational_contract.md`.
Считай ёмкость = velocity×focus − отсутствия (**cold-start: sp_per_person_sprint + [УТОЧНИТЬ velocity]**). Добей SP каждого до ёмкости; пометь 🔴/🟡/🟢. Прогони риск-детекторы (`availability.md`) → карточки риска.
Построй `operational-contract-{sprint}.md` (участник→задачи→ожидаемые даты; коммиты текстом).
Выход: `{sprint_workspace}/sprint-load.md` + operational-contract. STOP.
