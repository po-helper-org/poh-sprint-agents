"""Страница статуса спринта: модель (model.py) → самодостаточный HTML под печать в PDF.

Визуальный язык — слайды /morning (poh-morning-status): тёмная тема, виджеты с
заголовком капсом и счётчиком, KPI-плитки. Лист 16:9, одна команда — один лист;
при нескольких командах первым идёт сводный лист. Цвета бакетов — те же, что на
странице actual-sprint, со ступенями под тёмный фон.
"""
from html import escape

from model import BUCKETS, STALE_DAYS, ddmm, plural

W, H = 1280, 720
MAX_ATTENTION = 6
MAX_SUMMARY_TOP = 4
MAX_EPICS = 9

BUCKET_NAMES = {'open': 'Открыто', 'blocked': 'Заблокировано', 'progress': 'В работе',
                'testing': 'Тестирование', 'review': 'Ревью', 'done': 'Готово'}
# шесть бакетов actual-sprint (status_mapping.md), светлее под фон #141518;
# проверено validate_palette.js: контраст ≥ 3:1, соседние пары различимы
BUCKET_COLORS = {'open': '#8b8f96', 'blocked': '#e5484d', 'progress': '#4c8dff',
                 'testing': '#e0c238', 'review': '#f07a3a', 'done': '#30a46c'}

