# Design — Навык sprint-planner (poh-sprint-agents, slice 1)

**Дата:** 2026-07-17 · **Статус:** на ревью · **БФТ:** `docs/bft-sprint-planner-slice1.md`

## 1. Цель

Навык `sprint-planner` автономного скрам-мастер-агента. Из OKR / SPRINT-ROADMAP /
ФАКТ прошлого спринта / People Graph / реестра отсутствий доводит спринт до
**согласованного vault-артефакта**: `ПЛАН-{sprint}.md` (приёмочно-готов) +
`operational-contract-{sprint}.md` + `consensus-{sprint}.md`. Всё под git,
обратимо. Материализация в трекер и презентация — за границей среза.

Реализует БФТ slice 1 целиком (5 БТ · 4 ПТ · 7 ФТ · 8 НФТ).

## 2. Архитектура — скаффолд репозитория

```
poh-sprint-agents/
  VISION.md · README.md · install.sh · domain-profile.template.md
  docs/
    bft-sprint-planner-slice1.md
    superpowers/specs/2026-07-17-sprint-planner-slice1-design.md
  .claude/
    commands/
      sm-sync.md  sm-goal.md  sm-decompose.md  sm-load.md  sm-deliver.md  sm-consensus.md
    skills/sprint-planner/
      SKILL.md
      resources/
        # порт из po-helper (standalone-копия)
        sprint_standards.md   hard_gates.md   sync_questions.md   writing_style.md
        # дельта slice 1
        decomposition_standard.md   story_roles.md   availability.md
        operational_contract.md     consensus_board.md
      examples/
        ideal_sprint_plan.md              # порт (эталон структуры)
        ideal_operational_contract.md     # дельта (новый эталон)
        ideal_consensus_log.md            # дельта
  tests/
    fixtures/demo-domain/                 # ростер, roadmap-срез, ФАКТ, availability
    check_plan_structure.py               # dev-time валидатор НФТ-SP-8 (8 блоков, колонки); опционален
```

Standalone: собственный `install.sh` + `domain-profile.template.md`, без
runtime-зависимости от po-helper. Порт = копия файлов, не сабмодуль.

## 3. Доменный профиль

`domain-profile.template.md` (резолв `{...}`-путей на стадиях):

- `paths`: `planning_root`, `sprint_workspace`, `sprint_output_doc`, `okr_output_doc`,
  `sprint_roadmap_doc`, `sprint_fact_doc`, `index_doc`, `kr_epic_map_doc`.
- `team` / `roster`: person-узлы (`full_name`, `role_title`, `expertise_topics`).
- `capacity`: `velocity` (из ФАКТ), `focus_factor` (дефолт 0.7), `sp_per_person_sprint`
  (**cold-start fallback**: на первом спринте нового репо ФАКТ нет → velocity ←
  `sp_per_person_sprint` + `[УТОЧНИТЬ velocity]`, не блокирует гейты).
- `availability`: реестр отсутствий (кто / окно / тип / гранулярность) — **дельта #84**.
- `meta.current_quarter`.

Поле пусто → дефолт + `[УТОЧНИТЬ]`. Профиль не отменяет требование источника на факт.

## 4. Пайплайн — 6 стадий (STOP каждая)

| # | Команда | Вход | Действие | Артефакт |
|---|---------|------|----------|----------|
| 0 | `/sm-sync` | roadmap-срез, ФАКТ (carryover+velocity), roster+capacity, availability-реестр | Ресинк-диалог Q1–Q7 (`sync_questions.md`) + отсутствия. Один вопрос за раз | `sprint-context.md` |
| 1 | `/sm-goal` | context | 1–3 Sprint Goal (образ результата), привязка OBJ/KR | `sprint-goal.md` |
| 2 | `/sm-decompose` | goal, KR | Истории ← KR / тег внепланового; `decomposition_standard`; роли истории (`story_roles`); DoR-чеклист (PLAN-уровень) | `sprint-stories.md` |
| 3 | `/sm-load` | stories, capacity, availability | Ёмкость = velocity×focus − отсутствия; SP до ёмкости; флаги 🔴/🟡/🟢; риск-карточки доступности; строит контракт | `sprint-load.md` + `operational-contract-{sprint}.md` |
| 4 | `/sm-deliver` | load | 8 гейтов + Светофор (`hard_gates`); сухой прогон; факт ← источник + обоснование расхождений; блок N+1 | `ПЛАН-{sprint}.md` (структура §3.1 БФТ) |
| 5 | `/sm-consensus` | ПЛАН | Board «как вижу»; правки команды (канал: PO ретранслирует на ревью, версионирование); **правки SP/состава/исполнителей → повторный прогон гейтов `/sm-deliver`**; гейт «все согласны»; фикс кто/дата | `consensus-{sprint}.md` + board |

Каждая команда на «Этапе 0» читает `domain-profile.md`, `SKILL.md`, `resources/*`.

## 5. Дельта-модули (дизайн)

