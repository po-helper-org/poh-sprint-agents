---
title: Риски квартала и комментарии к рискам спринта учитывают рефлексию агента (team-pulse)
date: 2026-11-12
kind: feature
area: sprint-business
prs: [42, 43]
tags: [риски, агенты, рефлексия, team-pulse, quarter-risks, sprint-risk-notes]
source: session
---

# Риски учитывают ежедневную рефлексию агента

## Ситуация

Каждый будний день PO-агенты (`po-gds`, `po-live`, `po-mrs`) проходят отчёты и ленту и сдают рефлексию
(poh-widget-call-reflection, `docs/agent-reflection.md`). Итог ложится в знание агента — навык `team-pulse`
профиля (цели и KR, риски и эскалации, кого ждём, статусы задач, правки PO) и `references/po-feedback.md`
(замечания и уроки PO). Бизнес-колода получает рефлексию напрямую (слой агента), а тексты рисков — нет:
навыки `quarter-risks` (риски квартала для CPO) и `sprint-risk-notes` (комментарии к слайду «Риски и проблемы»)
этих файлов не читали, и замечания PO к рефлексиям до рисков не доходили.

## Решение

- В шаг 1 обоих навыков (`hermes/quarter-risks/SKILL.md`, `hermes/sprint-risk-notes/SKILL.md`) — чтение
  `<профиль>/skills/team-pulse/SKILL.md` и `references/po-feedback.md`. Внутри шага 1, а не отдельным шагом:
  cron-промты велят пройти «шаги 1–7», переустанавливать задачи cron не нужно.
- Правила: уроки PO — обязательные; правки PO — факт; риски, эскалации, «кого ждём» из рефлексии — гипотезы,
  каждую сверяет Jira (подтвердилась — пишется, иначе — по Jira, расхождение в `note`); цифры — только из facts.
  Рефлексия старше 3 рабочих дней — так и сказано в ответе.
- Установщики подставляют `{{PULSE}}` (путь в профиле); `--check` ловит навык без team-pulse.

## Проверка

`tests/test_hermes_risk_skills.py` — оба установщика во временном `HERMES_HOME`: путь к team-pulse и po-feedback
подставлен, пустых подстановок нет, чтение — в шаге 1.

## Дополнение: пути установщиков (PR 43)

При переустановке навыков выяснилось: умолчания установщиков (`REPORTS_DIR` = `~/Projects/poh-widget-sprint-observe/
workspace/reports`, конфиг колоды = `<клон виджета>/workspace/…`) на сервере не существуют — снимок и конфиг лежат в
`~/.local/share/…`. Агенты искали их сами (11.11 `sprint-risk-notes` нашёл конфиг через настройки виджета).
Теперь установщики берут умолчания из `~/.config/poh-widget-sprint-business/config.json` (`observe_workspace`,
`workspace`), конфиг колоды подставляется отдельным `{{CONFIG}}`, а не из каталога кода. Нет настроек — прежние
умолчания. Тесты: `test_paths_come_from_widget_config`, `test_without_widget_config_falls_back_to_clone_paths`.
