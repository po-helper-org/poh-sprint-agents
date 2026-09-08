#!/usr/bin/env python3
"""Собирает отчётную страницу спринта из ФАКТ-{sprint}.md.

    python3 sprint-report-html.py <путь-к-ФАКТ-{sprint}.md> [-o out.html]
                                  [--link-whitelist confluence.example,jira.example]

Страница — документ, а не слайды (решение О8): раскладка описана в
docs/superpowers/specs/2026-09-08-sprint-result-html-design.md, а её рабочий
образец — docs/reference/sprint-report-page-mockup.html. Оттуда же взяты
sprint-report.css и sprint-report.js, поэтому расхождение макета и выхода
экспортёра — дефект экспортёра, а не «две разные страницы».

Доменные преобразования поверх markdown:
  1. Колонка «Результат» → заливка по шкале + разбор ступени лестницы.
  2. Колонка «Комментарий» → помеченные строки вместо абзаца.
  3. Блок инициативы → надзаголовок, строка KR, плашка вердикта.
  4. Подсчёт строк по статусам → светофор спринта (по строкам, решение Д1).
  5. «Изменения в процессе спринта» → карточки БЫЛО/СТАЛО/результат.
  6. [УТОЧНИТЬ] → mark + красная точка.
  7. Ссылки — только по вайтлисту (решение О5): без него URL остаётся текстом.
"""
import argparse
import html as htmlmod
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Метки микро-грамматики комментария → класс. Порядок — как в report_structure.md.
COMMENT_LABELS = [
    ("Образ результата", "c-goal"),
    ("Факт", "c-fact"),
    ("Причина", "c-why"),
    ("Блокатор", "c-block"),
    ("Созависимые", "c-dep"),
    ("Следующий шаг", "c-next"),
]
LABEL_RE = re.compile(
    r"^\s*(%s)\s*:\s*" % "|".join(re.escape(l) for l, _ in COMMENT_LABELS), re.I)

VERDICT_STATES = {
    "достигнут частично": ("v-part", "Достигнут частично."),
    "не достигнут": ("v-no", "Не достигнут."),
    "достигнут": ("v-ok", "Достигнут."),
}

UNC_RE = re.compile(r"`?(\[УТОЧНИТЬ[^\]]*\])`?")
# Хвостовая пунктуация в URL не входит: «…/rec.» в конце предложения — точка
# предложения, а не часть адреса.
URL_RE = re.compile(r"https?://[^\s<>()\"']*[^\s<>()\"'.,;:!?]")


# ---------- инлайн ----------

def inline(text, whitelist=()):
    """Экранирование + инлайн-markdown + ссылки по вайтлисту.

    Ссылка на хост вне вайтлиста остаётся текстом: отчёт уходит наружу, и
    кликабельный внутренний адрес в нём — нарушение гейта 5, а не удобство.
    """
    esc = htmlmod.escape(text)
    esc = UNC_RE.sub(r'<mark class="unc">\1</mark>', esc)
    esc = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
                 lambda m: _link(m.group(2), m.group(1), whitelist), esc)
    esc = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", esc)
    esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
    esc = URL_RE.sub(lambda m: _link(m.group(0), m.group(0), whitelist), esc)
    return esc


def _link(href, label, whitelist):
    host = re.sub(r"^https?://", "", href).split("/")[0].lower()
    if any(host == w or host.endswith("." + w) for w in whitelist):
        return ('<a href="%s" target="_blank" rel="noopener">%s</a>'
                % (htmlmod.escape(href, quote=True), label))
    return label


# ---------- разбор markdown ----------

def split_tables(lines):
    """Плоский поток строк → блоки: ('table', rows) | ('lines', [str])."""
    blocks, buf, table = [], [], []
    for line in lines:
        if line.strip().startswith("|"):
            if buf:
                blocks.append(("lines", buf)); buf = []
            table.append([c.strip() for c in line.strip().strip("|").split("|")])
        else:
            if table:
                blocks.append(("table", table)); table = []
            buf.append(line)
    if buf:
        blocks.append(("lines", buf))
    if table:
        blocks.append(("table", table))
    return blocks