CSS = """
@page { size: %(w)dpx %(h)dpx; margin: 0; }
:root {
  --bg:#0f1012; --card:#141518; --soft:#1a1b1f; --line:#2a2b2f;
  --ink:#e6e7ea; --ink2:#b4b7bd; --muted:#8b8f96;
  --red:#e5484d; --green:#30a46c; --amber:#e0a538; --amber-bg:#2a2210; --blue:#4c8dff;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { background: var(--bg); color: var(--ink);
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font: 14px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
.sheet { width: %(w)dpx; height: %(h)dpx; padding: 34px 44px 22px; display: flex; flex-direction: column;
  gap: 16px; overflow: hidden; page-break-after: always; break-after: page; position: relative; }
.sheet:last-child { page-break-after: auto; break-after: auto; }
.id { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; color: var(--ink2); white-space: nowrap; }
.num { font-variant-numeric: tabular-nums; }

/* шапка */
.head { display: flex; align-items: flex-end; justify-content: space-between;
  border-bottom: 1px solid var(--line); padding-bottom: 12px; }
.eyebrow { font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; }
.title { font-size: 28px; font-weight: 700; letter-spacing: -.01em; }
.title .sprint { color: var(--ink2); font-weight: 600; }
.when { text-align: right; color: var(--ink2); font-size: 14px; }
.when b { color: var(--ink); font-size: 18px; font-weight: 600; display: block; }
.when .late { color: var(--red); }
.banner { background: var(--amber-bg); color: var(--amber); border: 1px solid #4a3a14; border-radius: 8px;
  padding: 7px 12px; font-size: 13px; }

/* KPI */
.kpis { display: grid; grid-template-columns: repeat(6, minmax(0,1fr)); gap: 12px; }
.kpi { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 11px 14px 12px; }
.kpi .k { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.kpi .v { font-size: 30px; font-weight: 700; margin-top: 2px; line-height: 1.1; }
.kpi .v small { font-size: 16px; color: var(--ink2); font-weight: 500; }
.kpi .s { font-size: 12px; color: var(--ink2); margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi.bad .v { color: var(--red); }
.kpi.good .v { color: var(--green); }
.kpi.warn .v { color: var(--amber); }
.track { height: 6px; background: var(--soft); border-radius: 3px; margin-top: 8px; overflow: hidden; }
.track i { display: block; height: 100%%; background: var(--green); border-radius: 3px; }

/* виджеты */
.body { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0,1.05fr) minmax(0,1fr) minmax(0,1fr); gap: 12px; }
.col { display: flex; flex-direction: column; gap: 12px; min-height: 0; }
.w { background: var(--card); border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
  display: flex; flex-direction: column; min-height: 0; }
.w.grow { flex: 1; }
.wh { display: flex; justify-content: space-between; align-items: baseline; padding: 10px 14px;
  border-bottom: 1px solid var(--line); font-size: 12px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--ink2); font-weight: 600; }
.wh span { color: var(--muted); font-weight: 500; letter-spacing: .02em; text-transform: none; }
.wb { padding: 10px 14px; }
.empty { color: var(--muted); padding: 14px; font-size: 13px; }
.more { color: var(--muted); font-size: 12px; padding: 7px 14px; border-top: 1px solid var(--line); margin-top: auto; }

/* строки «Внимание» */
.row { padding: 7px 14px; border-bottom: 1px solid var(--line); }
.row:last-child { border-bottom: 0; }
.r1 { display: flex; gap: 8px; align-items: baseline; min-width: 0; }
.r1 .t { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.r2 { font-size: 12px; color: var(--muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tag { font-size: 10px; font-weight: 700; letter-spacing: .06em; border-radius: 4px; padding: 1px 5px;
  flex: none; position: relative; top: -1px; }
.tag.blocked { color: var(--red); background: #2d1415; }
.tag.stale { color: var(--amber); background: var(--amber-bg); }
.tag.risk { color: var(--ink2); background: var(--soft); border: 1px solid var(--line); }
.days { flex: none; font-size: 12px; color: var(--ink2); }
.days.hot { color: var(--red); font-weight: 600; }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%%; margin-right: 5px; position: relative; top: -1px; }

/* эпики */
.epic { padding: 7px 14px 8px; border-bottom: 1px solid var(--line); }
.epic:last-child { border-bottom: 0; }
.e1 { display: flex; gap: 8px; align-items: baseline; }
.e1 .t { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.e1 .n { color: var(--ink2); font-size: 13px; }
.e1 .b { color: var(--red); font-size: 12px; }
.bar { display: flex; gap: 2px; height: 6px; margin-top: 6px; }
.bar i { display: block; height: 100%%; border-radius: 2px; }

/* статусы */
.stack { display: flex; gap: 2px; height: 14px; }
.stack i { display: block; height: 100%%; border-radius: 3px; }
.legend { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px 10px; margin-top: 10px; font-size: 12px; color: var(--ink2); }
.legend b { color: var(--ink); font-weight: 600; margin-left: 2px; }
.legend .zero { color: var(--muted); }
.legend .zero b { color: var(--muted); font-weight: 400; }

/* график */
svg text { font-family: inherit; }
.chartlegend { display: flex; gap: 16px; font-size: 12px; color: var(--ink2); padding: 0 14px 10px; }
.chartlegend i { display: inline-block; width: 16px; height: 0; border-top: 2px solid; vertical-align: middle; margin-right: 6px; }

/* сводный лист */
table { width: 100%%; border-collapse: collapse; }
th { white-space: nowrap; text-align: left; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted);
  font-weight: 600; padding: 10px 14px; border-bottom: 1px solid var(--line); }
td { padding: 12px 14px; border-bottom: 1px solid var(--line); vertical-align: middle; }
tr:last-child td { border-bottom: 0; }
td.r, th.r { text-align: right; }
.teamname { font-size: 17px; font-weight: 600; }
.sub { font-size: 12px; color: var(--muted); }

.foot { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); }
.foot .old { color: var(--amber); }
""" % {'w': W, 'h': H}


def e(text):
    return escape(str(text), quote=True)


def days_short(n):
    return '<1 д' if n == 0 else f'{n} д'


# ------------------------------------------------------------------ блоки

def head(eyebrow, title_html, when_html, page):
    return (f'<div class="head"><div><div class="eyebrow">{e(eyebrow)} · {page}</div>'
            f'<div class="title">{title_html}</div></div>'
            f'<div class="when">{when_html}</div></div>')


