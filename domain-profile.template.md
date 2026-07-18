# Domain Profile — poh-sprint-agents

> Копия → `.claude/domain-profile.md`, заполнить под проект. Пустое поле → дефолт + `[УТОЧНИТЬ]`.

## paths
planning_root:      GROUND/NEXUS/project-management
sprint_workspace:   GROUND/SPRINTS/{sprint}
sprint_output_doc:  GROUND/SPRINTS/{sprint}/ПЛАН-{sprint}.md
okr_output_doc:     GROUND/NEXUS/project-management/{quarter}/OKR.md
sprint_roadmap_doc: GROUND/SPRINTS/SPRINT-ROADMAP-{quarter}.md
sprint_fact_doc:    GROUND/SPRINTS/{prev_sprint}/ФАКТ-{prev_sprint}.md
kr_epic_map_doc:    GROUND/NEXUS/project-management/{quarter}/KR-EPIC-MAP.md

## team
# person-узлы: full_name · role_title · expertise_topics (источник ролей истории #138)
roster_source: GROUND/NEXUS/team

## capacity
focus_factor:         0.7
sp_per_person_sprint: 8      # cold-start fallback, если velocity из ФАКТ нет
# velocity резолвится из sprint_fact_doc прошлых 3–5 спринтов

## availability            # реестр отсутствий #84
registry: GROUND/SPRINTS/availability.md
updated:  [УТОЧНИТЬ дату актуализации]   # НФТ-SP-3: должна быть ≤ старта спринта

## meta
current_quarter: [УТОЧНИТЬ, напр. 2026Q3]
po_name:         [УТОЧНИТЬ]
sprint_weeks:    2
