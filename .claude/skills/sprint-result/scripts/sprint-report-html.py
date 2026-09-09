#!/usr/bin/env python3
"""Собирает отчётную колоду спринта из ФАКТ-{sprint}.md.

    python3 sprint-report-html.py <путь-к-ФАКТ-{sprint}.md> [-o out.html]
                                  [--link-whitelist wiki.example,tracker.example]
                                  [--max-rows 6]

Выход — лента слайдов 1280×720 по эталонной колоде
(docs/reference/sprint-report-deck-reference.md). CSS и JS лежат рядом;
расхождение эталона и выхода — дефект экспортёра.

Что делает поверх markdown:
  1. Разделение на слайды: титул → HERO команды → слайды стримов → служебные.
  2. Сортировка строк по убыванию результата + подпись о ней (§7 эталона).
  3. Заливка строки целиком по шкале; стоп-маркеры 🛑/🚫 у нулей (§5).
  4. Ячейка комментария → список фактов + строка следующего шага (§6).
  5. Счётчики итогового слайда — по строкам всех стримов (§8, решение Д1).
  6. Разрез стрима, не влезающего в слайд, на «(продолжение)».
  7. Ступень лестницы (решение О2) уходит в подсказку ячейки: в .md она есть и
     проверяется гейтом 3, на слайде её нет — так в эталоне.
  8. Ссылки — только по вайтлисту (решение О5), иначе URL остаётся текстом.
"""
import argparse
import html as htmlmod
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

MAX_ROWS_PER_SLIDE = 6

NEXT_LABEL_RE = re.compile(
    r"^\s*(След\.?\s*шаг|Следующий шаг|Следующий спринт|След\.?\s*спринт|"
    r"В следующем спринте|В след\.?\s*спринте)\s*:\s*(.*)$", re.I)
UNC_RE = re.compile(r"`?(\[УТОЧНИТЬ[^\]]*\])`?")
URL_RE = re.compile(r"https?://[^\s<>()\"']*[^\s<>()\"'.,;:!?]")
IMG_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")
# «100%», «🛑 0%», «ACTIVITY», «заблокировано» — с необязательной ступенью после «·»
RESULT_RE = re.compile(r"^\s*([^·]+?)\s*(?:·\s*(.+))?$")
PERCENT_RE = re.compile(r"(\d{1,3})\s*%")

LEGEND = (
    '<div class="legend">'
    '<div class="pill green">выполнено-<br>100%</div>'
    '<div class="pill yellow">в работе<br>сделано от<br>50% до 99%</div>'
    '<div class="pill red">в работе<br>сделано до<br>50%</div>'
    "</div>")


# ---------- инлайн ----------

def inline(text, whitelist=()):
    esc = htmlmod.escape(text)
    esc = UNC_RE.sub(r'<mark class="unc">\1</mark>', esc)
    esc = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
                 lambda m: _link(m.group(2), m.group(1), whitelist), esc)
    esc = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", esc)
    esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
    return URL_RE.sub(lambda m: _link(m.group(0), m.group(0), whitelist), esc)


def _link(href, label, whitelist):
    host = re.sub(r"^https?://", "", href).split("/")[0].lower()
    if any(host == w or host.endswith("." + w) for w in whitelist):
        return ('<a href="%s" target="_blank" rel="noopener">%s</a>'
                % (htmlmod.escape(href, quote=True), label))
    return label


# ---------- разбор markdown ----------

def is_divider(cells):
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells if c)


def parse_blocks(lines):
    """Строки раздела → [('table', rows) | ('lines', [str])] в исходном порядке."""
    blocks, buf, table = [], [], []
    for line in lines:
        if line.strip().startswith("|"):
            if buf:
                blocks.append(("lines", buf)); buf = []
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not is_divider(cells):
                table.append(cells)
        else:
            if table:
                blocks.append(("table", table)); table = []
            buf.append(line)
    if buf:
        blocks.append(("lines", buf))
    if table:
        blocks.append(("table", table))
    return blocks