def when_parts(m):
    """(главное, пояснение, просрочен ли) — для шапки листа и строки сводки."""
    p = m['pace']
    if not p['started']:
        return f'старт {ddmm(p["start"])}', f'до {ddmm(p["end"])}', False
    if p['overdue']:
        return f'срок истёк {ddmm(p["end"])}', 'в JIRA спринт не закрыт', True
    left = p['left']
    tail = (f'осталось {left} раб. {plural(left, "день", "дня", "дней")}' if left
            else 'последний день')
    return f'день {p["workday"]} из {p["workdays"]}', f'до {ddmm(p["end"])} · {tail}', False


def when_block(m):
    main, sub, late = when_parts(m)
    return f'<b{" class=late" if late else ""}>{main}</b>{sub}'


def pace_kpi(m):
    p = m['pace']
    gap = p['gap']
    if not p['started']:
        return 'kpi', '—', 'спринт не начался'
    if gap > 0:
        return 'kpi bad', f'−{gap}', 'задач отстаём от идеала'
    if gap < 0:
        return 'kpi good', f'+{-gap}', 'задач впереди идеала'
    return 'kpi good', '0', 'идём по идеальному темпу'


def kpis(m):
    p = m['pace']
    pct = round(100 * p['closed'] / p['scope']) if p['scope'] else 0
    cls, pace_v, pace_s = pace_kpi(m)
    if p['dClosed'] is None:
        day_v, day_s = '—', 'первый день спринта'
    else:
        day_v = f'+{p["dClosed"]}' if p['dClosed'] > 0 else '0'
        ds = p['dScope']
        day_s = 'закрыто' + (f' · объём {"+" if ds > 0 else ""}{ds}' if ds else ' · объём тот же')
    nb, ns, nr = len(m['blocked']), len(m['stale']), len(m['risks'])
    tiles = [
        ('kpi', 'Готово', f'{p["closed"]}<small> / {p["scope"]}</small>',
         f'{pct}% задач с подзадачами<div class="track"><i style="width:{pct}%"></i></div>'),
        (cls, 'Темп', pace_v, pace_s),
        ('kpi', 'За сутки', day_v, day_s),
        ('kpi bad' if nb else 'kpi', 'Блокеры', str(nb), 'в статусах ожидания'),
        ('kpi warn' if ns else 'kpi', 'Без движения', str(ns), f'статус не менялся > {STALE_DAYS} дн.'),
        ('kpi warn' if nr else 'kpi', 'Зона риска', str(nr), 'в работе дольше медианы'),
    ]
    return '<div class="kpis">' + ''.join(
        f'<div class="{c}"><div class="k">{k}</div><div class="v num">{v}</div><div class="s">{s}</div></div>'
        for c, k, v, s in tiles) + '</div>'


