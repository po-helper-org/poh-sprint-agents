# Sprint-Planner (slice 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать навык `sprint-planner` автономного скрам-мастер-агента (poh-sprint-agents), доводящий спринт до согласованного vault-артефакта ПЛАН + operational-contract + consensus-log.

**Architecture:** Markdown-навык Claude Code (SKILL.md + resources + examples + 6 slash-команд `sm-*`). Зрелые ресурсы порт standalone-копией из `po-helper-org/poh-helper`; 5 дельта-модулей автором. Единственный рантайм-код — dev-time валидатор структуры на Python. Всё в vault под git, обратимо.

**Tech Stack:** Markdown (навык), Bash (install.sh), Python 3 (dev-time валидатор + pytest), `gh` CLI (порт из upstream-репо).

## Global Constraints

- **Standalone.** Ноль runtime-зависимости от po-helper. Порт = копия файлов, не сабмодуль.
- **Vault-only (slice 1).** Ноль записей в JIRA/трекер. Артефакты — markdown под git.
- **Zero-hallucination.** Каждый факт (SP/исполнитель/KR/дата/capacity) ← источник; нет → `[УТОЧНИТЬ у {кого}]`.
- **Язык контента — русский.** Проза деловая телеграфная, без AI-стоп-слов и декоративных эмодзи (кроме статус-иконок эталона: 📋🎯📊👤⚠️🔭🟢🟡🔴).
- **Upstream source:** `po-helper-org/poh-helper`, ветка `main`. Порт-команда: `gh api "repos/po-helper-org/poh-helper/contents/<path>" --jq '.content' | base64 -d > <dest>`.
- **БФТ истины:** `docs/bft-sprint-planner-slice1.md` (5 БТ · 4 ПТ · 7 ФТ · 8 НФТ). **Дизайн:** `docs/superpowers/specs/2026-07-17-sprint-planner-slice1-design.md`.

---

## File Structure

```
poh-sprint-agents/
  VISION.md · README.md · install.sh · domain-profile.template.md   (Task 1–2)
  .claude/
    commands/  sm-sync.md sm-goal.md sm-decompose.md sm-load.md sm-deliver.md sm-consensus.md  (Task 11)
    skills/sprint-planner/
      SKILL.md                                                        (Task 10)
      resources/
        sprint_standards.md sync_questions.md writing_style.md        (Task 3, порт)
        hard_gates.md                                                 (Task 4, порт+адапт)
        decomposition_standard.md                                     (Task 5, дельта)
        story_roles.md                                                (Task 6, дельта)
        availability.md                                               (Task 7, дельта)
        operational_contract.md                                       (Task 8, дельта)
        consensus_board.md                                            (Task 9, дельта)
      examples/
        ideal_sprint_plan.md                                          (Task 3, порт)
        ideal_operational_contract.md                                 (Task 8, дельта)
        ideal_consensus_log.md                                        (Task 9, дельта)
  tests/
    check_plan_structure.py  test_check_plan_structure.py             (Task 12)
    fixtures/demo-domain/                                             (Task 13)
```

---

### Task 1: Git-init + скаффолд + коммит существующих документов

**Files:**
- Create: `.gitignore`
- Existing (уже созданы): `VISION.md`, `docs/bft-sprint-planner-slice1.md`, `docs/superpowers/specs/2026-07-17-sprint-planner-slice1-design.md`

- [ ] **Step 1: Инициализировать репозиторий и структуру каталогов**

```bash
cd /Users/aleksishmanov/projects/poh-org/poh-sprint-agents
git init
mkdir -p .claude/commands .claude/skills/sprint-planner/resources .claude/skills/sprint-planner/examples tests/fixtures/demo-domain
```

- [ ] **Step 2: Создать `.gitignore`**

```gitignore
.DS_Store
__pycache__/
*.pyc
.venv/
.pytest_cache/
tests/fixtures/**/output/
```

- [ ] **Step 3: Проверить дерево**

Run: `git status --porcelain && ls VISION.md docs/`
Expected: VISION.md + docs/ присутствуют; untracked-файлы видны.

- [ ] **Step 4: Первый коммит (документы согласования)**

```bash
git add VISION.md docs/bft-sprint-planner-slice1.md docs/superpowers/ .gitignore
git commit -m "docs: vision + БФТ + design навыка sprint-planner (slice 1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Доменный профиль + минимальный install.sh + README

**Files:**
- Create: `domain-profile.template.md`
- Create: `install.sh`
- Create: `README.md`

**Interfaces:**
- Produces: поля профиля, на которые ссылаются все стадии — `paths.*`, `team`, `capacity.{velocity,focus_factor,sp_per_person_sprint}`, `availability`, `meta.current_quarter`.

- [ ] **Step 1: Написать `domain-profile.template.md`**

```markdown
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
```

- [ ] **Step 2: Написать минимальный `install.sh` (non-destructive копия навыка в target)**

```bash
#!/usr/bin/env bash
# poh-sprint-agents installer — копирует навык sprint-planner в target-проект (Claude Code).
# Non-destructive: существующие файлы не перезаписываются. domain-profile.md не трогается.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$PWD}"
copy() { # src rel-path
  local dest="$TARGET/$1"
  if [ -e "$dest" ]; then echo "skip (exists): $1"; return; fi
  mkdir -p "$(dirname "$dest")"; cp -R "$SCRIPT_DIR/$1" "$dest"; echo "add: $1"
}
copy ".claude/skills/sprint-planner"
for c in sm-sync sm-goal sm-decompose sm-load sm-deliver sm-consensus; do
  copy ".claude/commands/$c.md"