def is_divider(row):
    return all(re.fullmatch(r":?-+:?", c or "-") for c in row)


def parse_sections(body):
    """Тело документа → [(заголовок | None, [строки])]."""
    sections, title, buf = [], None, []
    for line in body.splitlines():
        if line.startswith("## "):
            sections.append((title, buf))
            title, buf = line[3:].strip(), []
        else:
            buf.append(line)
    sections.append((title, buf))
    return sections


# ---------- доменные преобразования ----------

def result_class(value):
    """Значение ячейки «Результат» → класс заливки и нормализованный статус."""
    v = value.strip().lower()
    if v.startswith("заблок") or v.startswith("activity") or not v:
        return "r-idle", "idle"
    m = re.match(r"(\d{1,3})\s*%", v)
    if not m:
        return "r-idle", "idle"
    n = int(m.group(1))
    if n >= 100:
        return "r-ok", "ok"
    if n >= 50:
        return "r-half", "half"
    return "r-low", "low"


def render_result(cell):
    """`100% · в Production` → число крупно + ступень мелким.

    Ступень — гейт 3 в вёрстке: без неё видно, что процент не выведен.
    """
    parts = [p.strip() for p in cell.split("·", 1)]
    num = parts[0]
    step = parts[1] if len(parts) > 1 else ""
    cls, status = result_class(num)
    body = '<span class="num">%s</span>' % htmlmod.escape(num)
    if step:
        body += '<span class="step">%s</span>' % htmlmod.escape(step)
    return '<td class="res %s">%s</td>' % (cls, body), status


def render_comment(cell, whitelist):
    """Ячейка комментария → помеченные строки. Без меток — обычный абзац."""
    out = []
    for chunk in re.split(r"<br\s*/?>", cell):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = LABEL_RE.match(chunk)
        if not m:
            out.append('<span class="c">%s</span>' % inline(chunk, whitelist))
            continue
        label = m.group(1)
        cls = next(c for l, c in COMMENT_LABELS if l.lower() == label.lower())
        rest = chunk[m.end():].strip()
        out.append('<span class="c %s"><b>%s</b>%s</span>'
                   % (cls, htmlmod.escape(label), inline(rest, whitelist)))
    return "<td>%s</td>" % "".join(out)


def render_task(cell, whitelist):
    """`[BE] BE-1: действие` → роль отдельной строкой над названием."""
    m = re.match(r"\s*(\[[A-ZА-Яa-zа-я]+\][^:]*?):\s*(.+)", cell)
    if m:
        return ('<td class="task"><span class="role">%s</span>%s</td>'
                % (htmlmod.escape(m.group(1).strip()), inline(m.group(2), whitelist)))
    return '<td class="task">%s</td>' % inline(cell, whitelist)


def render_table(rows, whitelist, tally):
    """Таблица строк спринта. Колонки узнаются по шапке, не по смещению."""
    header = rows[0]
    body = [r for r in rows[1:] if not is_divider(r)]
    idx = {name.strip().lower(): i for i, name in enumerate(header)}
    i_task = idx.get("задача")
    i_comment = idx.get("комментарий")
    i_res = idx.get("результат")
    i_tag = idx.get("тег")

    cols = ['<col class="c-task">']
    for n, name in enumerate(header[1:], start=1):
        low = name.strip().lower()
        cols.append('<col class="c-res">' if low == "результат"
                    else '<col class="c-okr">' if low in ("тег", "okr команды")
                    else "<col>")

    out = ['<div class="table-wrap"><table>',
           "<colgroup>%s</colgroup>" % "".join(cols),
           "<thead><tr>%s</tr></thead><tbody>"
           % "".join("<th>%s</th>" % htmlmod.escape(h) for h in header)]
    for row in body:
        if all(not c for c in row):
            continue
        cells = []
        for n, cell in enumerate(row):
            if n == i_task:
                cells.append(render_task(cell, whitelist))
            elif n == i_comment:
                cells.append(render_comment(cell, whitelist))
            elif n == i_res:
                td, status = render_result(cell)
                cells.append(td)
                tally[status] += 1
            elif n == i_tag:
                cells.append('<td><span class="tag">%s</span></td>'
                             % htmlmod.escape(cell.strip("`")))
            else:
                cells.append('<td class="okr">%s</td>' % inline(cell, whitelist))
        out.append('<tr class="row">%s</tr>' % "".join(cells))
    out.append("</tbody></table></div>")
    return "\n".join(out)