def burndown_svg(m, width=390, height=196):
    p = m['pace']
    days, ideal = p['days'], p['ideal']
    pad_l, pad_r, pad_t, pad_b = 30, 44, 12, 22
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    top = max([d['scope'] for d in days] + [1])
    n = len(days)
    x = lambda i: pad_l + (iw * i / (n - 1) if n > 1 else iw / 2)  # noqa: E731
    y = lambda v: pad_t + ih * (1 - v / top)  # noqa: E731
    step = iw / (n - 1) if n > 1 else iw
    parts = []
    for i, d in enumerate(days):  # выходные — фоном, как на странице, в пределах оси
        if d['weekend']:
            x0, x1 = max(pad_l, x(i) - step / 2), min(pad_l + iw, x(i) + step / 2)
            parts.append(f'<rect x="{x0:.1f}" y="{pad_t}" width="{x1 - x0:.1f}" '
                         f'height="{ih}" fill="#1a1b1f"/>')
    for v in (0, round(top / 2), top):
        parts.append(f'<line x1="{pad_l}" x2="{pad_l + iw}" y1="{y(v):.1f}" y2="{y(v):.1f}" '
                     f'stroke="#2a2b2f" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" text-anchor="end" '
                     f'font-size="11" fill="#8b8f96">{v}</text>')
    first = p['first']
    parts.append(f'<polyline points="{x(first):.1f},{y(ideal[first]):.1f} {x(n - 1):.1f},{y(0):.1f}" '
                 f'fill="none" stroke="#8b8f96" stroke-width="1.5" stroke-dasharray="4 4"/>')
    ti = p['todayIndex']
    if ti is not None:
        pts = ' '.join(f'{x(i):.1f},{y(days[i]["remaining"]):.1f}'
                       for i in range(min(first, ti), ti + 1))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="#4c8dff" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
        cx, cy = x(ti), y(days[ti]['remaining'])
        parts.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{pad_t}" y2="{pad_t + ih}" '
                     f'stroke="#4c8dff" stroke-opacity=".35" stroke-dasharray="2 3"/>')
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.5" fill="#4c8dff" '
                     f'stroke="#141518" stroke-width="2"/>')
        anchor, dx = ('end', -9) if ti > n * 0.6 else ('start', 9)
        parts.append(f'<text x="{cx + dx:.1f}" y="{cy - 8:.1f}" text-anchor="{anchor}" font-size="12" '
                     f'font-weight="600" fill="#e6e7ea">{days[ti]["remaining"]} осталось</text>')
        iy = y(ideal[ti] or 0)
        if ideal[ti] is not None and abs(iy - cy) > 14:
            ly = iy + 14 if iy + 14 < pad_t + ih - 4 else iy - 7  # у оси — над точкой, не на датах
            parts.append(f'<circle cx="{cx:.1f}" cy="{iy:.1f}" r="3" fill="#8b8f96"/>')
            parts.append(f'<text x="{cx + dx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                         f'font-size="11" fill="#8b8f96">идеал {ideal[ti]}</text>')
    for i, anchor in ((0, 'start'), (n - 1, 'end')):
        parts.append(f'<text x="{x(i):.1f}" y="{height - 5}" text-anchor="{anchor}" font-size="11" '
                     f'fill="#8b8f96">{ddmm(days[i]["date"])}</text>')
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'role="img" aria-label="Burndown: остаток задач по дням">{"".join(parts)}</svg>')


def burndown_widget(m):
    p = m['pace']
    sub = f'объём {p["scope"]} · остаток {p["remaining"]}'
    return (f'<div class="w"><div class="wh">Burndown<span>{sub}</span></div>'
            f'<div class="wb" style="padding-bottom:4px">{burndown_svg(m)}</div>'
            f'<div class="chartlegend"><span><i style="border-color:#4c8dff"></i>остаток</span>'
            f'<span><i style="border-color:#8b8f96;border-top-style:dashed"></i>идеальный темп</span>'
            f'<span style="margin-left:auto;color:#8b8f96">выходные — фоном</span></div></div>')


def status_widget(m):
    split = m['split']
    total = sum(split.values())
    bars = ''.join(f'<i style="flex:{split[b]};background:{BUCKET_COLORS[b]}"></i>'
                   for b in BUCKETS if split.get(b))
    legend = ''.join(
        f'<span class="{"" if split.get(b) else "zero"}"><span class="dot" '
        f'style="background:{BUCKET_COLORS[b]}"></span>{BUCKET_NAMES[b]}<b class="num">{split.get(b, 0)}</b></span>'
        for b in BUCKETS)
    return (f'<div class="w grow"><div class="wh">Статусы<span>{total} задач</span></div>'
            f'<div class="wb"><div class="stack">{bars}</div><div class="legend">{legend}</div></div></div>')


SUMMARY_PACE = {'задач отстаём от идеала': 'отстаём', 'задач впереди идеала': 'впереди',
                'идём по идеальному темпу': 'по плану'}

KIND_TAG = {'blocked': 'БЛОК', 'stale': 'СТОИТ', 'risk': 'РИСК'}


def attention_row(r):
    days = r['days']
    if r['kind'] == 'risk':
        when, hot = f'в работе {days_short(days)}', False
    else:
        when = days_short(days) if days is not None else '—'
        hot = days is not None and days > STALE_DAYS
    return (f'<div class="row"><div class="r1"><span class="tag {r["kind"]}">{KIND_TAG[r["kind"]]}</span>'
            f'<span class="id">{e(r["key"])}</span><span class="t">{e(r["title"])}</span>'
            f'<span class="days num{" hot" if hot else ""}">{when}</span></div>'
            f'<div class="r2"><span class="dot" style="background:{BUCKET_COLORS[r["bucket"]]}"></span>'
            f'{e(r["status"])}{" · " + e(r["priority"]) if r.get("priority") else ""} · {e(r["who"])}</div></div>')


