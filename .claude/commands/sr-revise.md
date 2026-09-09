---
description: "Круг правок: промт с колоды → правки → ре-прогон гейтов и валидаторов → версия +1 + пересборка колоды. STOP."
---
# /sr-revise {sprint}
Роль: Reviser. Вход — промт, собранный на колоде (слайд + строка + текст правки). Прочитай `{sprint_report_doc}`, `resources/fact_gates.md`, `resources/report_structure.md`, `resources/comment_logic.md`, `resources/writing_register.md`.

Внеси каждую правку в **тот раздел и ту строку**, которые названы в промте. Правка PO — источник: записывай как есть, не переформулируй. Меняется процент → перепроверь ступень лестницы (гейт 3). Меняется состав строк → перепроверь трассировку к ПЛАН (гейт 1).

Ре-прогони 9 гейтов, затем **оба валидатора до пересборки колоды**:
```
python3 .claude/skills/sprint-result/scripts/check_report_structure.py   {sprint_report_doc}
python3 .claude/skills/sprint-result/scripts/sprint-report-style-lint.py {sprint_report_doc}
```

Подними `**Версия:**` на 1, добавь строку в «Историю изменений». **Пересобери колоду** — без этого круг не закрывается и те же замечания придут повторно. Отдай PO путь и список внесённых правок. STOP.
