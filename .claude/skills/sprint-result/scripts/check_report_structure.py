"""Валидатор структуры отчёта ФАКТ — машинная часть гейтов.

Проверяет НФТ-SR-8 (обязательные блоки и колонки) и то из гейтов
`resources/fact_gates.md`, что проверяется без знания ПЛАН:

  гейт 2 — строка с «Результат» < 100% несёт причину и следующий шаг;
  гейт 3 — у каждого значения «Результат» названа ступень лестницы;
  гейт 4 — у каждого стрима есть вердикт по Sprint Goal (наличие, не качество);
  гейт 6 — строк на стрим не больше, чем влезает в слайд (предупреждение).

Вне scope: гейт 1 (трассировка к ПЛАН — валидатор не знает плана), качество
вердикта, гейт 5 (чистота публикации — нужен вайтлист домен-профиля), гейт 9
(регистр текста — отдельный `sprint-report-style-lint.py`).

CLI: python3 .claude/skills/sprint-result/scripts/check_report_structure.py \
         ФАКТ-{sprint}.md
Код возврата: 1 при блокирующих нарушениях, 0 при чистом прогоне и 🟡.
"""
import re
import sys

REPORT_COLUMNS = ["Задачи", "Комментарий", "Результат"]
META_FIELDS = ["Период", "Ответственный", "Статус", "Версия"]
REQUIRED_BLOCKS = ["Итоги спринта"]

# Стрим без Sprint Goal по природе: это не цель, а сборник влётов.
NO_VERDICT_STREAMS = ("Внеплановые", "Прочие активности", "Техдолг")

MAX_ROWS_PER_STREAM = 6

# «100% · в Production», «🛑 0% · ждём смежников», «ACTIVITY · фоновая»
RESULT_RE = re.compile(
    r"^\s*(?:[^\w\s%]+\s*)?(\d{1,3}\s*%|ACTIVITY|заблокировано)\s*(?:·\s*(.+))?$", re.I)


def _strip_bold(cell):
    cell = cell.strip()
    if cell.startswith("**") and cell.endswith("**") and len(cell) >= 4:
        cell = cell[2:-2].strip()
    return cell


def _is_divider(cells):
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells if c)


def _tables(text):
    """Таблицы документа → [(шапка, [строки], заголовок ближайшего раздела)]."""
    out, header, rows, section = [], None, [], None
    for line in text.splitlines():
        if re.match(r"^#{2,3}\s+", line):
            if header:
                out.append((header, rows, section))
            header, rows = None, []
            section = re.sub(r"^#{2,3}\s+", "", line).strip()
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            if header:
                out.append((header, rows, section))
                header, rows = None, []
            continue
        cells = [_strip_bold(c) for c in stripped.strip("|").split("|")]
        if _is_divider(cells):
            continue
        if header is None:
            header = cells
        else:
            rows.append(cells)
    if header:
        out.append((header, rows, section))
    return out


def _streams(text):
    """[(название, тело раздела)] по каждому `### СТРИМ:`."""
    out = []
    for chunk in re.split(r"^###\s+", text, flags=re.M)[1:]:
        head = chunk.splitlines()[0].strip()
        if head.startswith("СТРИМ"):
            name = head.split(":", 1)[1].strip() if ":" in head else head
            out.append((name, chunk))
    return out


def _row_issues(header, rows, section):
    issues = []
    idx = {name.strip().lower(): i for i, name in enumerate(header)}
    i_res = idx.get("результат")
    i_comment = idx.get("комментарий")
    i_task = idx.get("задачи", idx.get("задача"))
    if i_res is None:
        return issues
    for row in rows:
        if i_res >= len(row) or not any(row):
            continue
        task = row[i_task] if i_task is not None and i_task < len(row) else "(без названия)"
        value = row[i_res].strip()
        m = RESULT_RE.match(value)
        if not m:
            issues.append(f"гейт 3: «{task}» — значение «{value}» не по шкале")
            continue
        if not (m.group(2) or "").strip():
            issues.append(f"гейт 3: «{task}» — результат без ступени лестницы")
        head = m.group(1).lower().replace(" ", "")
        if head.startswith("activity") or head == "100%":
            continue
        comment = row[i_comment] if i_comment is not None and i_comment < len(row) else ""
        low = comment.lower()
        if "причина" not in low and "блокатор" not in low and "блокер" not in low:
            issues.append(f"гейт 2: «{task}» — незакрытая строка без причины")
        if not re.search(r"след\.?\s*шаг|следующий шаг|следующий спринт|"
                         r"в след(ующем|\.)?\s*спринте", low):
            issues.append(f"гейт 2: «{task}» — незакрытая строка без следующего шага")
    return issues


def validate_report(text):
    """Блокирующие нарушения. [] — чисто."""
    issues = []
    if not re.search(r"^#\s*ФАКТ\s*\|", text, re.M):
        issues.append("нет шапки «# ФАКТ | {sprint}»")
    for field in META_FIELDS:
        if not re.search(r"\*\*%s:?\*\*" % field, text):
            issues.append(f"нет поля шапки: {field}")

    streams = _streams(text)
    if not streams:
        issues.append("нет ни одного блока «### СТРИМ:»")

    for block in REQUIRED_BLOCKS:
        if not re.search(r"^##\s*%s" % re.escape(block), text, re.M):
            issues.append(f"нет блока: {block}")
    if not re.search(r"^###\s*Ключевые риски", text, re.M):
        issues.append("нет блока: Ключевые риски и блокеры")

    for name, chunk in streams:
        if name.startswith(NO_VERDICT_STREAMS):
            continue
        if "Вердикт по Sprint Goal" not in chunk:
            issues.append(f"гейт 4: «{name}» — нет вердикта по Sprint Goal")

    tables = _tables(text)
    row_tables = [t for t in tables if [c.strip() for c in t[0][:3]] == REPORT_COLUMNS]
    if not row_tables:
        issues.append("колонки таблицы строк нарушены/не в порядке "
                      "(ожидается Задачи | Комментарий | Результат)")
    for header, rows, section in row_tables:
        issues.extend(_row_issues(header, rows, section))
    return issues


def readability_warnings(text):
    """Гейт 6 — 🟡. Агент предупреждает, разрез решает PO (решение Д2)."""
    warnings = []
    for header, rows, section in _tables(text):
        if not section or not section.startswith("СТРИМ"):
            continue
        filled = [r for r in rows if any(r)]
        if len(filled) > MAX_ROWS_PER_STREAM:
            name = section.split(":", 1)[-1].strip()
            warnings.append(f"гейт 6: «{name}» — строк {len(filled)}, порог "
                            f"{MAX_ROWS_PER_STREAM}; экспортёр разрежет на «(продолжение)»")
    return warnings


def main(argv):
    if len(argv) != 2:
        print("использование: check_report_structure.py ФАКТ-{sprint}.md", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        text = fh.read()
    issues, warnings = validate_report(text), readability_warnings(text)
    for w in warnings:
        print("🟡 " + w)
    for i in issues:
        print("🔴 " + i)
    if not issues:
        print("🟢 REPORT OK" if not warnings else "🟡 REPORT OK с предупреждениями")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