- **`decomposition_standard.md`** (#70) — уровни `ИНИЦИАТИВА→ЭПИК→ИСТОРИЯ→ПОДЗАДАЧА`:
  размер, критерии «хорошей» истории/подзадачи, DoR/DoD. Дефолт встроен,
  переопределение доменным профилем.
- **`story_roles.md`** (#138) — 4 роли (руководитель / разработчик / тестировщик /
  релиз-менеджер) на уровне истории; автоподстановка из `team`-нексуса; фазовые
  теги `[SA]/[BE]/[FE]/[QA]/[REL]` — в подзадачах (образ действия).
- **`availability.md`** (#84) — формат реестра (кто/окно/тип); приватность (факт
  «недоступен», не причина); вычет из capacity; риск-детекторы: перегруз ·
  ключевой-в-отпуске-на-критичной · срок-в-окне-отсутствия · bus-factor →
  карточки риска для скрам-мастера.
- **`operational_contract.md`** (#68) — формат `operational-contract-{sprint}.md`:
  на исполнителя — задачи (ссылка на историю ПЛАНа) · ожидаемые даты · роль.
  Коммиты в slice 1 = **плановые ожидания текстом**, не git/dev-info сигнал (нет
  трекер-интеграции до след. среза). Разворачивает «👤 Персональный фокус».
- **`consensus_board.md`** (#83) — shareable markdown board: группы по историям,
  карточки подзадач `@исполнитель`/`SP`, легенда SP по исполнителю (перекличка с
  capacity); цикл правок (версии до консенсуса); гейт «все согласны» (кто/дата),
  STOP до фиксации.

## 6. Поток данных

```
OKR · SPRINT-ROADMAP · ФАКТ(N-1) · team · availability
        │
    /sm-sync → context ─ /sm-goal → goal ─ /sm-decompose → stories
        │
    /sm-load → load + operational-contract
        │
    /sm-deliver → ПЛАН (8 гейтов ✅) ─ /sm-consensus → consensus-log
        │
    (граница slice 1) → [след. срез: BUILD в JIRA / презентация]
```

Всё в vault под git; ноль записей в трекер до конца среза (НФТ-SP-2).

## 7. Гейты и корректность

- **Zero-hallucination:** каждый факт (SP/исполнитель/KR/дата/capacity) ← источник;
  нет → `[УТОЧНИТЬ у {кого}]` (БТ-SP-5, НФТ-SP-1).
- **8 hard gates + Светофор** в `/sm-deliver` (порт `hard_gates.md`): 🔴 при
  нарушении критичных 1–5 → назад на load/decompose.
- **DoR PLAN-уровня** (адаптация #96) — **вход** `/sm-decompose`, не дублирует гейты:
  образ результата (наличие) · критерий демо · валидный исполнитель. Гейт 5 на
  выходе `/sm-deliver` проверяет **качество** образа результата. JIRA-пункт (Epic
  Link) — за границей среза.
- **Гейт консенсуса** (#83): материализация только после «все согласны»; правки,
  меняющие SP/состав/исполнителей, ре-прогоняют 8 гейтов (стадия 5).

## 8. Тестирование / верификация

- **Golden fixture** (`tests/fixtures/demo-domain/`): ростер, roadmap-срез, ФАКТ,
  availability-реестр. Прогон пайплайна → сверка `ПЛАН` с эталоном.
- **`check_plan_structure.py`** — валидатор НФТ-SP-8: 8 блоков §3.1, фикс. колонки,
  0 `TBD`-исполнителей в Must, 0 фактов-сирот без KR/тега.
- **Гейт-тесты:** каждый из 8 гейтов ловит внесённое нарушение (перегруз, TBD в
  Must, история-сирота, пустой Sprint Goal, carryover не учтён).
- **Availability-тест:** отпуск в окне спринта → ёмкость снижена, риск-карточка эмитится.
- **Contract-тест:** 100% исполнителей имеют строку с ≥1 датой (НФТ-SP-7).

**Разделение рантайма и теста.** Сам навык = markdown-инструкции для агента, без
рантайм-кода. `check_plan_structure.py` — **dev-time тест-утилита** (CI/локально),
не часть навыка и не зависимость установки; проверяет выход агента на fixture.
Опционально: если Python нежелателен — заменяется ручным чек-листом структуры
(§3.1 БФТ). Основная проверка среза — прогон агента на fixture + сверка с эталоном.

## 9. Границы (вне slice 1)

Запись в JIRA (BUILD/activate, баг #47) · презентация Google Docs · Excalidraw
self-host · cron-пинги и прогноз исполнительности (#67) · аудио→транскрипт ·
фазы daily / факт / ретро. Отдельными срезами.

## 10. Открытые вопросы (дефолты приняты, см. БФТ §6)

Источник отсутствий = ручной реестр в профиле · board = markdown · роли на
истории + фазовые теги в подзадачах · стандарт декомпозиции встроенный дефолт.