def parse_sections(body):
    """Тело → дерево: [(уровень, заголовок, [строки])] для ## и ###."""
    out, level, title, buf = [], None, None, []
    for line in body.splitlines():
        m = re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            if title is not None or buf:
                out.append((level, title, buf))
            level, title, buf = len(m.group(1)), m.group(2).strip(), []
        else:
            buf.append(line)
    out.append((level, title, buf))
    return [s for s in out if s[1] is not None]


# ---------- статус строки ----------

def parse_result(cell):
    """Ячейка результата → (что показать, ступень, класс, ключ сортировки)."""
    m = RESULT_RE.match(cell.strip())
    shown = (m.group(1) if m else cell).strip()
    step = (m.group(2) or "").strip() if m else ""
    low = shown.lower()
    if low.startswith("activity"):
        return shown, step, "", -2          # вне шкалы, в счётчики не идёт
    pm = PERCENT_RE.search(shown)
    if pm:
        n = int(pm.group(1))
        cls = "stat-green" if n >= 100 else "stat-yellow" if n >= 50 else "stat-red"
        return shown, step, cls, n
    if "заблок" in low:
        return shown, step, "stat-red", -1
    return shown, step, "", -2


# ---------- ячейки ----------

def render_task(cell, whitelist):
    """`[BE] BE-1: действие` → роль отдельной строкой над названием."""
    m = re.match(r"\s*(\[[^\]]+\][^:]*?):\s*(.+)", cell)
    if m:
        return ('<td class="task"><span class="role">%s</span>%s</td>'
                % (htmlmod.escape(m.group(1).strip()), inline(m.group(2), whitelist)))
    return '<td class="task">%s</td>' % inline(cell, whitelist)


def render_comment(cell, whitelist):
    """Список фактов + отдельная строка следующего шага (§6 эталона)."""
    items, nexts = [], []
    for chunk in re.split(r"<br\s*/?>", cell):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = NEXT_LABEL_RE.match(chunk)
        if m:
            nexts.append((m.group(1).strip(), m.group(2).strip()))
            continue
        items.append(re.sub(r"^[-*]\s+", "", chunk))
    out = ""
    if items:
        out += "<ul>%s</ul>" % "".join(
            "<li>%s</li>" % inline(i, whitelist) for i in items)
    for label, value in nexts:
        out += ('<div class="next">%s: <span class="next-item">%s</span></div>'
                % (htmlmod.escape(label), inline(value, whitelist)))
    return "<td>%s</td>" % out


def render_rows(rows, whitelist, tally):
    """Строки стрима: разбор, подсчёт статусов, сортировка по убыванию."""
    header = rows[0]
    idx = {name.strip().lower(): i for i, name in enumerate(header)}
    i_task = idx.get("задачи", idx.get("задача", 0))
    i_comment = idx.get("комментарий", 1)
    i_res = idx.get("результат", 2)

    prepared = []
    for row in rows[1:]:
        if not any(row) or i_res >= len(row):
            continue
        shown, step, cls, key = parse_result(row[i_res])
        if cls == "stat-green":
            tally["green"] += 1
        elif cls == "stat-yellow":
            tally["yellow"] += 1
        elif cls == "stat-red":
            tally["red"] += 1
        cells = (render_task(row[i_task] if i_task < len(row) else "", whitelist)
                 + render_comment(row[i_comment] if i_comment < len(row) else "", whitelist)
                 + '<td class="result"%s>%s</td>'
                 % ((' title="%s"' % htmlmod.escape(step, quote=True)) if step else "",
                    htmlmod.escape(shown)))
        prepared.append((key, '<tr class="row %s">%s</tr>' % (cls, cells)))

    prepared.sort(key=lambda p: -p[0])
    return [html for _, html in prepared]


def table_shell(row_html):
    return ('<table class="rep">'
            '<colgroup><col class="c1"><col class="c2"><col class="c3"></colgroup>'
            "<thead><tr><th>Задачи</th><th>Комментарий</th><th>Результат</th></tr></thead>"
            "<tbody>%s</tbody></table>" % "".join(row_html))


# ---------- слайды ----------

