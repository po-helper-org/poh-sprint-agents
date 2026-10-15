#!/usr/bin/env python3
"""Разбор блокеров: проверка файла агента против фактов и страница отчёта.

Агент только классифицирует (кого и чего ждали) и пишет вывод; все числа на
странице — из фактов: дни случая и стороны скрипт пересчитывает по датам
ожиданий, а не берёт у агента.
"""
import html
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACTUAL = HERE.parent / 'actual-sprint'
for _p in (HERE, ACTUAL / 'runner'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import schema as schema_mod  # noqa: E402
import waits as waits_mod  # noqa: E402

SCHEMA_PATH = HERE / 'contract' / 'blockers.schema.json'
TEMPLATE = HERE / 'resources' / 'blockers_template.html'
LEAD_MAX, SECTION_MAX, WHAT_MAX, BASIS_MAX = 450, 220, 160, 240
TOP_CASES = 15
KEY_RE = waits_mod.KEY_RE
NUM_RE = re.compile(r'(?<![\w.,-])\d+(?:[.,]\d+)?(?![\w-])')
DATE_RE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b|\b\d{1,2}[–-]\d{1,2}\b|'
                     r'\b\d{1,2}(?:[–-]\d{1,2})?\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|'
                     r'октябр|ноябр|декабр)\w*|\b(?:19|20)\d{2}\b|\bQ[1-4]\b')
FREE_INTS = 5
STATE = {'open': 'открыто', 'done': 'решено', 'workaround': 'решено обходом'}


# ------------------------------------------------------------------ дни

def wait_days(w, per):
    """Рабочие дни ожидания по окнам: те же правила, что в waits.facts."""
    hol = {date.fromisoformat(h) for h in per.get('holidays', [])}
    to_d = date.fromisoformat(per['to'])
    # дни — только внутри периода отчёта, как в waits.facts; даты случая — как в JIRA
    start = max(date.fromisoformat(w['from']), date.fromisoformat(per['from']))
    end = date.fromisoformat(w['to']) if w['to'] else to_d + timedelta(days=1)
    days = set(waits_mod.workdays(start, min(end, to_d + timedelta(days=1)), hol))
    out = {}
    for win in per['windows']:
        w0, w1 = date.fromisoformat(win['from']), date.fromisoformat(win['to'])
        out[win['id']] = {d for d in days if w0 <= d <= w1}
    out['total'] = days
    return out


def union(day_sets, wid):
    acc = set()
    for ds in day_sets:
        acc |= ds[wid]
    return acc


# ------------------------------------------------------------------ проверка

def text_numbers(text):
    clean = KEY_RE.sub(' ', DATE_RE.sub(' ', text))
    for raw in NUM_RE.findall(clean):
        num = raw.replace(',', '.')
        yield raw, (num.rstrip('0').rstrip('.') if '.' in num else num)


def collect_numbers(value, out):
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        out.add(str(round(value)) if float(value).is_integer() else str(value))
    elif isinstance(value, str):
        out.update(n for _, n in text_numbers(value))
    elif isinstance(value, dict):
        for v in value.values():
            collect_numbers(v, out)
    elif isinstance(value, list):
        for v in value:
            collect_numbers(v, out)
    return out


def disjoint(wids, by_id, report_to):
    """Пара ожиданий случая, между которыми разрыв во времени (больше выходных), или None."""
    spans = sorted((by_id[w]['from'], by_id[w]['to'] or report_to, w) for w in wids if w in by_id)
    if not spans:
        return None
    end, last = date.fromisoformat(spans[0][1]), spans[0][2]
    for start, stop, wid in spans[1:]:
        if date.fromisoformat(start) > end + timedelta(days=3):
            return last, wid
        if date.fromisoformat(stop) > end:
            end, last = date.fromisoformat(stop), wid
    return None


