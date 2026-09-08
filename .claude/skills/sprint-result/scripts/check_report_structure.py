"""Dev-time валидатор структуры отчёта ФАКТ.

Проверяет НФТ-SR-8 (обязательные блоки + колонки таблицы) и машинную часть
гейтов отчёта (`.claude/skills/sprint-result/resources/fact_gates.md`):

  гейт 2 — строка с «Результат» < 100% несёт «Причина» и «Следующий шаг»;
  гейт 3 — у каждого значения «Результат» названа ступень лестницы;
  гейт 4 — у каждой инициативы есть вердикт по Sprint Goal (наличие, не качество);
  гейт 6 — читаемость: ≤ 5 инициатив, ≤ 6 строк на инициативу (предупреждение).

Не входит в scope: гейт 1 (трассировка к ПЛАН — валидатор не знает плана),
качество вердикта и гейт 5 (чистота публикации — нужен вайтлист домен-профиля).
Это ответственность агента через fact_gates.md.

CLI: python3 .claude/skills/sprint-result/scripts/check_report_structure.py \
         ФАКТ-{sprint}.md
Код возврата: 1 при блокирующих нарушениях, 0 при чистом прогоне и 🟡.
"""
import re
import sys

REQUIRED_BLOCKS = ["Итог для бизнеса", "Перенос"]
REPORT_COLUMNS = ["Задача", "Комментарий", "Результат"]
META_FIELDS = ["Период", "Ответственный", "Статус", "Версия"]

MAX_INITIATIVES = 5
MAX_ROWS_PER_INITIATIVE = 6

# «100% · в Production» — число и ступень, из которой оно выведено (гейт 3).
RESULT_RE = re.compile(r"^\s*(\d{1,3}\s*%|ACTIVITY|заблокировано)\s*(·\s*(.+))?$", re.I)


def _strip_bold(cell):
    cell = cell.strip()
    if cell.startswith("**") and cell.endswith("**") and len(cell) >= 4:
        cell = cell[2:-2].strip()
    return cell


def _is_divider(cells):
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells if c)


def _tables(text):
    """Markdown-таблицы документа → [(шапка, [строки], заголовок раздела)]."""
    out, header, rows, section = [], None, [], None
    for line in text.splitlines():
        if line.startswith("## "):
            if header:
                out.append((header, rows, section))
            header, rows = None, []
            section = line[3:].strip()
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


def _row_issues(header, rows, section):
    """Гейты 2 и 3 по строкам одной таблицы."""
    issues = []
    idx = {name.strip().lower(): i for i, name in enumerate(header)}
    i_res, i_comment, i_task = (idx.get("результат"), idx.get("комментарий"),
                               idx.get("задача"))
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
        if not (m.group(3) or "").strip():
            issues.append(f"гейт 3: «{task}» — процент без ступени лестницы")
        head = m.group(1).lower()
        if head.startswith("activity"):
            continue
        done = head.replace(" ", "") == "100%"
        if done:
            continue
        comment = row[i_comment] if i_comment is not None and i_comment < len(row) else ""
        low = comment.lower()
        if "причина" not in low:
            issues.append(f"гейт 2: «{task}» — незакрытая строка без причины")
        if "следующий шаг" not in low:
            issues.append(f"гейт 2: «{task}» — незакрытая строка без следующего шага")
    return issues


def validate_report(text):
    """Блокирующие нарушения структуры и машинных гейтов. [] — чисто."""
    issues = []
    if not re.search(r"^#\s*ФАКТ\s*\|", text, re.M):
        issues.append("нет шапки «# ФАКТ | {sprint}»")
    for field in META_FIELDS:
        if not re.search(r"\*\*%s:?\*\*" % field, text):
            issues.append(f"нет поля шапки: {field}")

    initiatives = re.findall(r"^##\s*ИНИЦИАТИВА:\s*(.+)$", text, re.M)
    if not initiatives:
        issues.append("нет ни одного блока «## ИНИЦИАТИВА:»")

    for block in REQUIRED_BLOCKS:
        if not re.search(r"^##\s*%s" % re.escape(block), text, re.M):
            issues.append(f"нет блока: {block}")
    if "Следующие шаги" not in text:
        issues.append("нет блока: Следующие шаги")

    # гейт 4 — вердикт в каждой секции инициативы
    for chunk in re.split(r"^##\s+", text, flags=re.M)[1:]:
        if chunk.startswith("ИНИЦИАТИВА") and "Вердикт по Sprint Goal" not in chunk:
            name = chunk.splitlines()[0].strip()
            issues.append(f"гейт 4: «{name}» — нет вердикта по Sprint Goal")

    # колонки таблицы строк (первые три в порядке)
    tables = _tables(text)
    row_tables = [t for t in tables
                  if [c.strip() for c in t[0][:3]] == REPORT_COLUMNS]
    if not row_tables:
        issues.append("колонки таблицы строк нарушены/не в порядке "
                      "(ожидается Задача | Комментарий | Результат)")
    for header, rows, section in row_tables:
        issues.extend(_row_issues(header, rows, section))
    return issues


def readability_warnings(text):
    """Гейт 6 — 🟡, не блокирует. Агент предупреждает, разрез решает PO (Д2)."""
    warnings = []
    initiatives = re.findall(r"^##\s*ИНИЦИАТИВА:\s*(.+)$", text, re.M)
    if len(initiatives) > MAX_INITIATIVES:
        warnings.append(f"гейт 6: инициатив {len(initiatives)}, порог {MAX_INITIATIVES}")
    for header, rows, section in _tables(text):
        if not section or not section.startswith("ИНИЦИАТИВА"):
            continue
        filled = [r for r in rows if any(r)]
        if len(filled) > MAX_ROWS_PER_INITIATIVE:
            name = section.split(":", 1)[-1].strip()
            warnings.append(f"гейт 6: «{name}» — строк {len(filled)}, "
                            f"порог {MAX_ROWS_PER_INITIATIVE}")
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