class Deck:
    def __init__(self):
        self.slides = []

    def add(self, cls, body):
        n = len(self.slides) + 1
        self.slides.append(
            '<section class="slide%s" id="slide-%d">%s'
            '<div class="slide-num">%d</div></section>'
            % ((" " + cls) if cls else "", n, body, n))

    def html(self):
        return "\n".join(self.slides)


def parse_verdict(sec_lines):
    """`**Вердикт по Sprint Goal:** состояние` + следующий абзац-доказательство.

    Состояние уходит в подзаголовок слайда, доказательство — в подсказку: на
    слайде эталона места под него нет, но гейт 4 требует, чтобы оно было.
    """
    for i, line in enumerate(sec_lines):
        m = re.search(r"\*\*Вердикт по Sprint Goal:?\*\*\s*:?\s*(.*)", line)
        if not m:
            continue
        proof = []
        for nxt in sec_lines[i + 1:]:
            s = nxt.strip()
            if not s or s.startswith("|") or s.startswith("#"):
                break
            proof.append(s)
        return m.group(1).strip(), " ".join(proof)
    return "", ""


def stream_slides(deck, title, verdict, rows, sprint, whitelist, tally, max_rows):
    row_html = render_rows(rows, whitelist, tally) if rows else []
    chunks = [row_html[i:i + max_rows] for i in range(0, len(row_html), max_rows)] or [[]]
    for n, chunk in enumerate(chunks):
        name = title if n == 0 else "%s (продолжение)" % title
        sub = 'Спринт %s · стрим "%s"' % (htmlmod.escape(sprint), htmlmod.escape(title))
        state, proof = verdict
        if state and n == 0:
            sub = ('<span%s>%s · Sprint Goal: %s</span>'
                   % ((' title="%s"' % htmlmod.escape(proof, quote=True)) if proof else "",
                      sub, inline(state, whitelist)))
        deck.add("", '<h1 class="slide-title">%s</h1><div class="slide-sub">%s</div>%s%s'
                     '<p class="sort-note">Сортировка: по убыванию результата</p>'
                     % (htmlmod.escape(name), sub, LEGEND, table_shell(chunk)))


def render_list(lines, whitelist, cls="", cap_sep=" — "):
    items = [l.strip()[2:] for l in lines if l.strip().startswith("- ")]
    if not items:
        return ""
    out = []
    for item in items:
        if cap_sep and cap_sep in item:
            head, tail = item.split(cap_sep, 1)
            out.append("<li>%s<span class=\"cap\"> %s %s</span></li>"
                       % (inline(head, whitelist), cap_sep.strip(), inline(tail, whitelist)))
        else:
            out.append("<li>%s</li>" % inline(item, whitelist))
    return '<ul class="%s">%s</ul>' % (cls, "".join(out))


def paragraphs(lines, whitelist):
    out, para = [], []
    for raw in lines:
        line = raw.strip()
        if not line or line == "---" or line.startswith("> ") or line.startswith("-"):
            if para:
                out.append("<p>%s</p>" % inline(" ".join(para), whitelist)); para = []
            continue
        para.append(line)
    if para:
        out.append("<p>%s</p>" % inline(" ".join(para), whitelist))
    return "".join(out)


def metrics_slide(deck, cards, sprint, whitelist, base):
    """Карточки метрик. Файла картинки ещё нет — рисуем место под него с
    ожидаемым путём, а не битую ссылку: PO прикладывает скриншот отдельно (О4)."""
    if not cards:
        return
    body = []
    for title, src, alt, text in cards:
        exists = bool(src) and (src.startswith("http") or (base / src).exists())
        shot = ('<img src="%s" alt="%s">' % (htmlmod.escape(src, quote=True), htmlmod.escape(alt))
                if exists else
                '<div class="noshot">Скриншот прикладывает PO%s</div>'
                % (("<br>" + htmlmod.escape(src)) if src else ""))
        body.append('<div class="metric-card"><h3>%s</h3>%s<p>%s</p></div>'
                    % (htmlmod.escape(title), shot, inline(text, whitelist)))
    deck.add("", '<h1 class="slide-title">Метрики</h1>'
                 '<div class="slide-sub">Спринт %s · процессные метрики</div>'
                 '<div class="metrics-grid">%s</div>'
                 % (htmlmod.escape(sprint), "".join(body)))