def check(doc, facts):
    """(ошибки, предупреждения, вид страницы). Есть ошибки — вида нет."""
    errors, warnings = [], []
    root = schema_mod.load_schema(SCHEMA_PATH)
    for err in schema_mod.validate(doc, root, root):
        errors.append(f'схема: {err.path}: {err.message}')
    if errors:
        return errors, warnings, None
    if doc['factsHash'] != facts['factsHash']:
        errors.append('factsHash не совпадает с фактами: снимок или период изменились после facts. '
                      'Снова blockers.py facts и разложите ожидания заново')
        return errors, warnings, None
    by_id = {w['id']: w for w in facts['waits']}
    seen = {}
    for group, items in (('cases', doc['cases']), ('notBlockers', doc['notBlockers'])):
        for n, item in enumerate(items, 1):
            for wid in item['waits']:
                where = f'{group}[{n}]'
                if wid not in by_id:
                    errors.append(f'{where}: ожидания {wid} нет в фактах')
                elif wid in seen:
                    errors.append(f'{where}: ожидание {wid} уже разобрано в {seen[wid]}')
                else:
                    seen[wid] = where
    for wid in by_id:
        if wid not in seen:
            w = by_id[wid]
            errors.append(f'ожидание {wid} ({w["key"]}, {w["from"]}) не разобрано: '
                          f'положите его в случай или в notBlockers с причиной')
    sides = {}
    for s in doc['sides']:
        if s['id'] in sides:
            errors.append(f'сторона {s["id"]} описана дважды')
        sides[s['id']] = s
        if len(s['what']) > WHAT_MAX:
            errors.append(f'сторона {s["id"]}: what длиннее {WHAT_MAX} знаков')
    used = set()
    for n, case in enumerate(doc['cases'], 1):
        if case['side'] not in sides:
            errors.append(f'cases[{n}]: стороны {case["side"]} нет в sides')
        used.add(case['side'])
        if len(case['what']) > WHAT_MAX:
            errors.append(f'cases[{n}]: what длиннее {WHAT_MAX} знаков')
        if len(case['basis']) > BASIS_MAX:
            errors.append(f'cases[{n}]: basis длиннее {BASIS_MAX} знаков')
    for n, case in enumerate(doc['cases'], 1):
        gap = disjoint(case['waits'], by_id, facts['period']['to'])
        if gap:
            errors.append(f'cases[{n}]: ожидания {gap[0]} и {gap[1]} не пересекаются по времени — это разные '
                          f'случаи: одно и то же задачи ждут одновременно. Разделите их')
    for sid in sides:
        if sid not in used:
            warnings.append(f'сторона {sid} не используется ни в одном случае')
    for n, text in enumerate(doc['lead'], 1):
        if len(text) > LEAD_MAX:
            errors.append(f'lead[{n}]: длиннее {LEAD_MAX} знаков ({len(text)})')
    for name, text in (doc.get('sections') or {}).items():
        if len(text) > SECTION_MAX:
            errors.append(f'sections.{name}: длиннее {SECTION_MAX} знаков ({len(text)})')
    known_keys = set(KEY_RE.findall(json.dumps(facts, ensure_ascii=False)))
    # вывод агента: в нём проверяем и ключи, и числа; в случаях и сторонах — только ключи
    # (в основании законно цитируются даты и номера из комментариев)
    narrative = [(f'lead[{n}]', t) for n, t in enumerate(doc['lead'], 1)]
    narrative += [(f'sections.{k}', v) for k, v in (doc.get('sections') or {}).items()]
    texts = narrative + [(f'cases[{n}]', c['what'] + ' ' + c['basis']) for n, c in enumerate(doc['cases'], 1)]
    texts += [(f'sides.{s["id"]}', s['what']) for s in doc['sides']]
    for where, text in texts:
        for key in sorted(set(KEY_RE.findall(text))):
            if key not in known_keys:
                errors.append(f'{where}: задачи {key} нет в фактах')
    if errors:
        return errors, warnings, None
    view = build(doc, facts)
    allowed = collect_numbers(facts, set()) | collect_numbers(view['numbers'], set())
    for where, text in narrative:
        for raw, num in text_numbers(text):
            if not (num.isdigit() and int(num) <= FREE_INTS) and num not in allowed:
                warnings.append(f'{where}: числа {raw} нет ни в фактах, ни в таблицах — проверьте, откуда оно')
    return errors, warnings, view


# ------------------------------------------------------------------ вид

def fmt_day(iso):
    d = date.fromisoformat(iso)
    return f'{d.day:02d}.{d.month:02d}'