def attention_widget(m):
    rows = m['attention']
    head_ = f'блокеров {len(m["blocked"])} · стоит {len(m["stale"])} · риск {len(m["risks"])}'
    if not rows:
        return (f'<div class="w grow"><div class="wh">Внимание<span>{head_}</span></div>'
                f'<div class="empty">Блокеров и зависших задач нет.</div></div>')
    out = [attention_row(r) for r in rows[:MAX_ATTENTION]]
    more = len(rows) - MAX_ATTENTION
    tail = f'<div class="more">ещё {more} — в отчёте sprint-report.html</div>' if more > 0 else ''
    return (f'<div class="w grow"><div class="wh">Внимание<span>{head_}</span></div>'
            f'{"".join(out)}{tail}</div>')


def epics_widget(m):
    epics = m['epics']
    if not epics:
        return ('<div class="w grow"><div class="wh">Эпики</div>'
                '<div class="empty">В спринте нет историй с эпиками.</div></div>')
    out = []
    for ep in epics[:MAX_EPICS]:
        c = ep['counts']
        bar = ''.join(f'<i style="flex:{c[b]};background:{BUCKET_COLORS[b]}"></i>' for b in BUCKETS if c[b])
        blk = f'<span class="b">блок {c["blocked"]}</span>' if c['blocked'] else ''
        out.append(f'<div class="epic"><div class="e1"><span class="t">{e(ep["title"])}</span>{blk}'
                   f'<span class="n num">{ep["done"]}/{ep["total"]}</span></div>'
                   f'<div class="bar">{bar}</div></div>')
    more = len(epics) - MAX_EPICS
    tail = f'<div class="more">ещё {more} эпиков — в отчёте sprint-report.html</div>' if more > 0 else ''
    done = sum(ep['done'] for ep in epics)
    total = sum(ep['total'] for ep in epics)
    return (f'<div class="w grow"><div class="wh">Эпики<span>готово {done} из {total}</span></div>'
            f'{"".join(out)}{tail}</div>')


