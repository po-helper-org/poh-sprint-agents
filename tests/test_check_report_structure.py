import sys
from pathlib import Path

# Валидатор ставится вместе с навыком: команды зовут его в целевом проекте,
# где каталога tests/ нет.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / ".claude/skills/sprint-result/scripts"))

from check_report_structure import readability_warnings, validate_report

GOOD = """# ФАКТ | 2026Q3-S8
**Период:** 18 — 31 августа 2026 · **Ответственный:** PO · **Статус:** закрыт · **Версия:** 1

## Итог для бизнеса
Новый тип контента в проде.

## ИНИЦИАТИВА: Перенос нагрузки (KR 1.1)
**Вердикт по Sprint Goal:** достигнут частично.
Обещали X. Показываем Y. Не показываем Z.

| Задача | Комментарий | Результат | OKR команды |
| - | - | - | - |
| [BE] BE-1: Переключение | Факт: переключено.<br>Причина: откат.<br>Следующий шаг: правка. | 80% · ревью пройдено | KR 1.1 |
| [BE] BE-2: Методы записи | Факт: в проде. | 100% · в Production | KR 1.2 |

## Перенос в 2026Q3-S9 и следующие шаги
- Переключение — 80%.

*Следующие шаги: демо.*
"""


def test_good_report_passes():
    assert validate_report(GOOD) == []
    assert readability_warnings(GOOD) == []


def test_missing_verdict_flagged():
    bad = GOOD.replace("**Вердикт по Sprint Goal:** достигнут частично.", "")
    assert any("гейт 4" in v for v in validate_report(bad))


def test_percent_without_ladder_step_flagged():
    bad = GOOD.replace("| 80% · ревью пройдено |", "| 80% |")
    assert any("без ступени" in v for v in validate_report(bad))


def test_unclosed_row_without_reason_flagged():
    bad = GOOD.replace("<br>Причина: откат.", "")
    assert any("без причины" in v for v in validate_report(bad))


def test_unclosed_row_without_next_step_flagged():
    bad = GOOD.replace("<br>Следующий шаг: правка.", "")
    assert any("без следующего шага" in v for v in validate_report(bad))


def test_closed_row_needs_no_reason():
    # Гейт 2 спрашивает только незакрытые: у 100% объяснять нечего.
    assert not any("BE-2" in v for v in validate_report(GOOD))


def test_activity_row_exempt_from_gate2():
    row = ("| [QA] QA-1: Онбординг | Факт: идёт. | ACTIVITY · фоновая | `[UNPLANNED]` |\n"
           "\n## Перенос")
    text = GOOD.replace("\n## Перенос", "\n" + row, 1)
    assert not any("Онбординг" in v for v in validate_report(text))


def test_blocked_row_needs_reason():
    # «заблокировано» — не 100%: объяснение обязательно, иначе отчёт молчит
    # о том, что именно держит строку.
    bad = GOOD.replace(
        "| [BE] BE-2: Методы записи | Факт: в проде. | 100% · в Production | KR 1.2 |",
        "| [BE] BE-2: Методы записи | Факт: готово на стенде. | заблокировано · ждёт вебхук | KR 1.2 |")
    issues = validate_report(bad)
    assert any("без причины" in v for v in issues)
    assert any("без следующего шага" in v for v in issues)


def test_missing_meta_field_flagged():
    bad = GOOD.replace("**Версия:** 1", "")
    assert any("Версия" in v for v in validate_report(bad))


def test_broken_columns_flagged():
    bad = GOOD.replace("| Задача | Комментарий | Результат | OKR команды |",
                       "| Комментарий | Задача | Результат | OKR команды |")
    assert any("колонки" in v for v in validate_report(bad))


def test_padded_header_passes():
    padded = GOOD.replace("| Задача | Комментарий | Результат | OKR команды |",
                          "| Задача  | Комментарий | Результат  | OKR команды |")
    assert validate_report(padded) == []


def test_too_many_rows_warns_but_does_not_block():
    # Строки дописываются в ту же таблицу: пустая строка разорвала бы её на две,
    # и порог не сработал бы ни на одной.
    last = "| [BE] BE-2: Методы записи | Факт: в проде. | 100% · в Production | KR 1.2 |"
    extra = "".join(
        "\n| [BE] BE-%d: Строка | Факт: в проде. | 100%% · в Production | KR 1.1 |" % i
        for i in range(3, 10))
    noisy = GOOD.replace(last, last + extra, 1)
    assert validate_report(noisy) == []
    assert any("гейт 6" in w for w in readability_warnings(noisy))