def build(doc, facts):
    """Таблицы страницы из фактов и классификации агента."""
    per = facts['period']
    wins = per['windows']
    by_id = {w['id']: w for w in facts['waits']}
    days_of = {wid: wait_days(w, per) for wid, w in by_id.items()}
    sides = {s['id']: s for s in doc['sides']}
    cases = []
    for case in doc['cases']:
        ws = [by_id[i] for i in case['waits']]
        sets = [days_of[i] for i in case['waits']]
        is_open = any(w['open'] for w in ws)
        start = min(w['from'] for w in ws)
        end = None if is_open else max(w['to'] for w in ws)
        state = 'open' if is_open else ('workaround' if case.get('workaround') else 'done')
        keys = []
        for w in ws:
            if w['key'] not in keys:
                keys.append(w['key'])
        cases.append({
            'when': f'с {fmt_day(start)}' if is_open else f'{fmt_day(start)}–{fmt_day(end)}',
            'start': start, 'what': case['what'], 'side': sides[case['side']]['name'],
            'sideId': case['side'], 'days': len(union(sets, 'total')),
            'win': {w['id']: len(union(sets, w['id'])) for w in wins},
            'state': state, 'keys': keys, 'evidence': case['evidence'], 'basis': case['basis'],
            'stages': sorted({w['stage'] for w in ws}), 'sets': sets,
        })
    cases.sort(key=lambda c: (-c['days'], c['start']))
    side_rows = []
    for s in doc['sides']:
        own = [c for c in cases if c['sideId'] == s['id']]
        if not own:
            continue
        sets = [ds for c in own for ds in c['sets']]
        side_rows.append({'name': s['name'], 'what': s['what'], 'internal': bool(s.get('internal')),
                          'unknown': bool(s.get('unknown')),
                          'cases': len(own), 'open': sum(c['state'] == 'open' for c in own),
                          'win': {w['id']: len(union(sets, w['id'])) for w in wins},
                          'caseDays': {w['id']: sum(c['win'][w['id']] for c in own) for w in wins}})
    side_rows.sort(key=lambda r: [-r['caseDays'][w['id']] for w in wins] + [r['name']])
    all_sets = [ds for c in cases for ds in c['sets']]
    external = lambda c: not (sides[c['sideId']].get('internal') or sides[c['sideId']].get('unknown'))  # noqa: E731
    ext_sets = [ds for c in cases if external(c) for ds in c['sets']]
    kpi = {w['id']: {'any': len(union(all_sets, w['id'])), 'external': len(union(ext_sets, w['id'])),
                     'caseDays': sum(c['win'][w['id']] for c in cases),
                     'externalCaseDays': sum(c['win'][w['id']] for c in cases if external(c)),
                     'workdays': w['workdays']} for w in wins}
    stages = [st for st in facts['stages'] if any(st['windows'][w['id']]['tasks'] for w in wins)]
    numbers = {'kpi': kpi, 'sides': [[r['win'], r['caseDays']] for r in side_rows],
               'cases': [[c['days'], c['win']] for c in cases],
               'open': sum(c['state'] == 'open' for c in cases), 'count': len(cases)}
    for c in cases:
        del c['sets']
    return {'team': facts['team'], 'period': per, 'source': facts['source'], 'rules': facts['rules'],
            'lead': doc['lead'], 'sections': doc.get('sections') or {}, 'sides': side_rows,
            'stages': stages, 'cases': cases, 'kpi': kpi, 'numbers': numbers,
            'signals': len(facts['signals']), 'notBlockers': sum(len(n['waits']) for n in doc['notBlockers']),
            'weak': sum(c['evidence'] == 'weak' for c in cases), 'limits': doc.get('limits') or [],
            'jiraBase': facts.get('jiraBase')}


# ------------------------------------------------------------------ страница

def esc(text):
    return html.escape(str(text if text is not None else ''), quote=True)


def issue_link(key, base):
    # адрес JIRA приходит из ответа сервера: в href — только http(s)
    if base and re.match(r'^https?://', base):
        return (f'<a class="key" href="{esc(base.rstrip("/"))}/browse/{esc(key)}" target="_blank" '
                f'rel="noopener">{esc(key)}</a>')
    return f'<span class="key mono">{esc(key)}</span>'


def quarter_title(q):
    year, n = q.split('Q')
    return f'{["I", "II", "III", "IV"][int(n) - 1]} квартал {year}'