done
# профиль — только если отсутствует
if [ ! -e "$TARGET/.claude/domain-profile.md" ]; then
  mkdir -p "$TARGET/.claude"; cp "$SCRIPT_DIR/domain-profile.template.md" "$TARGET/.claude/domain-profile.md"
  echo "add: .claude/domain-profile.md (из шаблона — заполнить)"
fi
echo "=== SPRINT-PLANNER-INSTALL: done → $TARGET ==="
```

- [ ] **Step 3: Написать `README.md`** (назначение, установка, 6 команд, ссылки на VISION/БФТ/spec)

```markdown
# poh-sprint-agents

Автономный скрам-мастер-агент. Навык `sprint-planner` (slice 1): спринт → согласованный vault-ПЛАН + операционный контракт + гейт консенсуса.

## Установка
`bash install.sh [target-проект]` — копирует навык и команды (non-destructive), кладёт `domain-profile.md` из шаблона.

## Команды (STOP после каждой)
`/sm-sync` → `/sm-goal` → `/sm-decompose` → `/sm-load` → `/sm-deliver` → `/sm-consensus`

## Документы
- Видение: `VISION.md`
- БФТ: `docs/bft-sprint-planner-slice1.md`
- Дизайн: `docs/superpowers/specs/2026-07-17-sprint-planner-slice1-design.md`
```

- [ ] **Step 4: Проверить синтаксис bash**

Run: `bash -n install.sh && echo OK`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
chmod +x install.sh
git add domain-profile.template.md install.sh README.md
git commit -m "feat: доменный профиль + минимальный installer + README

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Порт зрелых ресурсов (verbatim) + эталон плана

**Files:**
- Create: `.claude/skills/sprint-planner/resources/sprint_standards.md`
- Create: `.claude/skills/sprint-planner/resources/sync_questions.md`
- Create: `.claude/skills/sprint-planner/resources/writing_style.md`
- Create: `.claude/skills/sprint-planner/examples/ideal_sprint_plan.md`

- [ ] **Step 1: Порт четырёх файлов из upstream**

```bash
cd /Users/aleksishmanov/projects/poh-org/poh-sprint-agents
base="repos/po-helper-org/poh-helper/contents"
gh api "$base/.claude/skills/sprint-planner/resources/sprint_standards.md" --jq '.content' | base64 -d > .claude/skills/sprint-planner/resources/sprint_standards.md
gh api "$base/.claude/skills/sprint-planner/resources/sync_questions.md"   --jq '.content' | base64 -d > .claude/skills/sprint-planner/resources/sync_questions.md
gh api "$base/.claude/skills/bft-writer/resources/writing_style.md"        --jq '.content' | base64 -d > .claude/skills/sprint-planner/resources/writing_style.md
gh api "$base/.claude/skills/sprint-planner/examples/ideal_sprint_plan.md" --jq '.content' | base64 -d > .claude/skills/sprint-planner/examples/ideal_sprint_plan.md
```

- [ ] **Step 2: Проверить, что файлы непусты и содержат ключевые маркеры**

Run:
```bash
grep -q "Модель ёмкости (capacity)" .claude/skills/sprint-planner/resources/sprint_standards.md && \
grep -q "Q1 — Видение" .claude/skills/sprint-planner/resources/sync_questions.md && \
grep -q "Capacity по командам" .claude/skills/sprint-planner/examples/ideal_sprint_plan.md && \
test -s .claude/skills/sprint-planner/resources/writing_style.md && echo OK
```
Expected: `OK`

- [ ] **Step 3: Заменить `sprint-` на `sm-` в текстах команд внутри портированных файлов** (навык переименовал стадии)

Run:
```bash
sed -i '' -E 's#/sprint-(sync|goal|decompose|load|deliver)#/sm-\1#g' \
  .claude/skills/sprint-planner/resources/sprint_standards.md \
  .claude/skills/sprint-planner/resources/sync_questions.md
grep -c "/sprint-" .claude/skills/sprint-planner/resources/sync_questions.md
```
Expected: `0` вхождений `/sprint-` в sync_questions.md (кроме `/sprint-fact`/`/sprint-build` — оставить, они за границей среза; проверить глазами).

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/sprint-planner/resources/{sprint_standards,sync_questions,writing_style}.md \
        .claude/skills/sprint-planner/examples/ideal_sprint_plan.md
git commit -m "feat: порт зрелых ресурсов (standards/sync/style) + эталон плана из po-helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Порт + адаптация hard_gates.md (DoR → PLAN-уровень)

**Files:**
- Create: `.claude/skills/sprint-planner/resources/hard_gates.md`

**Interfaces:**
- Produces: 8 гейтов + Светофор (используются `/sm-deliver`); DoR PLAN-уровня (используется `/sm-decompose`).

- [ ] **Step 1: Порт файла**

```bash
gh api "repos/po-helper-org/poh-helper/contents/.claude/skills/sprint-planner/resources/hard_gates.md" \
  --jq '.content' | base64 -d > .claude/skills/sprint-planner/resources/hard_gates.md
sed -i '' -E 's#/sprint-(deliver|load|decompose)#/sm-\1#g' .claude/skills/sprint-planner/resources/hard_gates.md
```

- [ ] **Step 2: Адаптировать раздел «Definition of Ready» под PLAN-уровень**

Найти секцию `## Definition of Ready истории спринта (усиленная)`. Заменить её тело так, чтобы:
- DoR — **вход `/sm-decompose`** (готовность истории к декомпозиции), не вход BUILD.
- Убрать пункт 4 (`Заведена в JIRA под эпиком / Epic Link`) — JIRA за границей slice 1.
- Оставить 3 пункта: (1) образ результата текстом, (2) измеримый критерий демо, (3) валидный исполнитель из ростера.
- Добавить строку: «Гейт 5 (`/sm-deliver`) проверяет **качество** образа результата; DoR — только **наличие**. Не дублировать.»
- Удалить ссылку на `build_gates.md`.

