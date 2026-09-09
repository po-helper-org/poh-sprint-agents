import sys
from pathlib import Path

# Валидаторы ставятся вместе с навыком: команды зовут их в целевом проекте,
# где каталога tests/ нет.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / ".claude/skills/sprint-result/scripts"))

from check_report_structure import readability_warnings, validate_report

GOOD = """# ФАКТ | 2026Q3-S8
**Период:** 18 — 31 августа 2026 · **Ответственный:** PO · **Статус:** закрыт · **Версия:** 1

## КОМАНДА: Ядро — Шлюзы

### СТРИМ: Перенос нагрузки

**Вердикт по Sprint Goal:** достигнут частично
Обещали X. Показываем Y.

| Задачи | Комментарий | Результат |
| - | - | - |
| [BE] BE-1: Переключение | - Выкатили<br>- **Причина:** откат<br>След. шаг: правка | 80% · ревью пройдено |
| [BE] BE-2: Методы записи | - В проде | 100% · в Production |

## Итоги спринта

### Ключевые риски и блокеры
- **Смежная система** — держит уведомления

### Переносим в 2026Q3-S9
- **Переключение** — 80%
"""


def test_good_report_passes():
    assert validate_report(GOOD) == []
    assert readability_warnings(GOOD) == []


def test_missing_verdict_flagged():
    bad = GOOD.replace("**Вердикт по Sprint Goal:** достигнут частично", "")
    assert any("гейт 4" in v for v in validate_report(bad))


def test_unplanned_stream_needs_no_verdict():
    # Сборник влётов — не цель: Sprint Goal у него нет по природе.
    extra = ("### СТРИМ: Внеплановые работы и влёты\n\n"
             "| Задачи | Комментарий | Результат |\n| - | - | - |\n"
             "| [BUG] BE-1: Фикс | - Закрыт | 100% · в Production |\n\n")
    assert validate_report(GOOD.replace("## Итоги спринта", extra + "## Итоги спринта")) == []


def test_result_without_ladder_step_flagged():
    bad = GOOD.replace("| 80% · ревью пройдено |", "| 80% |")
    assert any("без ступени" in v for v in validate_report(bad))


def test_unclosed_row_without_reason_flagged():
    bad = GOOD.replace("<br>- **Причина:** откат", "")
    assert any("без причины" in v for v in validate_report(bad))


def test_unclosed_row_without_next_step_flagged():
    bad = GOOD.replace("<br>След. шаг: правка", "")
    assert any("без следующего шага" in v for v in validate_report(bad))


def test_closed_row_needs_no_explanation():
    assert not any("BE-2" in v for v in validate_report(GOOD))


def test_activity_row_exempt():
    row = "| [QA] QA-1: Онбординг | - Идёт | ACTIVITY · фоновая |\n"
    text = GOOD.replace("\n## Итоги спринта", "\n" + row + "\n## Итоги спринта", 1)
    assert not any("Онбординг" in v for v in validate_report(text))


def test_blocked_row_needs_explanation():
    # «🛑 0%» — не 100%: без причины и шага отчёт молчит о том, что держит строку.
    bad = GOOD.replace("| [BE] BE-2: Методы записи | - В проде | 100% · в Production |",
                       "| [BE] BE-2: Методы записи | - Готово на стенде | 🛑 0% · ждёт вебхук |")
    issues = validate_report(bad)
    assert any("без причины" in v for v in issues)
    assert any("без следующего шага" in v for v in issues)


def test_stop_marker_parsed_as_scale_value():
    # Стоп-маркер перед процентом не должен читаться как «значение не по шкале».
    bad = GOOD.replace("| [BE] BE-2: Методы записи | - В проде | 100% · в Production |",
                       "| [BE] BE-2: Методы записи | - Снято<br>- **Причина:** переключили "
                       "исполнителя<br>След. шаг: вернуть в S9 | 🚫 0% · не начиналась |")
    assert not any("не по шкале" in v for v in validate_report(bad))


def test_missing_meta_field_flagged():
    assert any("Версия" in v for v in validate_report(GOOD.replace("**Версия:** 1", "")))


def test_missing_risks_block_flagged():
    bad = GOOD.replace("### Ключевые риски и блокеры", "")
    assert any("Ключевые риски" in v for v in validate_report(bad))


def test_broken_columns_flagged():
    bad = GOOD.replace("| Задачи | Комментарий | Результат |",
                       "| Комментарий | Задачи | Результат |")
    assert any("колонки" in v for v in validate_report(bad))


def test_padded_header_passes():
    padded = GOOD.replace("| Задачи | Комментарий | Результат |",
                          "| Задачи  | Комментарий | Результат  |")
    assert validate_report(padded) == []


def test_too_many_rows_warns_but_does_not_block():
    last = "| [BE] BE-2: Методы записи | - В проде | 100% · в Production |"
    extra = "".join("\n| [BE] BE-%d: Строка | - В проде | 100%% · в Production |" % i
                    for i in range(3, 10))
    noisy = GOOD.replace(last, last + extra, 1)
    assert validate_report(noisy) == []
    assert any("гейт 6" in w for w in readability_warnings(noisy))