def render(view, now):
    wins = view['period']['windows']
    head_w = ''.join(f'<th class="num">{esc(w["label"])}, раб. дней из {w["workdays"]}</th>' for w in wins)
    team = view['team'].get('name') or view['team'].get('slug')
    parts = [f'<h1>Блокеры: {esc(team)}, {esc(quarter_title(view["period"]["quarter"]))}</h1>',
             f'<p class="meta mono">отчёт на {esc(view["period"]["to"])} · собран {esc(now)}</p>']
    kpi = []
    for w in wins:
        k = view['kpi'][w['id']]
        kpi.append(f'<div class="kpi"><span class="kpi-n">{k["externalCaseDays"]}</span>'
                   f'<span class="kpi-l mono">{esc(w["label"])}: дней ожидания других команд</span></div>')
    opened = view['numbers']['open']
    kpi.append(f'<div class="kpi"><span class="kpi-n">{view["numbers"]["count"]}</span>'
               f'<span class="kpi-l mono">случаев ожидания, открыто {opened}</span></div>')
    parts.append('<div class="kpis">' + ''.join(kpi) + '</div>')
    parts += [f'<p class="lead">{esc(p)}</p>' for p in view['lead']]

    parts.append('<h2>Кого ждали</h2>')
    if view['sections'].get('sides'):
        parts.append(f'<p>{esc(view["sections"]["sides"])}</p>')
    def tag(r):
        if r['internal']:
            return ' <span class="tag mono">своя команда</span>'
        return ' <span class="tag mono">сторона не названа</span>' if r['unknown'] else ''
    head_s = ''.join(f'<th class="num">{esc(w["label"])}: дней ожидания · дней из {w["workdays"]}</th>' for w in wins)
    rows = ''.join(
        f'<tr><td data-l="Кого">{esc(r["name"])}{tag(r)}</td>'
        + ''.join(f'<td class="num" data-l="{esc(w["label"])}">{r["caseDays"][w["id"]]}'
                  f'<small> · {r["win"][w["id"]]} из {w["workdays"]}</small></td>' for w in wins)
        + f'<td data-l="Чего ждали">{esc(r["what"])}</td></tr>' for r in view['sides'])
    parts.append(f'<div class="table-wrap"><table class="cards"><thead><tr><th>Кого ждали</th>{head_s}'
                 f'<th>Чего ждали</th></tr></thead><tbody>{rows}</tbody></table></div>')
    parts.append('<p class="note">Дни ожидания — сумма длительностей случаев в рабочих днях: два разных случая '
                 'по неделе — 10 дней; если несколько задач ждали одно и то же, это один случай — 5. '
                 '«Дней из N» — рабочие дни, когда эту сторону ждала хотя бы одна задача; '
                 'ожидания часто шли одновременно, поэтому эти дни не складываются. Стороны без пометки — '
                 'другие команды и партнёры.</p>')

    parts.append('<h2>Где стояли задачи</h2>')
    if view['sections'].get('stages'):
        parts.append(f'<p>{esc(view["sections"]["stages"])}</p>')
    srows = ''
    for st in view['stages']:
        cells = ''.join(f'<td class="num" data-l="{esc(w["label"])}">{st["windows"][w["id"]]["days"]}'
                        f'<small> · задач {st["windows"][w["id"]]["tasks"]}, медиана {st["windows"][w["id"]]["medianDays"]}</small></td>'
                        for w in wins)
        srows += (f'<tr><td data-l="Стадия">{esc(st["name"])}<br><small class="mono">'
                  f'{esc(", ".join(st["statuses"]))}</small></td>{cells}</tr>')
    parts.append(f'<div class="table-wrap"><table class="cards"><thead><tr><th>Стадия</th>{head_w}</tr></thead>'
                 f'<tbody>{srows}</tbody></table></div>')
    parts.append(f'<p class="note">Дни — рабочие дни, когда в стадии стояла хотя бы одна задача; медиана — '
                 f'рабочих дней одного захода. Случаем считается заход в очередь не короче '
                 f'{view["rules"]["queueMinDays"]} рабочих дней и любая приостановка.</p>')

    parts.append('<h2>Главные случаи</h2>')
    if view['sections'].get('cases'):
        parts.append(f'<p>{esc(view["sections"]["cases"])}</p>')

    def case_rows(cases):
        out = ''
        for c in cases:
            keys = ', '.join(issue_link(k, view['jiraBase']) for k in c['keys'])
            weak = ' <span class="tag mono">слабое подтверждение</span>' if c['evidence'] == 'weak' else ''
            out += (f'<tr><td class="mono" data-l="Когда">{esc(c["when"])}</td>'
                    f'<td data-l="Чего ждали">{esc(c["what"])}{weak}'
                    f'<details><summary>основание</summary>{esc(c["basis"])}</details></td>'
                    f'<td data-l="От кого">{esc(c["side"])}</td>'
                    f'<td class="num" data-l="Раб. дней">{c["days"]}</td>'
                    f'<td data-l="Сейчас"><span class="st st-{c["state"]}">{STATE[c["state"]]}</span></td>'
                    f'<td data-l="Задачи">{keys}</td></tr>')
        return out
    head_c = ('<thead><tr><th>Когда</th><th>Чего ждали</th><th>От кого</th><th class="num">Рабочих дней</th>'
              '<th>Сейчас</th><th>Задачи</th></tr></thead>')
    top, rest = view['cases'][:TOP_CASES], view['cases'][TOP_CASES:]
    parts.append(f'<div class="table-wrap"><table class="cards">{head_c}<tbody>{case_rows(top)}</tbody></table></div>')
    if rest:
        parts.append(f'<details class="more"><summary>Остальные случаи: {len(rest)}</summary>'
                     f'<div class="table-wrap"><table class="cards">{head_c}<tbody>{case_rows(rest)}</tbody>'
                     f'</table></div></details>')
    if opened:
        parts.append(f'<p class="note">Открыто на {esc(view["period"]["to"])}: {opened}.</p>')

    src = view['source']
    parts.append('<h2>Источники и ограничения</h2>')
    parts.append('<p>Цифры посчитаны скриптом по истории статусов задач JIRA; кого и чего ждали — '
                 'вывод ИИ-агента по комментариям и связям задач, у каждого случая есть основание.</p>')
    parts.append('<div class="table-wrap"><table><thead><tr><th>Источник</th><th>Что взято</th></tr></thead><tbody>'
                 f'<tr><td>JIRA ({esc(src.get("transport"))})</td><td>{src.get("issues")} задач: история статусов, '
                 f'комментарии, связи. Выборка: <span class="mono">{esc(src.get("jql"))}</span>. '
                 f'Снято {esc(src.get("fetchedAt"))}</td></tr></tbody></table></div>')
    limits = ['Часы работы не измеряются: учёта времени в JIRA нет. Мера потерь — рабочие дни, '
              'когда задача стояла; пока задача стоит, команда обычно делает другую работу, '
              'поэтому дни — это задержка сроков, а не простой людей.',
              'Ожидание видно, только если задачу перевели в статус ожидания или она стояла в очереди. '
              'Ожидание «в работе» без смены статуса отчёт не видит.']
    if view['rules'].get('skip'):
        limits.append('Не считались статусы: ' + ', '.join(view['rules']['skip']) + '.')
    if view['signals']:
        limits.append(f'Ещё {view["signals"]} комментариев говорят об ожидании, но статус задачи не менялся — '
                      f'в таблицы они не вошли.')
    if view['notBlockers']:
        limits.append(f'Не вошли {view["notBlockers"]} приостановок, которые не были ожиданием других '
                      f'(пауза по приоритету, свои ошибки, требования).')
    if view['weak']:
        limits.append(f'У {view["weak"]} случаев причина выведена по косвенным признакам — помечены '
                      f'«слабое подтверждение».')
    limits += view['limits']
    parts.append('<ul>' + ''.join(f'<li>{esc(x)}</li>' for x in limits) + '</ul>')
    body = '\n'.join(parts)
    title = f'Блокеры {team} · {quarter_title(view["period"]["quarter"])}'
    page = TEMPLATE.read_text(encoding='utf-8')
    return page.replace('{{TITLE}}', esc(title)).replace('{{BODY}}', body)


def demo(out):
    """Демо-страница из examples/: вымышленная команда, те же проверки, что у настоящей."""
    ex = HERE / 'examples'
    snap = json.loads((ex / 'demo-snapshot.json').read_text(encoding='utf-8'))
    doc = json.loads((ex / 'demo-blockers.json').read_text(encoding='utf-8'))
    facts = waits_mod.facts(snap, waits_mod.period('2026Q3', to='2026-10-14'), {})
    errors, _, view = check(doc, facts)
    if errors:
        raise SystemExit('\n'.join(errors))
    Path(out).write_text(render(view, '2026-10-14T18:00'), encoding='utf-8')
    print(f'демо → {out}')


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--demo':
        raise SystemExit('использование: report.py --demo страница.html')
    demo(sys.argv[2])
