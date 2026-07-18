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