def render_change_table(rows, whitelist):
    """«Изменения в процессе спринта» → карточки, а не таблица.

    Три колонки таблицы в вёрстке живут по-разному: «было» и «стало» стоят
    рядом для сравнения, результат — под ними с отбивкой.
    """
    body = [r for r in rows[1:] if not is_divider(r) and any(r)]
    out = []
    for row in body:
        who = row[0] if len(row) > 0 else ""
        ba = row[1] if len(row) > 1 else ""
        res = row[2] if len(row) > 2 else ""
        m = re.search(r"БЫЛО\s*:?\s*(.*?)\s*СТАЛО\s*:?\s*(.*)", ba, re.S | re.I)
        was, now = (m.group(1), m.group(2)) if m else (ba, "")
        out.append(
            '<div class="change"><div class="who">Затронуто: %s</div>'
            '<div class="ba"><div><b>Было</b>%s</div><div><b>Стало</b>%s</div></div>'
            '<p class="out">%s</p></div>'
            % (inline(who, whitelist), inline(was.strip(" .;"), whitelist),
               inline(now.strip(), whitelist), inline(res, whitelist)))
    return "\n".join(out)


def render_lines(lines, whitelist, lead_first=False):
    """Абзацы и списки. Единственная проза в отчёте — «Итог для бизнеса»."""
    out, para, bullets, first = [], [], [], True

    def flush_para():
        nonlocal para, first
        if para:
            cls = ' class="lead"' if (lead_first and first) else ""
            out.append("<p%s>%s</p>" % (cls, inline(" ".join(para), whitelist)))
            para = []
            first = False

    def flush_bullets():
        nonlocal bullets
        if bullets:
            out.append("<ul>%s</ul>" % "".join(
                "<li>%s</li>" % inline(b, whitelist) for b in bullets))
            bullets = []

    for raw in lines:
        line = raw.strip()
        if not line or line == "---":
            flush_para(); flush_bullets(); continue
        if line.startswith("> "):
            continue                       # аннотация эталона, не содержимое
        if line.startswith("- "):
            flush_para(); bullets.append(line[2:]); continue
        flush_bullets()
        para.append(line)
    flush_para(); flush_bullets()
    return "\n".join(out)


def render_verdict(lines, whitelist):
    """`**Вердикт по Sprint Goal:** …` + абзац → плашка. Нет — None."""
    text = "\n".join(lines)
    m = re.search(r"\*\*Вердикт по Sprint Goal:?\*\*\s*:?\s*(.+)", text)
    if not m:
        return None, lines
    tail = text[m.end():].strip().splitlines()
    state_raw = m.group(1).strip().rstrip(".").lower()
    cls, label = next(((c, l) for k, (c, l) in VERDICT_STATES.items()
                       if state_raw.startswith(k)), ("v-part", m.group(1).strip()))
    proof = " ".join(l.strip() for l in tail
                     if l.strip() and l.strip() != "---" and not l.strip().startswith("|"))
    plaque = ('<div class="verdict %s"><span class="vlabel">Вердикт по Sprint Goal</span>'
              '<span class="vstate">%s</span><p>%s</p></div>'
              % (cls, htmlmod.escape(label), inline(proof, whitelist)))
    rest = [l for l in lines if not re.search(r"\*\*Вердикт по Sprint Goal", l)]
    if proof:
        rest = [l for l in rest if l.strip() not in proof]
    return plaque, rest


