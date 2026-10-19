#!/usr/bin/env python3
"""Риски квартала для CPO (/business/risks): сбор эпиков квартала, страница и текст для синка.

    quarter.py fetch  [--config путь] [--team slug]   эпики квартала из Jira → quarter-risks.data.json
    quarter.py render [--today ГГГГ-ММ-ДД]            страница, текст для CPO и снимок недели
    quarter.py check  [--file путь]                   блок агента quarter-risks.json против схемы и целей
    quarter.py facts                                  расчёт для агента: статусы, кандидаты, тексты из данных

Файлы — в каталоге reports (рядом с sprint-goals.json): по умолчанию — каталог business_data конфига,
или --reports путь. Jira — только чтение (REST с токеном, как у сборщика). Правила — docs/quarter-risks.md,
решения — docs/adr/0001–0003.

Коды выхода: 0 — успех, 1 — блок не принят, 2 — нет конфига, данных или Jira.
"""
import argparse
import html
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent
for _p in (HERE, SKILLS / 'actual-sprint' / 'runner', SKILLS / 'actual-sprint' / 'contract', SKILLS / 'sprint-blockers'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import buckets as buckets_mod  # noqa: E402
import config as config_mod  # noqa: E402
import quarter_model as qm  # noqa: E402
import schema as schema_mod  # noqa: E402

SCHEMA_PATH = HERE / 'contract' / 'quarter-risks.schema.json'
EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2
PAGE = 50
BATCH = 50
DEFAULT_LINK = '/jira/?key={key}'
ISSUE_FIELDS = 'summary,status,issuetype,assignee,created,resolutiondate'
LIMITS = {'ask': 160, 'who': 60, 'ifNot': 160, 'why': 200, 'title': 80, 'text': 200, 'reason': 160, 'note': 200}


class QuarterError(Exception):
    def __init__(self, message, code=EXIT_ERROR):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ сбор

def _field_id(fields, names):
    names = [n.lower() for n in names]
    return next((f['id'] for f in fields if f.get('name', '').strip().lower() in names), None)


def _chunks(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


def _status_changed(raw):
    last = None
    for h in (raw.get('changelog') or {}).get('histories') or []:
        if any(it.get('field') == 'status' for it in h.get('items') or []) and (last is None or h['created'] > last):
            last = h['created']
    return (last or raw['fields'].get('created') or '')[:10] or None


def _rules(params):
    try:
        return buckets_mod.load(overrides=params.get('status_buckets') or {}, done_exact=params.get('done_statuses'),
                                categories=params.get('categories'), done_categories=params.get('done_categories'),
                                progress_categories=params.get('progress_categories'))
    except ValueError as exc:
        raise QuarterError(f'правила статусов: {exc}', EXIT_CONFIG) from exc


def fetch(transport, teams, goals, now, page=PAGE):
    """Эпики квартала из кэша целей и все их задачи (без подзадач) с датой последней смены статуса.

    teams — [{slug, name, params}] из конфига отчёта: правила статусов те же, что у сборщика (ADR 0002)."""
    meta = transport.get('/rest/api/2/field')
    target_end = _field_id(meta, ('target end', 'целевая дата окончания'))
    due_ids = ([target_end] if target_end else []) + ['duedate']
    quarter = next((g.get('quarter') for g in goals.values() if g.get('quarter')), None)
    out = []
    for team in teams:
        params = team.get('params') or {}
        explicit = params.get('epic_link_field')
        epic_field = explicit if explicit and explicit != 'auto' else \
            _field_id(meta, params.get('epic_link_names') or ('ссылка на эпик', 'epic link'))
        rules = _rules(params)
        keys = list(((goals.get(team['slug']) or {}).get('epics') or {}))
        warnings, epics = [], {}
        for batch in _chunks(keys, BATCH):
            found = transport.get('/rest/api/2/search', jql='key in (' + ','.join(batch) + ')',
                                  fields=','.join(['summary', 'status'] + due_ids), maxResults=len(batch))
            for raw in found.get('issues') or []:
                f = raw['fields']
                st = f.get('status') or {}
                epics[raw['key']] = {
                    'key': raw['key'], 'title': f.get('summary') or raw['key'], 'status': st.get('name'),
                    'bucket': rules.bucket(st.get('name'), (st.get('statusCategory') or {}).get('name', '')),
                    'due': next((str(f[d])[:10] for d in due_ids if f.get(d)), None), 'items': []}
        missing = [k for k in keys if k not in epics]
        if missing:
            warnings.append(f'Jira не отдала {len(missing)} эпик(ов) квартала (нет прав или удалены): {", ".join(missing)}')
        if not epic_field:
            warnings.append('поле связи с эпиком не найдено — задач эпиков нет. Задайте params.epic_link_field')
        elif epics:
            ref = f'cf[{epic_field.split("_")[1]}]' if epic_field.startswith('customfield_') else f'"{epic_field}"'
            for batch in _chunks(list(epics), BATCH):
                jql, start = f'{ref} in ({",".join(batch)}) ORDER BY key', 0
                while True:
                    res = transport.get('/rest/api/2/search', jql=jql, fields=f'{ISSUE_FIELDS},{epic_field}',
                                        expand='changelog', startAt=start, maxResults=page)
                    issues = res.get('issues') or []
                    for raw in issues:
                        f = raw['fields']
                        itype = f.get('issuetype') or {}
                        ek = f.get(epic_field)
                        if itype.get('subtask') or ek not in epics:
                            continue
                        st = f.get('status') or {}
                        bucket = rules.bucket(st.get('name'), (st.get('statusCategory') or {}).get('name', ''))
                        resolved = f.get('resolutiondate') if bucket == 'done' else None
                        epics[ek]['items'].append({
                            'key': raw['key'], 'title': f.get('summary', ''), 'type': itype.get('name'),
                            'status': st.get('name'), 'bucket': bucket,
                            'created': (f.get('created') or '')[:10] or None,
                            'doneAt': resolved[:10] if resolved else None,
                            'statusChanged': _status_changed(raw),
                            'assignee': (f.get('assignee') or {}).get('displayName')})
                    start += len(issues)
                    if not issues or start >= res.get('total', 0):
                        break
        out.append({'slug': team['slug'], 'name': team.get('name') or team['slug'].upper(),
                    'epics': [epics[k] for k in keys if k in epics], 'warnings': warnings})
    return {'version': 1, 'quarter': quarter, 'fetchedAt': now, 'teams': out}


# ------------------------------------------------------------------ страница

ICON = {'red': '🔴', 'yellow': '🟡', 'none': '⚪', 'green': '🟢', 'done': '✅', 'dropped': '✖'}
COUNT_LABEL = {'red': 'не успевают', 'yellow': 'под риском', 'none': 'без прогноза', 'green': 'в срок', 'done': 'готово'}
CIRCLED = '①②③④⑤⑥⑦⑧⑨'
e = html.escape

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#14171c;--muted:#5d6673;--line:#e1e5ea;--red:#d92b3a;--red-bg:#fdecee;
--yellow:#b7791f;--yellow-bg:#fdf5e3;--green:#1f8a4c;--green-bg:#e8f6ee;--grey:#6b7480;--grey-bg:#eef0f3;--accent:#e30611}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--card:#1b1e23;--fg:#e9ecf1;--muted:#9aa3ae;--line:#2c3138;
--red:#ff6b77;--red-bg:#3a1d21;--yellow:#f0b54a;--yellow-bg:#382d17;--green:#5fd08f;--green-bg:#17301f;--grey:#a0a8b3;--grey-bg:#262a30}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:16px}h1{font-size:20px;margin:0 0 2px}h2{font-size:16px;margin:22px 0 8px}
h3{font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin:16px 0 6px}
.sub,.muted,small{color:var(--muted)}small{font-size:12px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}.chip{border-radius:999px;padding:2px 10px;font-size:13px;background:var(--grey-bg);white-space:nowrap}
.c-red{background:var(--red-bg);color:var(--red)}.c-yellow{background:var(--yellow-bg);color:var(--yellow)}
.c-green{background:var(--green-bg);color:var(--green)}.c-none,.c-done,.c-dropped{background:var(--grey-bg);color:var(--grey)}
.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}button{font:inherit;border:1px solid var(--line);background:var(--card);
color:var(--fg);border-radius:8px;padding:5px 12px;cursor:pointer}button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.esc{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--red);border-radius:10px;padding:12px 14px;margin:8px 0}
.esc.s-yellow{border-left-color:var(--yellow)}.esc-head{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:baseline}
.esc dl{display:grid;grid-template-columns:max-content 1fr;gap:3px 12px;margin:8px 0 6px}.esc dt{color:var(--muted)}.esc dd{margin:0}
.esc .foot{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between}
details.cands{margin:10px 0}details.cands>summary{cursor:pointer;color:var(--muted)}
.table{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.grid{display:grid;grid-template-columns:118px minmax(180px,2.2fr) 112px 62px 82px minmax(130px,1.6fr) minmax(130px,1.5fr) 82px;gap:10px;align-items:start;padding:8px 12px}
.head{font-size:12px;color:var(--muted);border-bottom:1px solid var(--line)}
details.row{border-top:1px solid var(--line)}details.row:first-of-type{border-top:0}details.row>summary{list-style:none;cursor:pointer}
details.row>summary::-webkit-details-marker{display:none}details.row[open]>summary{background:var(--bg)}
.st b{font-weight:600}.kr b{display:block}.num{font-variant-numeric:tabular-nums}
.more{padding:6px 12px 14px 140px;display:grid;gap:8px}.more ul{margin:2px 0;padding-left:18px}
a{color:inherit}.late{color:var(--red)}.better{color:var(--green)}
.method{margin-top:26px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:10px}
@media (max-width:820px){.head{display:none}.grid{grid-template-columns:1fr 1fr;gap:4px 10px}
.grid .kr,.grid .blk,.grid .path{grid-column:1/-1}.more{padding:6px 12px 14px}}
@media print{button,.actions,details.cands{display:none}details.row>summary{background:none}}
"""


def _d(value, view):
    return qm.ddmm(value, view['today']) if value else '—'


def _link(key, link):
    return f'<a href="{e(link.replace("{key}", key))}" target="_blank" rel="noopener">{e(key)}</a>'


def _who(row):
    head = f'{row["teamName"]} · {row["kr"]}' if row.get('kr') else row['teamName']
    return head


def _esc_card(esc, view, link, i=None, candidate=False):
    st = esc['status'] if esc['status'] in ('red', 'yellow') else 'red'
    num = f'<b>{CIRCLED[i]}</b> ' if i is not None and i < len(CIRCLED) else ''
    src = '' if esc['source'] == 'agent' else ' <small>· текст из данных — агент уточнит</small>'
    button = (f'<button type="button" class="primary" data-approve="{e(esc["key"])}" data-hash="{e(esc["hash"])}" data-on="1">'
              f'✅ В эскалацию</button>' if candidate else
              f'<button type="button" data-approve="{e(esc["key"])}" data-hash="{e(esc["hash"])}" data-on="0">Снять ✅</button>')
    why = f'<div class="muted">{e(esc["why"])}</div>' if esc.get('why') else ''
    return (f'<article class="esc s-{st}"><div class="esc-head">{num}<b>{e(esc["teamName"])} · {e(esc.get("kr") or esc["key"])}</b>'
            f'<span>«{e(esc["title"])}»</span> {_link(esc["key"], link)}'
            f'<span class="chip c-{st}">шанс к {_d(view["deadline"], view)} — {qm.pct(esc["chance"])}</span></div>'
            f'<dl><dt>Прошу</dt><dd>{e(esc["ask"])}</dd><dt>У кого</dt><dd>{e(esc["who"])}</dd>'
            f'<dt>До</dt><dd>{_d(esc["by"], view)}</dd><dt>Если нет</dt><dd>{e(esc["ifNot"])}</dd></dl>'
            f'<div class="foot">{why}<span>{src}</span>{button}</div></article>')


def _delta_html(row, view):
    d = row.get('delta')
    if not d:
        return '<span class="muted">—</span>'
    parts = []
    if d.get('p85Days'):
        days = d['p85Days']
        parts.append(f'<span class="{"late" if days > 0 else "better"}">{"▲ +" if days > 0 else "▼ −"}{abs(days)} дн.</span>')
    elif d.get('p85Days') == 0:
        parts.append('<span class="muted">=</span>')
    if d.get('statusWas'):
        parts.append(f'<small>было: {e(qm.TITLES.get(d["statusWas"], d["statusWas"]))}</small>')
    if d.get('newBlockers'):
        parts.append(f'<small class="late">+{len(d["newBlockers"])} блок.</small>')
    if d.get('resolvedBlockers'):
        parts.append(f'<small class="better">−{len(d["resolvedBlockers"])} блок.</small>')
    return '<br>'.join(parts) or '<span class="muted">=</span>'


def _row_html(row, view, link):
    st = row['status']
    title = qm.TITLES.get(st, st)
    po = f'<br><small>оценка PO · расчёт: {e(qm.TITLES[row["computedStatus"]])}</small>' if row.get('override') else ''
    dates = f'{_d(row["due"], view)} → {_d(row["p85"], view)}' if row['p85'] or row['due'] else '—'
    chance = qm.pct(row['chance'])
    if row.get('method') == 'team':
        chance += '<br><small>по темпу команды</small>'
    elif row.get('thin'):
        chance += '<br><small>ориентир.</small>'
    prog = f'{round(100 * row["done"] / row["total"])}%' if row['total'] else '—'
    week = f'<br><small>+{row["lastWeek"]:g} за нед.</small>' if row['total'] and row.get('lastWeek') else ''
    if row['blockers']:
        b = row['blockers'][0]
        blk = f'⛔ {b["days"]} раб. дн. — {e(b["key"])} «{e(b["status"])}»'
        if len(row['blockers']) > 1:
            blk += f' <small>и ещё {len(row["blockers"]) - 1}</small>'
    elif row['risks']:
        r = row['risks'][0]
        blk = f'{e(r["roam"])}: {e(r["title"])}'
    else:
        blk = f'<span class="muted">{e(row["note"]) or "—"}</span>'
    path = e(row['path']) if row.get('path') else '<span class="muted">—</span>'
    if row.get('escalation') and row['escalation']['approved']:
        path += ' <small>· в эскалации</small>'
    summary = (f'<summary class="grid"><span class="st"><span class="chip c-{st}">{ICON.get(st, "")} {e(title)}</span>{po}</span>'
               f'<span class="kr"><b>{e(row["kr"] or row["key"])}</b>{e(row["title"])}'
               f'<br><small>{e(row["obj"] or "")} · {e(row["key"])}</small></span>'
               f'<span class="num">{dates}</span><span class="num">{chance}</span><span class="num">{prog}{week}</span>'
               f'<span class="blk">{blk}</span><span class="path">{path}</span><span class="num">{_delta_html(row, view)}</span></summary>')
    more = []
    if row.get('override'):
        more.append(f'<div><b>Оценка PO:</b> {e(row["override"])}</div>')
    if row['p85']:
        method = 'по темпу команды (своей истории меньше 7 недель)' if row['method'] == 'team' else \
            f'по своему темпу за {row["points"]} нед.'
        more.append(f'<div><b>Прогноз</b> {method}: с вероятностью 50% — к {_d(row["p50"], view)}, 85% — к {_d(row["p85"], view)}, '
                    f'95% — к {_d(row["p95"], view)}. К {_d(view["deadline"], view)} с 85% будет закрыто {row["howMany85"]} из {row["open"]}.'
                    + (f' Объём может вырасти до +{round(row["growth"] * 100)}%.' if row['growth'] else '') + '</div>')
    if row['due']:
        more.append(f'<div><b>Target end:</b> {_d(row["due"], view)}'
                    + (' — уже прошёл, обновить в Jira' if row['due'] < view['today'] and st != 'done' else '') + '</div>')
    if row['blockers']:
        more.append('<div><b>Блокаторы</b><ul>' + ''.join(
            f'<li>{_link(b["key"], link)} «{e(b["title"])}» — {e(b["status"])} с {_d(b["since"], view)}, {b["days"]} раб. дн.'
            + (f' · {e(b["assignee"])}' if b.get('assignee') else '') + '</li>' for b in row['blockers']) + '</ul></div>')
    if row['risks']:
        more.append('<div><b>Риски</b><ul>' + ''.join(
            f'<li><b>{e(r["roam"])}</b> · {e(r["title"])} — {e(r["owner"])}'
            + (f', решить до {_d(qm.day(r["due"]), view)}' if r.get('due') else '') + (f'. {e(r["text"])}' if r.get('text') else '')
            + '</li>' for r in row['risks']) + '</ul></div>')
    if row['items']:
        shown = row['items'][:15]
        more.append(f'<div><b>Открытые задачи ({row["open"]})</b><ul>' + ''.join(
            f'<li>{_link(it["key"], link)} {e(it.get("title", ""))} <small>· {e(it.get("status") or "")}'
            + (f' · {e(it["assignee"])}' if it.get('assignee') else '') + '</small></li>' for it in shown)
            + (f'<li class="muted">и ещё {row["open"] - len(shown)}</li>' if row['open'] > len(shown) else '') + '</ul></div>')
    return f'<details class="row s-{st}">{summary}<div class="more">{"".join(more)}</div></details>'


def render_html(view, link=DEFAULT_LINK):
    counts = view['counts']
    chips = ''.join(f'<span class="chip c-{s}">{ICON[s]} {counts[s]} {COUNT_LABEL[s]}</span>' for s in qm.STATUSES if counts.get(s))
    if view['previousWeek']:
        chips += f'<span class="chip{" c-red" if view["shifted"] else ""}">прогноз сдвинулся позже: {view["shifted"]}</span>'
    fetched = view.get('fetchedAt') or ''
    try:
        fetched = datetime.fromisoformat(fetched).strftime('%d.%m %H:%M')
    except ValueError:
        pass
    out = [f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">'
           f'<title>Риски квартала {e(view["quarter"])}</title><style>{CSS}</style></head><body><main>'
           f'<header><h1>Риски квартала {e(view["quarter"])}</h1>'
           f'<div class="sub">неделя с {_d(view["monday"], view)} · данные Jira {e(fetched)} · до конца квартала '
           f'({_d(view["deadline"], view)}) — {view["weeksLeft"]} нед.</div><div class="chips">{chips}</div>'
           f'<div class="actions"><button type="button" class="primary" data-act="copy">Скопировать для CPO</button>'
           f'<button type="button" data-act="refresh">Обновить данные</button></div></header>']
    out.append('<section><h2>Нужно решение</h2>')
    if view['escalations']:
        out += [_esc_card(x, view, link, i) for i, x in enumerate(view['escalations'])]
        if view['moreEscalations']:
            out.append(f'<p class="muted">Ещё {view["moreEscalations"]} эскалации с ✅ — наверху только ближайшие три.</p>')
    else:
        out.append('<p class="muted">Эскалаций нет. Кандидаты ниже — отметьте ✅ те, что нужно поднять на синке.</p>')
    out.append('</section>')
    if view['candidates']:
        out.append(f'<details class="cands"><summary>Кандидаты в эскалацию: {len(view["candidates"])} — ждут ✅ PO</summary>'
                   + ''.join(_esc_card(x, view, link, candidate=True) for x in view['candidates']) + '</details>')
    prev = view['previousWeek']
    week_head = f'За неделю <small>к прошлому понедельнику {_d(qm.day(prev), view)}</small>' if prev else \
        'За неделю <small>сравнение — со следующего понедельника</small>'
    out.append('<section><h2>Инициативы квартала</h2>')
    for team in view['teams']:
        out.append(f'<h3>{e(team["name"])}</h3>')
        for w in team['warnings']:
            out.append(f'<p class="late"><small>⚠ {e(w)}</small></p>')
        out.append(f'<div class="table"><div class="grid head"><span>Статус</span><span>Инициатива</span>'
                   f'<span>Target end → 85%</span><span>Шанс к {_d(view["deadline"], view)}</span><span>Прогресс</span>'
                   f'<span>Блокатор / риск</span><span>Путь в зелёный</span><span>{week_head}</span></div>')
        out += [_row_html(r, view, link) for r in team['rows']]
        out.append('</div>')
    out.append('</section>')
    for label, rows in (('Вхождение в квартал не решено', view['unconfirmed']), ('Сняты из квартала', view['dropped'])):
        if rows:
            out.append(f'<section><h2>{label}</h2><ul>' + ''.join(
                f'<li>{e(r["teamName"])} · {e(r["kr"] or r["key"])} «{e(r["title"])}» {_link(r["key"], link)}</li>' for r in rows)
                + '</ul></section>')
    out.append(
        f'<footer class="method"><b>Как считается.</b> Инициатива — эпик из карты целей квартала. Шанс — доля из 10 000 прогонов '
        f'Monte Carlo по числу задач, закрытых за каждую из последних 12 недель, в которых остаток закрыт до '
        f'{_d(view["deadline"], view)}; неделя считается, если закончилась до конца квартала. Меньше 7 недель своей истории — '
        f'доля темпа команды. Блокатор — задача в ожидании без движения 3+ рабочих дня. Статус: '
        f'🔴 шанс &lt; 50% или блокатор ≥ 10 раб. дн.; 🟡 шанс &lt; 85% или блокатор ≥ 3; 🟢 шанс ≥ 85%. '
        f'Target end — веха команды, на цвет не влияет.</footer>')
    out.append('</main><script src="/business/risks-page.js" defer></script></body></html>')
    return ''.join(out)


def cpo_text(view):
    c = view['counts']
    lines = [f'Риски квартала {view["quarter"]} · {qm.ddmm(view["monday"])} · до конца квартала {view["weeksLeft"]} нед.',
             ' · '.join(f'{qm.TITLES[s]} {c[s]}' for s in qm.STATUSES), '']
    if view['escalations']:
        lines.append('Нужно решение:')
        for i, x in enumerate(view['escalations'], 1):
            lines += [f'{i}. {x["teamName"]} · {x.get("kr") or x["key"]} «{x["title"]}» — шанс к {qm.ddmm(view["deadline"])}: {qm.pct(x["chance"])}',
                      f'   Прошу: {x["ask"]} · у кого: {x["who"]} · до {qm.ddmm(x["by"], view["today"])}',
                      f'   Если нет: {x["ifNot"]}']
    else:
        lines.append('Нужно решение: нет')
    at_risk = [r for t in view['teams'] for r in t['rows'] if r['status'] in ('red', 'yellow')
               and not (r.get('escalation') and r['escalation']['approved'])]
    if at_risk:
        lines += ['', 'Под угрозой (без эскалации):']
        for r in at_risk:
            extra = f', путь в зелёный: {r["path"]}' if r.get('path') else ''
            lines.append(f'- {r["teamName"]} · {r["kr"] or r["key"]} «{r["title"]}» — {qm.TITLES[r["status"]]}, '
                         f'шанс {qm.pct(r["chance"])}{extra}')
    return '\n'.join(lines) + '\n'


# ------------------------------------------------------------------ файлы и проверка

class Reports:
    def __init__(self, path):
        self.dir = Path(path)
        self.goals = self.dir / 'sprint-goals.json'
        self.data = self.dir / 'quarter-risks.data.json'
        self.block = self.dir / 'quarter-risks.json'
        self.approvals = self.dir / 'quarter-risks.approvals.json'
        self.page = self.dir / 'quarter-risks.html'
        self.text = self.dir / 'quarter-risks.txt'
        self.history = self.dir / 'quarter-risks.history'


def read_json(path, what, required=True):
    if not Path(path).is_file():
        if required:
            raise QuarterError(f'{what} нет: {path}', EXIT_CONFIG)
        return None
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise QuarterError(f'{path} не разбирается как JSON ({exc})') from exc


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def read_goals(rep):
    doc = read_json(rep.goals, 'кэша целей (sprint-goals.json)')
    teams = doc.get('teams') if isinstance(doc, dict) else None
    if not isinstance(teams, dict) or not teams:
        raise QuarterError(f'{rep.goals}: нет teams — агент ещё не записал цели квартала', EXIT_CONFIG)
    return teams


def check_block(doc, goals):
    errors = [f'схема: {err.path}: {err.message}' for err in schema_mod.validate(doc, schema_mod.load_schema(SCHEMA_PATH))]
    if errors:
        return errors
    for slug, team in (doc.get('teams') or {}).items():
        known = (goals.get(slug) or {}).get('epics') or {}
        if slug not in goals:
            errors.append(f'[{slug}] такой команды нет в кэше целей; есть: {", ".join(goals)}')
            continue
        for key, ini in (team.get('initiatives') or {}).items():
            where = f'[{slug}] {key}'
            if key not in known:
                errors.append(f'{where}: эпика нет среди инициатив квартала команды')
            texts = [(f, (ini.get('escalation') or {}).get(f)) for f in ('ask', 'who', 'ifNot', 'why')]
            texts += [('title', r.get('title')) for r in ini.get('risks') or []] + [('text', r.get('text')) for r in ini.get('risks') or []]
            texts += [('reason', (ini.get('override') or {}).get('reason')), ('note', ini.get('note'))]
            errors += [f'{where}.{f}: длиннее {LIMITS[f]} знаков ({len(t)})' for f, t in texts if t and len(t) > LIMITS[f]]
    return errors


def load_history(rep, monday):
    if not rep.history.is_dir():
        return None
    weeks = sorted(p.stem for p in rep.history.glob('*.json') if p.stem < monday.isoformat())
    return read_json(rep.history / f'{weeks[-1]}.json', 'снимка недели', required=False) if weeks else None


def make_view(rep, today=None, quiet=False):
    goals = read_goals(rep)
    data = read_json(rep.data, 'данных квартала (quarter-risks.data.json) — сначала quarter.py fetch')
    block = read_json(rep.block, 'блока агента', required=False)
    if block is not None:
        errors = check_block(block, goals)
        if errors:
            if not quiet:
                print('⚠ блок агента не принят, страница — на текстах из данных:\n  ' + '\n  '.join(errors[:5]))
            block = None
    raw = read_json(rep.approvals, '✅ PO', required=False) or {}
    approvals = {k: (v.get('hash') if isinstance(v, dict) else v) for k, v in raw.items()}
    today = today or qm.day(data.get('fetchedAt')) or date.today()
    from forecast import week_monday
    history = load_history(rep, week_monday(today))
    return qm.build(goals, data, block=block, approvals=approvals, history=history, today=today)


def _jsonable(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


# ------------------------------------------------------------------ команды

def reports_of(args):
    if args.reports:
        return Reports(args.reports)
    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        raise QuarterError(f'конфиг: {exc}', EXIT_CONFIG) from exc
    return Reports(cfg.business_data.parent)


def cmd_fetch(args):
    try:
        cfg = config_mod.load(args.config)
        token, url = cfg.token(), cfg.jira_url()
    except config_mod.ConfigError as exc:
        raise QuarterError(f'конфиг: {exc}', EXIT_CONFIG) from exc
    import source as source_mod  # REST-транспорт /sprint-blockers: только GET, TLS всегда
    rep = Reports(args.reports) if args.reports else Reports(cfg.business_data.parent)
    goals = read_goals(rep)
    teams = [{'slug': t.slug, 'name': t.name, 'params': t.params} for t in cfg.teams
             if t.slug in goals and (not args.team or t.slug == args.team)]
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')
    try:
        transport = source_mod.RestTransport(url, token, cfg.ca_bundle)
        data = fetch(transport, teams, goals, now)
    except source_mod.SourceError as exc:
        raise QuarterError(str(exc), EXIT_CONFIG) from exc
    write_text(rep.data, json.dumps(data, ensure_ascii=False, indent=1) + '\n')
    n = sum(len(t['epics']) for t in data['teams'])
    items = sum(len(e['items']) for t in data['teams'] for e in t['epics'])
    print(f'квартал {data["quarter"]}: эпиков {n}, задач {items} → {rep.data}')
    for t in data['teams']:
        for w in t['warnings']:
            print(f'⚠ [{t["slug"]}] {w}')
    return EXIT_OK


def cmd_render(args):
    rep = reports_of(args)
    view = make_view(rep, qm.day(args.today) if args.today else None)
    write_text(rep.page, render_html(view, args.link or DEFAULT_LINK))
    write_text(rep.text, cpo_text(view))
    write_text(rep.history / f'{view["snapshot"]["week"]}.json', json.dumps(view['snapshot'], ensure_ascii=False, indent=1) + '\n')
    c = view['counts']
    print(f'риски квартала {view["quarter"]}: ' + ', '.join(f'{qm.TITLES[s].lower()} {c[s]}' for s in qm.STATUSES if c[s])
          + f'; эскалаций {len(view["escalations"])}, кандидатов {len(view["candidates"])} → {rep.page}')
    return EXIT_OK


def cmd_check(args):
    rep = reports_of(args)
    path = Path(args.file) if args.file else rep.block
    errors = check_block(read_json(path, 'блока агента'), read_goals(rep))
    for line in errors:
        print(f'✗ {line}')
    if errors:
        print(f'блок не принят: ошибок {len(errors)}. Поправьте {path.name} и проверьте снова.')
        return EXIT_ERROR
    print(f'блок агента ✓ ← {path}')
    return EXIT_OK


def cmd_facts(args):
    view = make_view(reports_of(args), qm.day(args.today) if args.today else None)
    slim = {k: v for k, v in view.items() if k not in ('snapshot',)}
    for t in slim['teams']:
        t['rows'] = [{k: v for k, v in r.items() if k != 'items'} for r in t['rows']]
    print(json.dumps(_jsonable(slim), ensure_ascii=False, indent=1))
    return EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(description='Риски квартала для CPO (/business/risks)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name, text in (('fetch', 'эпики квартала из Jira'), ('render', 'страница, текст для CPO, снимок недели'),
                       ('check', 'проверить блок агента'), ('facts', 'расчёт для агента')):
        p = sub.add_parser(name, help=text)
        p.add_argument('--config', default='sprint-report.config.toml', help='конфиг отчёта (команды, Jira, пути)')
        p.add_argument('--reports', default=None, help='каталог reports вместо пути из конфига')
        if name == 'fetch':
            p.add_argument('--team', default=None, help='только эта команда')
        if name in ('render', 'facts'):
            p.add_argument('--today', default=None, help='дата снимка ГГГГ-ММ-ДД (по умолчанию — дата сбора)')
        if name == 'render':
            p.add_argument('--link', default=None, help=f'ссылка на задачу с {{key}}, по умолчанию {DEFAULT_LINK}')
        if name == 'check':
            p.add_argument('--file', default=None, help='блок агента (по умолчанию reports/quarter-risks.json)')
    args = ap.parse_args(argv)
    try:
        return {'fetch': cmd_fetch, 'render': cmd_render, 'check': cmd_check, 'facts': cmd_facts}[args.cmd](args)
    except QuarterError as exc:
        print(f'✗ {exc}')
        return exc.code


if __name__ == '__main__':
    sys.exit(main())