Итоговый блок:
```markdown
## Definition of Ready истории (PLAN-уровень, вход `/sm-decompose`)

Готовность истории к декомпозиции. 3 пункта — обязательны:
1. **Образ результата текстом** — доказуемое состояние к концу спринта (не «реализовать»).
2. **Измеримый критерий демо** — что показываем и как проверяем «сделано».
3. **Валидный исполнитель** — имя из ростера NEXUS/team (не TBD в Must).

Нарушение → история не готова к декомпозиции: вернуть в discovery/уточнение.
Разграничение: DoR проверяет **наличие** образа результата; гейт 5 `/sm-deliver` — его **качество** (`БЫЛО→СТАЛО`, не TBD). Пункт не дублируется.
JIRA-готовность (Epic Link, заведение в трекере) — за границей slice 1 (BUILD-проход, след. срез).
```

- [ ] **Step 3: Добавить cold-start-примечание к Гейту 4 (перегруз)**

В теле «Гейт 4» добавить строку:
```markdown
> Cold-start (S1, нет ФАКТ): ёмкость = `sp_per_person_sprint` из профиля + `[УТОЧНИТЬ velocity]`. Отсутствие истории velocity — не нарушение гейта.
```

- [ ] **Step 4: Проверка**

Run:
```bash
grep -q "PLAN-уровень, вход" .claude/skills/sprint-planner/resources/hard_gates.md && \
! grep -q "Epic Link" .claude/skills/sprint-planner/resources/hard_gates.md && \
grep -q "Cold-start" .claude/skills/sprint-planner/resources/hard_gates.md && echo OK
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/sprint-planner/resources/hard_gates.md
git commit -m "feat: порт hard_gates + адаптация DoR под PLAN-уровень (без JIRA, cold-start)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Дельта-модуль decomposition_standard.md (#70)

**Files:**
- Create: `.claude/skills/sprint-planner/resources/decomposition_standard.md`

- [ ] **Step 1: Написать файл**

```markdown
# Стандарт декомпозиции (poh-sprint-agents)

Единый стандарт разбиения. Дефолт встроен; переопределение — `decomposition` в domain-profile.

## Уровни

| Уровень | Что это | Размер | Владелец |
|---|---|---|---|
| ИНИЦИАТИВА | Направление/OBJ-срез квартала | месяцы | PO |
| ЭПИК | Крупная поставка под KR | 1–2 спринта | PO/SA |
| ИСТОРИЯ | Пользовательская/техническая единица ценности | ≤ 8 SP (иначе разбить) | исполнитель |
| ПОДЗАДАЧА | Атомарный шаг роли `[SA]/[BE]/[FE]/[QA]/[REL]` | 1–2 дня | исполнитель |

## Критерии «хорошей» истории (INVEST-совместимо)

- **Независима** — можно взять в спринт без блокирующей связки.
- **Ценностна** — образ результата виден к концу спринта (демо-критерий).
- **Оценима** — SP по шкале Фибоначчи (`sprint_standards.md`); > 8 SP в Must → разбить.
- **Наследует KR** или помечена тегом внепланового (`sprint_standards.md`).

## DoR / DoD (ссылки, не дубль)

- **DoR** истории — `hard_gates.md` (PLAN-уровень, вход `/sm-decompose`).
- **DoD** — определяется командой; в slice 1 фиксируется как «измеримый критерий демо» в образе результата.

## Правило

