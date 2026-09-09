# Domain Profile — demo-domain («Витрина», golden fixture)

> Заполнено из `domain-profile.template.md` для golden fixture `tests/fixtures/demo-domain/`.
> Cold-start намеренно: `sprint_fact_doc` указывает на несуществующий S6 → ФАКТ отсутствует, ёмкость резолвится через `sp_per_person_sprint`-fallback.

## paths
planning_root:      tests/fixtures/demo-domain
sprint_workspace:   tests/fixtures/demo-domain/S7
sprint_output_doc:  tests/fixtures/demo-domain/S7/ПЛАН-2026Q3-S7.md
okr_output_doc:     tests/fixtures/demo-domain/OKR.md
sprint_roadmap_doc: tests/fixtures/demo-domain/SPRINT-ROADMAP-2026Q3.md
sprint_fact_doc:    tests/fixtures/demo-domain/S6/ФАКТ-2026Q3-S6.md   # не существует — cold-start, файл намеренно отсутствует
kr_epic_map_doc:    tests/fixtures/demo-domain/KR-EPIC-MAP.md

## team
# person-узлы: full_name · role_title · expertise_topics
roster_source: tests/fixtures/demo-domain/team.md

## capacity
focus_factor:         0.7
sp_per_person_sprint: 8      # cold-start fallback, если velocity из ФАКТ нет
# velocity резолвится из sprint_fact_doc прошлых 3–5 спринтов — здесь недоступна (S6 отсутствует)

## availability            # реестр отсутствий
registry: tests/fixtures/demo-domain/availability.md
updated:  2026-07-17

## meta
current_quarter: 2026Q3
po_name:         PO (demo)
sprint_weeks:    2
