"""Dev-time валидатор структуры ПЛАН спринта.

Проверяет НФТ-SP-8: наличие 8 обязательных блоков + порядок/состав колонок
таблицы плана, а также гейт 3 (0 TBD-исполнителя в Must-историях) — по ВСЕМ
таблицам документа (и 7-колоночной таблице ЦЕЛЬ, и 8-колоночной таблице
«Необходимые внеплановые работы», где добавлена колонка Тег).

Колонка Исполнитель ищется по имени в шапке каждой markdown-таблицы, а не по
фиксированному смещению — число колонок между таблицами разное.

Не входит в scope: проверка гейта 2 (орфаны — история должна ссылаться на
KR/тег). Это ответственность агента через .claude/skills/sprint-planner/
resources/hard_gates.md, а не этого структурного валидатора.
"""
import re

REQUIRED_BLOCKS = [
    "Необходимые внеплановые работы",
    "📊 Capacity по командам",
    "👤 Персональный фокус",
    "⚠️ Общие риски",
    "🔭 Спринт N+1",
]
PLAN_COLUMNS = ["ЭПИК", "История", "Образ результата", "Образ действия", "Исполнитель", "Приоритет", "SP"]


def _strip_bold(cell: str) -> str:
    cell = cell.strip()
    if cell.startswith("**") and cell.endswith("**") and len(cell) >= 4:
        cell = cell[2:-2].strip()
    return cell


def _find_tbd_must_violations(text: str) -> list[str]:
    """Гейт 3: TBD-исполнитель в Must-истории — по всем markdown-таблицам.

    Колонка Исполнитель определяется по имени в шапке каждой таблицы (там,
    где есть и «Исполнитель», и «Приоритет»), а не по фиксированному
    смещению cells[-3] — это ломается на 8-колоночной таблице внеплановых
    работ (добавлена колонка Тег).
    """
    issues = []
    lines = text.splitlines()
    executor_idx = None
    priority_idx = None
    in_table = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            in_table = False
            executor_idx = None
            priority_idx = None
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        # шапка таблицы: содержит и Исполнитель, и Приоритет
        if "Исполнитель" in cells and "Приоритет" in cells:
            executor_idx = cells.index("Исполнитель")
            priority_idx = cells.index("Приоритет")
            in_table = True
            continue
        if not in_table or executor_idx is None:
            continue
        # разделительная строка (| --- | --- | ...)
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c):
            continue
        if priority_idx >= len(cells) or executor_idx >= len(cells):
            continue
        priority_cell = _strip_bold(cells[priority_idx])
        executor_cell = _strip_bold(cells[executor_idx])
        if priority_cell == "Must" and executor_cell == "TBD":
            issues.append("TBD-исполнитель в Must-истории (гейт 3)")
    return issues


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
    # колонки таблицы плана (в порядке), устойчиво к паддингу/выравниванию
    header_found = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells[: len(PLAN_COLUMNS)] == PLAN_COLUMNS:
            header_found = True
            break
    if not header_found:
        issues.append("колонки таблицы плана нарушены/не в порядке")
    # 0 TBD-исполнителя в Must (гейт 3) — по имени колонки, не по фиксированному offset.
    # ЭПИК тоже может быть TBD (эталон допускает) — колонка Исполнитель ищется явно.
    issues.extend(_find_tbd_must_violations(text))
    return issues
