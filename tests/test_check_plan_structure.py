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

def test_tbd_executor_in_unplanned_must_flagged():
    # Таблица «Необходимые внеплановые работы» — 8 колонок (добавлена Тег в конце).
    # Регресс: cells[-3] при 8 колонках попадает на Приоритет, а не Исполнитель.
    bad = GOOD.replace(
        "## Необходимые внеплановые работы",
        "## Необходимые внеплановые работы\n"
        "| ЭПИК | История | Образ результата | Образ действия | Исполнитель | Приоритет | SP | Тег |\n"
        "| - | - | - | - | - | - | - | - |\n"
        "| OBJ 3 | BE: Y | БЫЛО→СТАЛО | - [BE] шаг | TBD | Must | 5 | внеплан |",
    )
    assert any("TBD" in v for v in validate_plan(bad))

def test_bold_must_executor_tbd_flagged():
    bad = GOOD.replace("| BE-2 | Must | 8 |", "| TBD | **Must** | 8 |")
    assert any("TBD" in v for v in validate_plan(bad))

def test_padded_header_passes():
    padded = GOOD.replace(
        "| ЭПИК | История | Образ результата | Образ действия | Исполнитель | Приоритет | SP |",
        "| ЭПИК  | История | Образ результата | Образ действия  | Исполнитель | Приоритет | SP |",
    )
    assert validate_plan(padded) == []

def test_missing_next_steps_block_flagged():
    bad = GOOD.replace("*📋 Следующие шаги: демо*", "")
    assert any("Следующие шаги" in v for v in validate_plan(bad))
