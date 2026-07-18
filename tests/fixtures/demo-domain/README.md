# demo-domain — golden fixture (Ticketland)

Golden fixture для прогона `/sm-sync … /sm-consensus` (полный пайплайн sprint-planner) на **2026Q3-S7**.

## Cold-start

`domain-profile.md → sprint_fact_doc` указывает на `S6/ФАКТ-2026Q3-S6.md`, который **намеренно не существует** в этой фикстуре. Это моделирует cold-start сценарий: ФАКТ прошлого спринта отсутствует, velocity неизвестна → ёмкость должна резолвиться через fallback `capacity.sp_per_person_sprint = 8` (см. `sprint_standards.md`, раздел «Модель ёмкости»), а не выдумываться.

## Состав фикстуры

| Файл | Роль |
|------|------|
| `domain-profile.md` | профиль домена, все paths → эта директория |
| `team.md` | ростер (BE-1, BE-2, FE-1, SA-1) |
| `availability.md` | реестр отсутствий на 2026Q3 (отпуск SA-1 28–31 июля) |
| `SPRINT-ROADMAP-2026Q3.md` | матрица KR×спринт (OBJ2 KR2.1 — кино через UMC, OBJ3 KR3.1 — B2B через extapi_go), срез на S7 |

## Ожидаемый выход

Прогон пайплайна на S7 с этими входами должен дать план, приблизительно эквивалентный эталону `.claude/skills/sprint-planner/examples/ideal_sprint_plan.md`:
- цель по OBJ2/KR2.1: кино в `web_db` через UMC, отображается на витрине с фильтрацией (BE-2, FE-1, SA-1);
- цель по OBJ3/KR3.1: B2B pay/sell на 100% через `extapi_go` (BE-1);
- capacity по исполнителям посчитана через fallback (velocity недоступна из-за отсутствующего S6-ФАКТ), с учётом отпуска SA-1 в конце спринта;
- признак cold-start (нет ФАКТ) явно отражён в плане/логах прогона, а не замаскирован выдуманными цифрами.