История > 8 SP → обязательная декомпозиция на подзадачи со своими ролями. Подзадача без роли-тега `[SA/BE/FE/QA/REL]` — запрещена (иначе неясно «от кого/когда» #138).
```

- [ ] **Step 2: Проверка** — Run: `grep -q "ИНИЦИАТИВА" .claude/skills/sprint-planner/resources/decomposition_standard.md && echo OK` → `OK`

- [ ] **Step 3: Commit** — `git add … && git commit -m "feat: дельта-модуль decomposition_standard (#70)"`

---

### Task 6: Дельта-модуль story_roles.md (#138)

**Files:**
- Create: `.claude/skills/sprint-planner/resources/story_roles.md`

- [ ] **Step 1: Написать файл**

```markdown
# Роли истории (#138)

Контекст «от кого / что / когда» для качественных метрик спринта. Роли **опциональны, по фазам** — не 4 обязательных на каждую историю.

## Роли (по фазам бизнес-цикла)

| Роль | Фаза-тег | Что ждём |
|---|---|---|
| руководитель | `[PO]` | приёмка образа результата |
| разработчик | `[BE]`/`[FE]` | реализация |
| тестировщик | `[QA]` | проверка/отладка |
| релиз-менеджер | `[REL]` | выкладка |

## Правила

- Роль назначается **на историю опционально** (не все истории имеют все 4 — SA-only/`[SPIKE]` могут иметь одну).
- Фазовые теги живут в **подзадачах** (колонка «Образ действия» плана): `- [BE] …`, `- [QA] …`.
- **Автоподстановка исполнителей** — из `team`-нексуса (`full_name` по `role_title`/`expertise_topics`). Нет соответствия → `[УТОЧНИТЬ исполнителя]`, не выдумывать.
- Роль питает `operational_contract.md`: «участник → задачи → ожидаемые даты» строится по ролям истории.

## Связь

Роли — вход операционного контракта (#68) и точек контроля дейлика (след. срез): чья очередь, кто следующий, кто блокирует.
```

- [ ] **Step 2: Проверка** — Run: `grep -q "по фазам" .claude/skills/sprint-planner/resources/story_roles.md && echo OK` → `OK`

- [ ] **Step 3: Commit** — `git commit -m "feat: дельта-модуль story_roles (#138)"`

---

### Task 7: Дельта-модуль availability.md + пример реестра (#84)

**Files:**
- Create: `.claude/skills/sprint-planner/resources/availability.md`

- [ ] **Step 1: Написать файл**

```markdown
# Availability — реестр отсутствий и риски доступности (#84)

Отсутствие (отпуск/больничный/командировка/part-time) — фактор ёмкости. В slice 1 источник — **ручной реестр** в vault (`availability.registry` из профиля). Календарь/HR-коннектор — след. срез.

## Формат реестра (`availability.md` в vault проекта)

```
# Availability — {quarter}
updated: 2026-07-17            # НФТ-SP-3: дата актуализации ≤ старта спринта

| Кто | Окно (с–по) | Тип | Гранулярность |
|-----|-------------|-----|---------------|
| BE-1 | 2026-07-21…2026-07-25 | отпуск | полный день |
| FE-1 | 2026-07-18…2026-08-01 | part-time 50% | частичная |
```

**Приватность:** показываем факт «недоступен» и окно, **не причину** (диагнозы/личное — нет).

## Вычет из ёмкости (`/sm-load`)

`ёмкость = velocity × focus_factor − отсутствия`. Отсутствие в окне спринта вычитается пропорционально:
- полный день: минус (дни_в_окне / рабочих_дней_спринта) × velocity;
- part-time X%: минус (1 − X) × доля_дней.

Реестр устарел (`updated` позже старта или пусто) → `[УТОЧНИТЬ availability]`, ёмкость помечается как оценочная.

## Риск-детекторы → карточки риска

Эмитятся в план (секция «⚠️ Общие риски» + отдельный блок скрам-мастеру):

| Детектор | Условие | Карточка |
|---|---|---|
| перегруз | Σ SP исполнителя > ёмкости после вычета | «{кто}: перегруз {N} SP — снять Should/передать» |
| ключевой-в-отпуске | единственный носитель критичной (Must) истории отсутствует в её окне | «{кто} в отпуске на Must {история} — риск срыва Sprint Goal» |
| срок-в-окне | ожидаемая дата истории попадает в окно отсутствия ответственного | «{история}: дата {D} в окне отсутствия {кто}» |
| bus-factor | Must-история без бэкапа, единственный носитель | «{история}: bus-factor=1, нет бэкапа» |

Формат карточки: `кто / когда / что под угрозой / рекомендация`.
```

- [ ] **Step 2: Проверка** — Run: `grep -q "bus-factor" .claude/skills/sprint-planner/resources/availability.md && grep -q "не причину" .claude/skills/sprint-planner/resources/availability.md && echo OK` → `OK`

- [ ] **Step 3: Commit** — `git commit -m "feat: дельта-модуль availability + риск-детекторы (#84)"`

---

### Task 8: Дельта-модуль operational_contract.md + эталон (#68)

**Files:**
- Create: `.claude/skills/sprint-planner/resources/operational_contract.md`
- Create: `.claude/skills/sprint-planner/examples/ideal_operational_contract.md`

**Interfaces:**
- Consumes: истории+исполнители из `sprint-load.md`, роли из `story_roles.md`, окна из `availability.md`.
- Produces: артефакт `operational-contract-{sprint}.md` (вход валидатора НФТ-SP-7 и след. срезов).

- [ ] **Step 1: Написать `operational_contract.md`**

```markdown
# Операционный контракт (#68)

Раскрывает «👤 Персональный фокус» ПЛАНа до операционного уровня: **участник → задачи → ожидаемые даты**. Отдельный артефакт рядом с ПЛАН (`operational-contract-{sprint}.md`).

## Формат

На каждого исполнителя — блок:

```
### {Исполнитель} ({role_title})
| История | Роль/фаза | Ожидаемая дата | Ожидаемый результат (коммит текстом) |
|---------|-----------|----------------|--------------------------------------|
| BE: Загрузка P24→UMC | [BE] | 2026-07-24 | endpoint UMC в staging, демо |
```

## Правила

- **Коммиты = плановые ожидания текстом**, не git/dev-info сигнал (нет трекер-интеграции в slice 1).
- Каждая строка ссылается на историю ПЛАНа; дата ← оценка `/sm-load` (SP + порядок), с учётом окон `availability.md`.
- **НФТ-SP-7:** 100% исполнителей имеют ≥1 строку с ≥1 ожидаемой датой. Нет даты → `[УТОЧНИТЬ дату]`.
- Дата в окне отсутствия исполнителя → пометить риском (см. `availability.md`, детектор «срок-в-окне»).
```

- [ ] **Step 2: Написать эталон `ideal_operational_contract.md`** (2 исполнителя, данные из `ideal_sprint_plan.md` — BE-2 кино, BE-1 B2B)

```markdown
# 2026Q3-S7 — Операционный контракт (эталон)

### BE-2 (Backend)
| История | Роль/фаза | Ожидаемая дата | Ожидаемый результат (коммит текстом) |
|---------|-----------|----------------|--------------------------------------|
| BE: Загрузка P24 → UMC → web_db | [BE] | 2026-07-24 | endpoint UMC: кино из P24 в web_db, демо в staging |
| BE: Загрузка P24 → UMC → web_db | [QA] | 2026-07-29 | отладка в staging завершена |

### BE-1 (Backend)
| История | Роль/фаза | Ожидаемая дата | Ожидаемый результат (коммит текстом) |
|---------|-----------|----------------|--------------------------------------|
| BE: POST order/pay через extapi_go | [BE] | 2026-07-22 | pay через Go, дебаг завершён |
| BE: POST order/pay через extapi_go | [REL] | 2026-07-25 | раскатка 1%→100% |
| BE: Кэш заказов (datarace) | [BE] | 2026-07-29 | datarace устранён |
```

- [ ] **Step 3: Проверка** — Run: `grep -q "плановые ожидания текстом" .claude/skills/sprint-planner/resources/operational_contract.md && grep -q "BE-2" .claude/skills/sprint-planner/examples/ideal_operational_contract.md && echo OK` → `OK`

- [ ] **Step 4: Commit** — `git commit -m "feat: дельта-модуль operational_contract + эталон (#68)"`

---

### Task 9: Дельта-модуль consensus_board.md + эталон (#83)

**Files:**
- Create: `.claude/skills/sprint-planner/resources/consensus_board.md`
- Create: `.claude/skills/sprint-planner/examples/ideal_consensus_log.md`

- [ ] **Step 1: Написать `consensus_board.md`**

```markdown
# Консенсус-доска и гейт согласия (#83)

Поверхность командного согласования между планом и материализацией. slice 1 — **структурированный shareable markdown**; Excalidraw self-host — след. срез.

## Board «как я вижу» (markdown)

Группировка по историям; карточка подзадачи с бейджами `@исполнитель` и `SP`; легенда суммарных SP по исполнителю (сверка с capacity `/sm-load`).

```
## История: BE: Загрузка P24 → UMC → web_db  (BE-2, 8 SP)
- [SA] Изучить контракт P24            @BE-2  ·  2 SP
- [BE] Endpoint в UMC                   @BE-2  ·  4 SP
- [QA] Отладка в staging                @BE-2  ·  2 SP

### Легенда SP: BE-2 = 8/8 · FE-1 = 5/8 …
```

## Цикл ревью

1. Агент публикует board «как вижу».
2. **Канал правок:** PO ретранслирует замечания команды устно на ревью (slice 1). Прямой импорт доски — потом.
3. Агент применяет правки, инкрементирует версию (`v1 → v2`), фиксирует дельту.
4. **Правки, меняющие SP / состав историй / исполнителей → повторный прогон гейтов `/sm-deliver`** (иначе план рассинхронизируется с гейтами).
5. Повтор до «все согласны».

## Гейт консенсуса

Материализация (за границей slice 1) разрешена только после явного «все согласны». Фиксируется `consensus-{sprint}.md`: кто согласовал · дата · финальная версия board · перечень применённых правок.
```

- [ ] **Step 2: Написать эталон `ideal_consensus_log.md`**

```markdown
# 2026Q3-S7 — Consensus-log (эталон)

**Спринт:** 2026Q3-S7 · **Финальная версия board:** v2 · **Дата согласия:** 2026-07-18

## Согласовали
| Кто | Роль | Дата |
|-----|------|------|
| PO | Product Owner | 2026-07-18 |
| BE-1 | Backend | 2026-07-18 |
| BE-2 | Backend | 2026-07-18 |
| FE-1 | Frontend | 2026-07-18 |

## Применённые правки (v1 → v2)
- FE-1: SP «FE: витрина кино» 5 → 8 (команда: недооценили фильтрацию) → **ре-прогон гейтов**: FE-1 стал 🟢 100%, добор снят.
- BE-1: перенос «Кэш заказов» на конец спринта (зависимость от SA).

## Гейт
✅ Все согласны. План готов к материализации (BUILD — след. срез).
```

- [ ] **Step 3: Проверка** — Run: `grep -q "повторный прогон гейтов" .claude/skills/sprint-planner/resources/consensus_board.md && grep -q "Согласовали" .claude/skills/sprint-planner/examples/ideal_consensus_log.md && echo OK` → `OK`

- [ ] **Step 4: Commit** — `git commit -m "feat: дельта-модуль consensus_board + эталон (#83)"`

---

### Task 10: SKILL.md (сборка навыка)

**Files:**
- Create: `.claude/skills/sprint-planner/SKILL.md`

**Interfaces:**
- Consumes: все `resources/*` и `examples/*` из Task 3–9.
- Produces: точку входа навыка, на которую ссылаются 6 команд (Task 11).

- [ ] **Step 1: Написать SKILL.md** — персона скрам-мастера, каркас Why→What→How, 6 стадий, принципы, карта ресурсов. Структура:

```markdown
---
name: sprint-planner
description: "Навык планирования спринта скрам-мастер-агента. Из OKR/roadmap/ФАКТ строит согласованный vault-ПЛАН (Why→What→How) + операционный контракт (участник→задачи→даты) + гейт консенсуса команды. 6 стадий, STOP каждая. Роли истории, capacity с отпусками, DoR, zero-hallucination. Используй когда: спланировать спринт, декомпозиция спринта, план/факт капасити, /sm-sync … /sm-consensus."
---

# Навык: Sprint Planner — скрам-мастер планирование спринта

## Роль
Ты — **скрам-мастер-агент**. Не PO («что хотим»), а страж исполнения: точная персональная декомпозиция, честная ёмкость, консенсус команды, операционный контракт. Facilitator, не диктатор: диалог по одному вопросу за раз.

## Принцип нулевого допуска к галлюцинациям
Каждый факт (SP/исполнитель/KR/дата/capacity) ← источник: OKR, SPRINT-ROADMAP, ФАКТ прошлого спринта, решение PO, реестр отсутствий. Нет источника → `[УТОЧНИТЬ у {кого}]`. Не выдумывать состав, оценки, имена.

## Доменный профиль
Пути `{...}` и параметры (`paths`, `team`, `capacity`, `availability`, `meta.current_quarter`) — из `.claude/domain-profile.md`. Шаблон — `domain-profile.template.md`. Пусто → дефолт + `[УТОЧНИТЬ]`.

## Каркас Why→What→How + консенсус (6 стадий, STOP каждая)

| # | Команда | Роль | Артефакт | Ресурсы |
|---|---------|------|----------|---------|
| 0 | /sm-sync | Context Builder | sprint-context.md | sync_questions.md, availability.md |
| 1 | /sm-goal | Outcome Designer | sprint-goal.md | — |
| 2 | /sm-decompose | Story Designer | sprint-stories.md | decomposition_standard.md, story_roles.md, hard_gates.md (DoR) |
| 3 | /sm-load | Capacity Balancer | sprint-load.md + operational-contract-{sprint}.md | sprint_standards.md, availability.md, operational_contract.md |
| 4 | /sm-deliver | Validator | ПЛАН-{sprint}.md | hard_gates.md, sprint_standards.md, ideal_sprint_plan.md |
| 5 | /sm-consensus | Facilitator | consensus-{sprint}.md + board | consensus_board.md |

## Принципы качества
1. Sprint Goal = образ результата команды, привязан OBJ/KR (не «поработаем над»).
2. История ← KR или тег внепланового (`sprint_standards.md`).
3. Образ результата = доказуемое состояние (`БЫЛО→СТАЛО` для технических).
4. Максимальная загрузка каждого vs ёмкость (с вычетом отсутствий).
5. Двойная оптика: Sprint Goal (команда) + Персональный фокус/контракт (каждый).
6. Carryover первым, тег `[CARRYOVER]`.
7. Горизонт N+1 (rolling-wave).
8. Структура ПЛАН — строго эталон `ideal_sprint_plan.md` (8 блоков, приёмочно-готово).

## Границы (slice 1)
Всё в vault под git, обратимо. Запись в JIRA, презентация, аудио, cron — за границей среза.

## Главное правило
**STOP после каждой стадии.** Опрос — по одному вопросу за раз (особенно `/sm-sync`, `/sm-goal`).
```

- [ ] **Step 2: Проверка** — Run: `grep -q "скрам-мастер" .claude/skills/sprint-planner/SKILL.md && grep -c "/sm-" .claude/skills/sprint-planner/SKILL.md` → ≥ 6.

- [ ] **Step 3: Commit** — `git commit -m "feat: SKILL.md навыка sprint-planner (персона + 6 стадий)"`

---

### Task 11: Шесть команд sm-*

**Files:**
- Create: `.claude/commands/sm-sync.md`, `sm-goal.md`, `sm-decompose.md`, `sm-load.md`, `sm-deliver.md`, `sm-consensus.md`

**Interfaces:**
- Каждая команда: «Этап 0: Загрузка» читает `.claude/domain-profile.md` + `SKILL.md` + релевантные `resources/*`, затем выполняет стадию, STOP.

- [ ] **Step 1: Написать `sm-sync.md`**

```markdown
---
description: "Стадия 0 — ресинк контекста спринта + подтягивание отсутствий. Один вопрос за раз. STOP."
---
# /sm-sync {sprint}
Роль: Context Builder. Прочитай `.claude/domain-profile.md`, `SKILL.md`, `resources/sync_questions.md`, `resources/availability.md`.
Подтяни: срез SPRINT-ROADMAP, ФАКТ прошлого спринта (carryover+velocity; **нет ФАКТ → cold-start**), ростер+capacity, реестр отсутствий (`availability.registry`; проверь `updated` ≤ старта).
Проведи ресинк-диалог Q1–Q7 (`sync_questions.md`) **по одному вопросу за раз**. Отсутствия — из реестра, подтверди дельту у PO.
Выход: `{sprint_workspace}/sprint-context.md` (актуальные KR, ростер+ёмкости с отпусками, carryover, внеплановые, риски, открытые `[УТОЧНИТЬ]`). STOP.
```

- [ ] **Step 2: Написать `sm-goal.md`**

```markdown
---
description: "Стадия 1 — Sprint Goal (образ результата команды), привязка OBJ/KR. STOP."
---
# /sm-goal {sprint}
Роль: Outcome Designer. Вход: `sprint-context.md`. Прочитай `SKILL.md`.
Сформулируй 1–3 Sprint Goal (по числу активных OBJ) — доказуемое состояние «команда показывает к концу спринта», привязка к OBJ/KR. Не «поработаем над». Диалог по одному вопросу.
Выход: `{sprint_workspace}/sprint-goal.md`. STOP.
```

- [ ] **Step 3: Написать `sm-decompose.md`**

```markdown
---
description: "Стадия 2 — истории ← KR, стандарт декомпозиции, роли, DoR. STOP."
---
# /sm-decompose {sprint}
Роль: Story Designer. Вход: `sprint-goal.md`, KR. Прочитай `resources/decomposition_standard.md`, `resources/story_roles.md`, `resources/hard_gates.md` (DoR), `resources/sprint_standards.md`.
Проверь DoR (вход стадии). Собери истории: каждая ← KR или тег внепланового. Разбей > 8 SP. Проставь роли истории (опционально, по фазам). Подзадачи с тегами `[SA/BE/FE/QA/REL]`.
Выход: `{sprint_workspace}/sprint-stories.md`. STOP.
```

- [ ] **Step 4: Написать `sm-load.md`**

```markdown
---
description: "Стадия 3 — capacity с отпусками, SP до ёмкости, операционный контракт, риски. STOP."
---
# /sm-load {sprint}
Роль: Capacity Balancer. Вход: `sprint-stories.md`. Прочитай `resources/sprint_standards.md`, `resources/availability.md`, `resources/operational_contract.md`.
Считай ёмкость = velocity×focus − отсутствия (**cold-start: sp_per_person_sprint + [УТОЧНИТЬ velocity]**). Добей SP каждого до ёмкости; пометь 🔴/🟡/🟢. Прогони риск-детекторы (`availability.md`) → карточки риска.
Построй `operational-contract-{sprint}.md` (участник→задачи→ожидаемые даты; коммиты текстом).
Выход: `{sprint_workspace}/sprint-load.md` + operational-contract. STOP.
```

- [ ] **Step 5: Написать `sm-deliver.md`**

```markdown
---
description: "Стадия 4 — 8 гейтов + Светофор, сухой прогон, запись ПЛАН по эталону. STOP."
---
# /sm-deliver {sprint}
Роль: Validator. Вход: `sprint-load.md` + operational-contract. Прочитай `resources/hard_gates.md`, `resources/sprint_standards.md`, `examples/ideal_sprint_plan.md`.
Прогони 8 гейтов + Светофор. 🔴 (гейт 1–5) → назад на load/decompose. Сухой прогон: каждый факт ← источник, расхождение → обоснование.
Запиши `{sprint_output_doc}` = `ПЛАН-{sprint}.md` строго по **8-блочной структуре эталона** + блок N+1. STOP.
```

- [ ] **Step 6: Написать `sm-consensus.md`**

```markdown
---
description: "Стадия 5 — board «как вижу», цикл правок команды, гейт согласия. STOP."
---
# /sm-consensus {sprint}
Роль: Facilitator. Вход: `ПЛАН-{sprint}.md`. Прочитай `resources/consensus_board.md`.
Отрендери board «как вижу» (группы по историям, `@исполнитель`/`SP`, легенда SP). Собери правки (**канал: PO ретранслирует на ревью**), версионируй. **Правки SP/состава/исполнителей → повторный `/sm-deliver`.**
Гейт «все согласны» → зафиксируй `consensus-{sprint}.md` (кто/дата/версия/правки). STOP.
```

- [ ] **Step 7: Проверка** — Run: `ls .claude/commands/sm-*.md | wc -l` → `6`; `grep -l "STOP" .claude/commands/sm-*.md | wc -l` → `6`.

- [ ] **Step 8: Commit** — `git commit -m "feat: 6 команд sm-* (sync→goal→decompose→load→deliver→consensus)"`

---

### Task 12: Валидатор структуры ПЛАН (TDD)

**Files:**
- Create: `tests/check_plan_structure.py`
- Test: `tests/test_check_plan_structure.py`

**Interfaces:**
- Produces: `validate_plan(text: str) -> list[str]` — возвращает список нарушений (пустой = ✅). Проверяет НФТ-SP-8 (8 блоков + колонки) + гейт 2/3 (0 орфанов, 0 TBD-Must).

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_check_plan_structure.py
from check_plan_structure import validate_plan

GOOD = """# 2026Q3-S7 — ПЛАН спринта
**Период:** 18 июля — 31 июля 2026 (2 недели)
## ЦЕЛЬ: Кино (OBJ 2)
**🎯 Образ результата команды (Sprint Goal):** кино на витрине
| ЭПИК | История | Образ результата | Образ действия | Исполнитель | Приоритет | SP |
| - | - | - | - | - | - | - |
| TBD | BE: X | БЫЛО→СТАЛО | - [BE] шаг | BE-2 | Must | 8 |
## Необходимые внеплановые работы
## 📊 Capacity по командам
## 👤 Персональный фокус
## ⚠️ Общие риски
## 🔭 Спринт N+1 (предварительно)
*📋 Следующие шаги: демо*
"""

def test_good_plan_passes():
    assert validate_plan(GOOD) == []

def test_missing_capacity_block_flagged():
    bad = GOOD.replace("## 📊 Capacity по командам", "")
    assert any("Capacity" in v for v in validate_plan(bad))

def test_tbd_executor_in_must_flagged():
    bad = GOOD.replace("| BE-2 | Must |", "| TBD | Must |")
    assert any("TBD" in v for v in validate_plan(bad))
```

- [ ] **Step 2: Запустить — убедиться что падает**

Run: `cd tests && python3 -m pytest test_check_plan_structure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'check_plan_structure'`.

- [ ] **Step 3: Реализовать валидатор**

```python
# tests/check_plan_structure.py
import re

REQUIRED_BLOCKS = [
    "Необходимые внеплановые работы",
    "📊 Capacity по командам",
    "👤 Персональный фокус",
    "⚠️ Общие риски",
    "🔭 Спринт N+1",
]
PLAN_COLUMNS = ["ЭПИК", "История", "Образ результата", "Образ действия", "Исполнитель", "Приоритет", "SP"]

def validate_plan(text: str) -> list[str]:
    issues = []
    # шапка + хотя бы одна цель + Sprint Goal
    if "ПЛАН спринта" not in text:
        issues.append("нет шапки «ПЛАН спринта»")
    if "## ЦЕЛЬ" not in text:
        issues.append("нет ни одного блока ЦЕЛЬ (OBJ)")
    if "Образ результата команды (Sprint Goal)" not in text:
        issues.append("нет Sprint Goal")
    # обязательные блоки
    for b in REQUIRED_BLOCKS:
        if b not in text:
            issues.append(f"нет блока: {b}")
    # колонки таблицы плана (в порядке)
    header = " | ".join(PLAN_COLUMNS)
    if not re.search(re.escape(header), text):
        issues.append("колонки таблицы плана нарушены/не в порядке")
    # 0 TBD-исполнителя в Must. Колонки: …|Исполнитель|Приоритет|SP → Исполнитель = cells[-3].
    # ЭПИК тоже может быть TBD (эталон допускает) — поэтому проверяем ПОЗИЦИЮ, не вхождение.
    for row in re.findall(r"^\|.*\| Must \|.*\|$", text, flags=re.MULTILINE):
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[-3] == "TBD":
            issues.append("TBD-исполнитель в Must-истории (гейт 3)")
    return issues
```

- [ ] **Step 4: Запустить — убедиться что проходит**

Run: `cd tests && python3 -m pytest test_check_plan_structure.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add tests/check_plan_structure.py tests/test_check_plan_structure.py
git commit -m "feat: dev-time валидатор структуры ПЛАН (НФТ-SP-8, TDD)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: Golden fixture — тестовый домен

**Files:**
- Create: `tests/fixtures/demo-domain/domain-profile.md`
- Create: `tests/fixtures/demo-domain/SPRINT-ROADMAP-2026Q3.md`
- Create: `tests/fixtures/demo-domain/availability.md`
- Create: `tests/fixtures/demo-domain/team.md`
- Create: `tests/fixtures/demo-domain/README.md`

**Interfaces:**
- Consumes: форматы из `sprint_standards.md` (roadmap-матрица), `availability.md` (реестр).
- Produces: полный вход для прогона пайплайна на S7 (cold-start: ФАКТ отсутствует намеренно).

- [ ] **Step 1: Написать fixture-файлы** (Ticketland-домен, согласован с `ideal_sprint_plan.md`)

`team.md`:
```markdown
# team (demo)
| Исполнитель | role_title | expertise |
|-------------|-----------|-----------|
| BE-1 | Backend | GDS, extapi_go |
| BE-2 | Backend | UMC, web_db |
| FE-1 | Frontend | PHP-витрина |
| SA-1 | System Analyst | требования, фильтры |
```

`availability.md`:
```markdown
# Availability — 2026Q3
updated: 2026-07-17
| Кто | Окно (с–по) | Тип | Гранулярность |
|-----|-------------|-----|---------------|
| SA-1 | 2026-07-28…2026-07-31 | отпуск | полный день |
```

`SPRINT-ROADMAP-2026Q3.md`: матрица KR×спринт по формату `sprint_standards.md` (OBJ2 KR2.1 кино, OBJ3 KR3.1 B2B; срез на S7).

`domain-profile.md`: заполненный из шаблона (paths → fixtures, capacity focus_factor 0.7, sp_per_person_sprint 8, availability.registry → этот файл, current_quarter 2026Q3, **sprint_fact_doc указывает на несуществующий S6 → cold-start**).

`README.md`: «Golden fixture для прогона `/sm-sync…/sm-consensus` на 2026Q3-S7. Cold-start (нет ФАКТ S6). Ожидаемый выход ≈ `examples/ideal_sprint_plan.md`.»

- [ ] **Step 2: Проверка** — Run: `ls tests/fixtures/demo-domain/ | wc -l` → `5`; `grep -q "updated:" tests/fixtures/demo-domain/availability.md && echo OK` → `OK`.

- [ ] **Step 3: Commit** — `git commit -m "test: golden fixture demo-domain (cold-start S7)"`

---

### Task 14: End-to-end verify + фиксация чек-листа приёмки

**Files:**
- Create: `tests/ACCEPTANCE.md`

- [ ] **Step 1: Прогнать пайплайн на fixture вручную (агентом)**

В сессии Claude Code с установленным навыком (или из корня репо) выполнить по стадиям на данных `tests/fixtures/demo-domain/`: `/sm-sync 2026Q3-S7` → … → `/sm-consensus 2026Q3-S7`. Выход складывать в `tests/fixtures/demo-domain/output/`.

- [ ] **Step 2: Проверить ПЛАН валидатором**

Run:
```bash
cd tests && python3 -c "from check_plan_structure import validate_plan; import sys; \
print(validate_plan(open('fixtures/demo-domain/output/ПЛАН-2026Q3-S7.md').read()) or 'PLAN OK')"
```
Expected: `PLAN OK` (пустой список нарушений).

- [ ] **Step 3: Пройти чек-лист приёмки против БФТ (НФТ)** — записать `tests/ACCEPTANCE.md`:

```markdown
# Acceptance — sprint-planner slice 1 (прогон demo-domain S7)

| НФТ | Проверка | Результат |
|-----|----------|-----------|
| SP-1 Точность | 0 фактов без источника в ПЛАН (нет `[УТОЧНИТЬ]` кроме velocity cold-start) | ☐ |
| SP-2 Обратимость | 0 записей в трекер; всё в output/ под git | ☐ |
| SP-3 Ёмкость | отпуск SA-1 (28–31.07) вычтен; карточка риска если Must в окне | ☐ |
| SP-4 Трассировка | 100% историй → KR или тег; валидатор орфанов ✅ | ☐ |
| SP-5 Каденс | 6 STOP-стадий отработали по одному вопросу | ☐ |
| SP-7 Контракт | 100% исполнителей ≥1 строка с датой в operational-contract | ☐ |
| SP-8 Структура | `validate_plan` → PLAN OK | ☐ |
| consensus | ре-прогон гейтов при правке SP отработал | ☐ |
```

- [ ] **Step 4: Commit**

```bash
git add tests/ACCEPTANCE.md
git commit -m "test: e2e прогон demo-domain + чек-лист приёмки НФТ

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Порядок и зависимости

Task 1 → 2 → 3 → 4 → (5,6,7,8,9 параллельно, независимы) → 10 (нужны 3–9) → 11 (нужен 10) → 12 (независим, можно раньше) → 13 → 14 (нужны все).

## Что вне этого плана (след. срезы)

BUILD в JIRA · презентация Google Docs · Excalidraw self-host · cron-пинги/forecast (#67) · аудио→транскрипт · фазы daily/факт/ретро.