# ---------- сборка ----------

def build(md_text, whitelist):
    lines = md_text.splitlines()
    h1 = next((l[2:].strip() for l in lines if l.startswith("# ")), "ФАКТ")
    sprint = h1.split("|")[-1].strip() if "|" in h1 else h1
    body = "\n".join(lines[lines.index("# " + h1) + 1:])

    meta = {}
    for key in ("Период", "Ответственный", "Статус", "Версия", "План"):
        m = re.search(r"\*\*%s:?\*\*\s*([^*\n·]+)" % key, body)
        if m:
            meta[key] = m.group(1).strip(" ·")

    sections = parse_sections(body)
    tally = {"ok": 0, "half": 0, "low": 0, "idle": 0}
    initiatives = [t for t, _ in sections if t and t.startswith("ИНИЦИАТИВА")]
    parts, seen_init = [], 0

    for title, sec_lines in sections:
        if title is None:
            continue
        anchor = "s-%d" % (len(parts) + 1)
        kicker, heading, krline, plaque = "", title, "", None

        if title.startswith("ИНИЦИАТИВА"):
            seen_init += 1
            kicker = "инициатива %d из %d" % (seen_init, len(initiatives))
            name = title.split(":", 1)[1].strip() if ":" in title else title
            m = re.match(r"(.*?)\s*\(([^)]*KR[^)]*)\)\s*$", name)
            if m:
                heading, krline = m.group(1).strip(), m.group(2).strip()
            else:
                heading = name
            plaque, sec_lines = render_verdict(sec_lines, whitelist)
        elif title.startswith("Итог"):
            kicker = "Спринт %s" % sprint
        elif title.startswith("Внеплановые"):
            kicker = "вне плана"
        elif title.startswith("Изменения"):
            kicker = "договорённости"
        elif title.startswith("Процессные"):
            kicker = "как шёл спринт"
        elif title.startswith("Демо"):
            kicker = "показываем руками"
        elif title.startswith("Перенос"):
            kicker = "в следующий спринт"

        html = ['<h2 id="%s">%s%s</h2>'
                % (anchor,
                   '<span class="kicker">%s</span>' % htmlmod.escape(kicker) if kicker else "",
                   htmlmod.escape(heading))]
        if krline:
            html.append('<p class="krline">%s</p>' % htmlmod.escape(krline))
        if plaque:
            html.append(plaque)

        for kind, block in split_tables(sec_lines):
            if kind == "table":
                if not block or is_divider(block[0]):
                    continue
                if title.startswith("Изменения"):
                    html.append(render_change_table(block, whitelist))
                else:
                    html.append(render_table(block, whitelist, tally))
            else:
                rendered = render_lines(block, whitelist,
                                        lead_first=title.startswith("Итог"))
                if rendered:
                    html.append(rendered)
        parts.append("\n".join(html))

    return h1, sprint, meta, tally, "\n\n".join(parts)