def summary_slide(deck, sprint, tally, streams, risks, carry, whitelist):
    total = tally["green"] + tally["yellow"] + tally["red"]
    kpi = "".join(
        '<div class="kpi %s"><div class="n">%d</div><div class="label">%s</div></div>'
        % (cls, tally[key], label)
        for cls, key, label in (("green", "green", "завершено на 100%"),
                                ("yellow", "yellow", "в работе, 50–99%"),
                                ("red", "red", "до 50% / заблокировано")))
    blocks = '<div class="summary-grid">%s</div>' % kpi
    if risks:
        blocks += ('<div class="risks"><h2>Ключевые риски и блокеры</h2>%s</div>'
                   % render_list(risks, whitelist, cap_sep=""))
    if carry:
        blocks += ('<div class="risks"><h2>Переносим в следующий спринт</h2>%s</div>'
                   % render_list(carry, whitelist, cap_sep=""))
    deck.add("", '<h1 class="slide-title">Итоги спринта %s</h1>'
                 '<div class="slide-sub">%d инициатив по %d стримам</div>%s'
                 % (htmlmod.escape(sprint), total, streams, blocks))


# ---------- сборка ----------

def build(md_text, whitelist, max_rows, base=Path(".")):
    lines = md_text.splitlines()
    h1 = next((l[2:].strip() for l in lines if l.startswith("# ")), "ФАКТ")
    sprint = h1.split("|")[-1].strip() if "|" in h1 else h1
    body = "\n".join(lines[lines.index("# " + h1) + 1:])

    meta = {}
    for key in ("Период", "Ответственный", "Статус", "Версия", "План"):
        m = re.search(r"\*\*%s:?\*\*\s*([^*\n·]+)" % key, body)
        if m:
            meta[key] = m.group(1).strip(" ·")

    deck = Deck()
    tally = {"green": 0, "yellow": 0, "red": 0}
    sections = parse_sections(body)
    teams = [t for lvl, t, _ in sections if lvl == 2 and t.startswith("КОМАНДА")]

    # титул
    kicker = ("Команды: " + " · ".join(t.split(":", 1)[1].split("—")[0].strip()
                                       for t in teams)) if teams else "Отчёт по спринту"
    meta_html = "<br>".join("%s: %s" % (htmlmod.escape(k), inline(v, whitelist))
                            for k, v in meta.items())
    deck.add("title-slide",
             '<div class="kicker">%s</div><h1>%s</h1><div class="author">%s</div>'
             '<div class="meta">%s</div>'
             % (htmlmod.escape(kicker), htmlmod.escape(h1),
                htmlmod.escape(meta.get("Ответственный", "")), meta_html))

    metric_cards, risks, carry, streams = [], [], [], 0
    ctx = None                       # текущий служебный раздел ## для вложенных ###

    for level, title, sec_lines in sections:
        blocks = parse_blocks(sec_lines)
        tables = [b for kind, b in blocks if kind == "table"]
        plain = [l for kind, b in blocks if kind == "lines" for l in b]

        if level == 2 and title.startswith("КОМАНДА"):
            ctx = None
            name = title.split(":", 1)[1].strip() if ":" in title else title
            head, _, sub = name.partition("—")
            deck.add("hero-slide",
                     '<div class="hero-line"></div><h1>%s</h1><div class="hero-sub">%s</div>'
                     % (htmlmod.escape(head.strip()), htmlmod.escape(sub.strip())))
            continue

        if title.startswith("СТРИМ") or (level == 3 and ctx is None and tables):
            streams += 1
            name = title.split(":", 1)[1].strip() if ":" in title else title
            stream_slides(deck, name, parse_verdict(sec_lines),
                          tables[0] if tables else [], sprint, whitelist, tally, max_rows)
            continue

        if level == 2:
            ctx = title
            if title.startswith("Изменения"):
                cards = []
                for row in (tables[0][1:] if tables else []):
                    if not any(row):
                        continue
                    who = row[0] if row else ""
                    ba = row[1] if len(row) > 1 else ""
                    res = row[2] if len(row) > 2 else ""
                    m = re.search(r"БЫЛО\s*:?\s*(.*?)\s*СТАЛО\s*:?\s*(.*)", ba, re.S | re.I)
                    was, now = (m.group(1), m.group(2)) if m else (ba, "")
                    cards.append(
                        '<div class="change"><div class="who">Затронуто: %s</div>'
                        '<div class="ba"><div><b>Было</b>%s</div><div><b>Стало</b>%s</div></div>'
                        '<p class="out">%s</p></div>'
                        % (inline(who, whitelist), inline(was.strip(" .;"), whitelist),
                           inline(now.strip(), whitelist), inline(res, whitelist)))
                if cards:
                    deck.add("", '<h1 class="slide-title">Изменения в процессе спринта</h1>'
                                 '<div class="slide-sub">Спринт %s · договорённости</div>%s'
                                 % (htmlmod.escape(sprint), "".join(cards)))
            elif title.startswith("Демо"):
                lst = render_list(plain, whitelist, cls="demo")
                if lst:
                    deck.add("", '<h1 class="slide-title">Демо</h1>'
                                 '<div class="slide-sub">Спринт %s · показываем руками</div>%s'
                                 % (htmlmod.escape(sprint), lst))
            continue

        if level == 3 and ctx and ctx.startswith("Метрик"):
            src, alt, text = "", "", []
            for raw in plain:
                im = IMG_RE.match(raw.strip())
                if im:
                    alt, src = im.group(1), im.group(2)
                elif raw.strip() and raw.strip() != "---":
                    text.append(raw.strip())
            metric_cards.append((title, src, alt, " ".join(text)))
        elif level == 3 and ctx and ctx.startswith("Итог"):
            target = carry if title.startswith("Перенос") else risks
            target.extend(plain)

    metrics_slide(deck, metric_cards, sprint, whitelist, base)
    summary_slide(deck, sprint, tally, streams, risks, carry, whitelist)
    return h1, sprint, deck, tally


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("-o", "--output")
    ap.add_argument("--link-whitelist", default="",
                    help="хосты через запятую; пусто — ссылки остаются текстом (О5)")
    ap.add_argument("--max-rows", type=int, default=MAX_ROWS_PER_SLIDE,
                    help="строк на слайд, дальше стрим режется на «(продолжение)»")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        sys.exit("нет файла: %s" % src)
    whitelist = tuple(h.strip().lower() for h in args.link_whitelist.split(",") if h.strip())

    h1, sprint, deck, tally = build(src.read_text(encoding="utf-8"), whitelist,
                                    args.max_rows, src.resolve().parent)

    css = (HERE / "sprint-report.css").read_text(encoding="utf-8")
    js = (HERE / "sprint-report.js").read_text(encoding="utf-8")
    js = (js.replace("__DOC_JSON__", json.dumps(src.name, ensure_ascii=False))
            .replace("__KEY_JSON__", json.dumps("sprint-result:" + sprint, ensure_ascii=False))
            .replace("__SPRINT_JSON__", json.dumps(sprint, ensure_ascii=False)))

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
    <div id="editList"><p class="empty">Правок нет.</p></div>
    <textarea id="promptOut" readonly placeholder="Промт соберётся здесь"></textarea>
    <button type="button" class="copybtn" id="copyBtn">Скопировать промт</button>
  </div>
</div>

<div class="rail">
  <button type="button" class="rail-tab" id="tocTab">Слайды</button>
  <button type="button" class="rail-tab edit-tab" id="editTab">Правки</button>
</div>
<nav class="drawer" id="tocDrawer"><h4>Слайды</h4><div id="tocList"></div></nav>
<aside class="drawer" id="editDrawer"><h4>Правки</h4><div id="editWalk"></div></aside>

<div class="deck">
{slides}
</div>

<script>
{js}</script>
</body>
</html>
""".format(title=htmlmod.escape(h1), css=css, js=js, slides=deck.html())

    out = Path(args.output) if args.output else src.with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    print("колода: %s (слайдов: %d, строк: %d)"
          % (out, len(deck.slides), tally["green"] + tally["yellow"] + tally["red"]))


if __name__ == "__main__":
    main()
