# Domain Profile — poh-sprint-agents

> Копия → `.claude/domain-profile.md`, заполнить под проект. Пустое поле → дефолт + `[УТОЧНИТЬ]`.

## paths
planning_root:      GROUND/NEXUS/project-management
sprint_workspace:   GROUND/SPRINTS/{sprint}
sprint_output_doc:  GROUND/SPRINTS/{sprint}/ПЛАН-{sprint}.md
okr_output_doc:     GROUND/NEXUS/project-management/{quarter}/OKR.md
sprint_roadmap_doc: GROUND/SPRINTS/SPRINT-ROADMAP-{quarter}.md
sprint_fact_doc:    GROUND/SPRINTS/{prev_sprint}/ФАКТ-{prev_sprint}.md   # читает sprint-planner
sprint_report_doc:  GROUND/SPRINTS/{sprint}/ФАКТ-{sprint}.md             # пишет sprint-result
sprint_report_page: GROUND/SPRINTS/{sprint}/ФАКТ-{sprint}.html
index_doc:          GROUND/NEXUS/project-management/{quarter}/INDEX.md
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

## publication            # чистота отчёта, гейт 5 навыка sprint-result
# Хосты, ссылки на которые допустимы в отчёте (через запятую). Пусто — любой
# внешний адрес остаётся в отчёте текстом, не ссылкой. Отчёт уходит наверх и
# живёт в переписке: внутренний адрес в нём — утечка, а не удобство.
link_whitelist:

## meta
current_quarter: [УТОЧНИТЬ, напр. 2026Q3]
po_name:         [УТОЧНИТЬ]
sprint_weeks:    2