def footer(models, now, max_age_h):
    stamps = [m['collected'] for m in models if m['collected']]
    oldest = min(stamps) if stamps else None
    left = f'Данные JIRA на {oldest.strftime("%d.%m.%Y %H:%M")}' if oldest else 'Данные JIRA'
    warnings = sum(len(m['warnings']) for m in models)
    if warnings:
        left += f' · предупреждений сбора {warnings}'
    if oldest and now and oldest.tzinfo and (now - oldest).total_seconds() > max_age_h * 3600:
        hours = int((now - oldest).total_seconds() // 3600)
        left = f'<span class="old">⚠ {left} — данные старше {hours} ч</span>'
    collectors = ', '.join(sorted({m['collector'] for m in models}))
    return (f'<div class="foot"><span>{left}</span>'
            f'<span>сборщик {e(collectors)} · подробности — sprint-report.html</span></div>')


def team_sheet(m, page, banner, foot):
    title = f'{e(m["team"])} <span class="sprint">· {e(m["sprint"])}</span>'
    return (f'<section class="sheet">{head("Статус спринта", title, when_block(m), page)}'
            f'{banner}{kpis(m)}'
            f'<div class="body"><div class="col">{burndown_widget(m)}{status_widget(m)}</div>'
            f'<div class="col">{attention_widget(m)}</div>'
            f'<div class="col">{epics_widget(m)}</div></div>{foot}</section>')


def summary_sheet(models, page, banner, foot, report_date):
    rows = []
    for m in models:
        p = m['pace']
        pct = round(100 * p['closed'] / p['scope']) if p['scope'] else 0
        _, pace_v, pace_s = pace_kpi(m)
        pace_color = 'var(--red)' if p['gap'] > 0 else 'var(--green)' if p['started'] else 'var(--muted)'
        split = m['split']
        bar = ''.join(f'<i style="flex:{split[b]};background:{BUCKET_COLORS[b]}"></i>'
                      for b in BUCKETS if split.get(b))
        d = p['dClosed']
        rows.append(
            f'<tr><td><div class="teamname">{e(m["team"])}</div><div class="sub">{e(m["sprint"])} · '
            f'{when_parts(m)[0]} · {when_parts(m)[1].split(" · ")[0]}</div></td>'
            f'<td style="width:260px"><div class="num" style="font-size:15px">{p["closed"]} / {p["scope"]} '
            f'<span class="sub">· {pct}%</span></div><div class="stack" style="height:8px;margin-top:6px">{bar}</div></td>'
            f'<td class="r num" style="color:{pace_color};font-size:17px;font-weight:600">{pace_v}'
            f'<div class="sub" style="font-weight:400">{SUMMARY_PACE.get(pace_s, pace_s)}</div></td>'
            f'<td class="r num" style="font-size:17px">{"—" if d is None else ("+" + str(d) if d > 0 else "0")}</td>'
            f'<td class="r num" style="font-size:17px;color:{"var(--red)" if m["blocked"] else "var(--ink)"}">{len(m["blocked"])}</td>'
            f'<td class="r num" style="font-size:17px;color:{"var(--amber)" if m["stale"] else "var(--ink)"}">{len(m["stale"])}</td>'
            f'<td class="r num" style="font-size:17px">{len(m["risks"])}</td></tr>')
    table = ('<div class="w"><table><tr><th>Команда</th><th>Готово</th><th class="r">Темп</th>'
             '<th class="r">За сутки</th><th class="r">Блокеры</th><th class="r">Без движения</th>'
             '<th class="r">Зона риска</th></tr>' + ''.join(rows) + '</table></div>')
    legend = ''.join(f'<span><span class="dot" style="background:{BUCKET_COLORS[b]}"></span>'
                     f'{BUCKET_NAMES[b]}</span>' for b in BUCKETS)
    top = ''
    if len(models) <= 3:  # больше трёх колонок не читается — тогда только таблица
        cols = []
        for m in models:
            rows_ = m['attention'][:MAX_SUMMARY_TOP]
            body = ''.join(attention_row(r) for r in rows_) or \
                '<div class="empty">Блокеров и зависших задач нет.</div>'
            cols.append(f'<div class="w"><div class="wh">{e(m["team"])}<span>внимание: '
                        f'{len(m["attention"])}</span></div>{body}</div>')
        top = (f'<div class="body" style="grid-template-columns:repeat({len(models)},minmax(0,1fr));'
               f'align-items:start">{"".join(cols)}</div>')
    return (f'<section class="sheet">{head("Статус спринтов", f"Команды на {report_date}", "", page)}'
            f'{banner}{table}<div class="legend" style="display:flex;gap:18px;margin-top:-4px">{legend}</div>'
            f'{top or "<div style=flex:1></div>"}{foot}</section>')


def render(models, now=None, max_age_h=12, refresh_error=None):
    banner = (f'<div class="banner">⚠ Свежий сбор не удался: {e(refresh_error)}. '
              f'Показан последний снимок.</div>') if refresh_error else ''
    foot = footer(models, now, max_age_h)
    sheets = []
    total = len(models) + (1 if len(models) > 1 else 0)
    stamps = [m['collected'] for m in models if m['collected']]
    report_date = min(stamps).strftime('%d.%m.%Y') if stamps else ''
    if len(models) > 1:
        sheets.append(summary_sheet(models, f'1 / {total}', banner, foot, report_date))
    for i, m in enumerate(models):
        page = f'{i + 1 + (total - len(models))} / {total}'
        sheets.append(team_sheet(m, page, banner, foot))
    title = 'Статус спринта' + (f' · {models[0]["team"]}' if len(models) == 1 else '')
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width={W}"><title>{e(title)} · {report_date}</title>'
            f'<style>{CSS}</style></head><body>{"".join(sheets)}</body></html>')