def render_tally(tally):
    """Светофор спринта: доли строк по статусам.

    Считаются строки, не SP (решение Д1): взвешивание по SP даёт «закрыли 80%
    спринта» при двух незакрытых Must.
    """
    total = sum(tally.values())
    if not total:
        return ""
    segs = [
        ("s-ok", tally["ok"], f"{tally['ok']} закрыто", f"100%: {tally['ok']}"),
        ("s-half", tally["half"], f"{tally['half']} в работе", f"50–99%: {tally['half']}"),
        ("s-low", tally["low"], str(tally["low"]), f"0–49%: {tally['low']}"),
        ("s-idle", tally["idle"], str(tally["idle"]),
         f"ACTIVITY / заблокировано: {tally['idle']}"),
    ]
    bar = "".join(
        f'<span class="{cls}" style="flex:{n}" title="{htmlmod.escape(tip)}">'
        f'{htmlmod.escape(label)}</span>'
        for cls, n, label, tip in segs if n)
    legend = "".join(
        f'<span><i style="background:{color}"></i>{text}</span>'
        for color, text in (("#d9ead3", "100% — закрыто"),
                            ("#fff2cc", "50–99% — в работе"),
                            ("#f4cccc", "0–49% — в работе"),
                            ("#eeeeee", "ACTIVITY / заблокировано")))
    return (f'<div class="tally"><div class="tally-bar" '
            f'aria-label="Готовность строк спринта, всего {total}">{bar}</div>'
            f'<div class="tally-legend">{legend}</div></div>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("-o", "--output")
    ap.add_argument("--link-whitelist", default="",
                    help="хосты через запятую; пусто — ссылки остаются текстом (О5)")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        sys.exit("нет файла: %s" % src)
    whitelist = tuple(h.strip().lower() for h in args.link_whitelist.split(",") if h.strip())

    h1, sprint, meta, tally, main_html = build(src.read_text(encoding="utf-8"), whitelist)

    css = (HERE / "sprint-report.css").read_text(encoding="utf-8")
    js = (HERE / "sprint-report.js").read_text(encoding="utf-8")
    js = (js.replace("__DOC_JSON__", json.dumps(src.name, ensure_ascii=False))
            .replace("__KEY_JSON__", json.dumps("sprint-result:" + sprint, ensure_ascii=False))
            .replace("__SPRINT_JSON__", json.dumps(sprint, ensure_ascii=False)))

    title = htmlmod.escape(h1)
    head, tail = h1.split("|", 1) if "|" in h1 else (h1, "")
    meta_html = "".join(
        "<span>%s: <b>%s</b></span>" % (htmlmod.escape(k), inline(v, whitelist))
        for k, v in meta.items())

    page = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{css}</style>
</head>
<body>

<div class="promptbox">
  <button type="button" id="finalBtn" class="finalbtn">Отчёт финальный</button>
  <button type="button" id="editBtn">Правки (0)</button>
  <p class="hint" id="hint"></p>
  <div class="panel" id="editPanel">
    <h4>Правки к отчёту</h4>
    <div id="editList"><p class="empty">Правок нет. Кликните строку таблицы или выделите текст.</p></div>
    <textarea id="promptOut" readonly placeholder="Промт соберётся здесь"></textarea>
    <button type="button" class="copybtn" id="copyBtn">Скопировать промт</button>
  </div>
</div>

<div class="rail">
  <button type="button" class="rail-tab" id="tocTab">Содержание</button>
  <button type="button" class="rail-tab edit-tab" id="editTab">Правки</button>
</div>
<nav class="drawer" id="tocDrawer"><h4>Содержание</h4><div id="tocList"></div></nav>
<aside class="drawer" id="editDrawer"><h4>Правки</h4><div id="editWalk"></div></aside>

<div class="layout">
<main>

<header class="doc-head">
  <h1>{head}{sep}</h1>
  <div class="meta">{meta_html}</div>
</header>

{tally}

{body}

<footer>
  <p class="anchors">Собрано из {src} · навык sprint-result</p>
  <p class="anchors">ревизия <span id="revOut" class="mono"></span></p>
</footer>

</main>
</div>

<script>
{js}</script>
</body>
</html>
""".format(title=title, css=css, js=js,
           head=htmlmod.escape(head.strip()),
           sep=(' <span class="sep">|</span> ' + htmlmod.escape(tail.strip())) if tail else "",
           meta_html=meta_html, tally=render_tally(tally), body=main_html,
           src=htmlmod.escape(src.name))

    out = Path(args.output) if args.output else src.with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    print("страница: %s (строк: %d)" % (out, sum(tally.values())))


if __name__ == "__main__":
    main()
