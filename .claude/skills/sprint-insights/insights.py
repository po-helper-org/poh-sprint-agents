#!/usr/bin/env python3
"""Инсайды ИИ для сводного отчёта: детерминированная обвязка вокруг ИИ-агента.

Данные отчёта собирает runner actual-sprint скриптом, без модели. Здесь — второй,
отдельный конвейер: агент интерпретирует графики, а скрипт держит его в рамках.

    insights.py facts [--team slug]   факты из снимка: графики, спринт сейчас, тенденция → stdout
    insights.py check [--file путь]   схема, хеш данных, ключи задач, числа против фактов
    insights.py apply [--file путь]   check, затем страница пересобирается из снимка

Агент читает только вывод facts и пишет reports/sprint-insights.json. В JIRA ни
скрипт, ни агент не ходят. Коды выхода: 0 — успех, 1 — инсайды не приняты, 2 — нет
конфига или снимка.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACTUAL = HERE.parent / 'actual-sprint'
STATUS = HERE.parent / 'sprint-status'
for _p in (ACTUAL / 'runner', ACTUAL / 'contract', STATUS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build as build_mod  # noqa: E402
import buckets as buckets_mod  # noqa: E402
import model as model_mod  # noqa: E402
import schema as schema_mod  # noqa: E402

RUNNER = ACTUAL / 'runner' / 'run.py'
SCHEMA_PATH = ACTUAL / 'contract' / 'insights.schema.json'
DEFAULT_CONFIG = 'sprint-report.config.toml'
EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2
TEXT_MAX, ACTION_MAX = 280, 200
KEY_RE = re.compile(r'\b[A-Z][A-Z0-9_]*-\d+\b')
# числа в тексте: не хвосты ключей задач и не части дат
NUM_RE = re.compile(r'(?<![\w.,-])\d+(?:[.,]\d+)?(?![\w-])')
DATE_RE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\b')
FREE_INTS = 5           # «2 задачи», «за 3 дня» — мелкие счёты агент выводит сам


class InsightsError(Exception):
    def __init__(self, message, code=EXIT_ERROR):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ данные

def load_config(path):
    if not Path(path).is_file():
        raise InsightsError(f'конфиг {path} не найден — отчёт ещё не настроен (/sprint-setup)', EXIT_CONFIG)
    import config as config_mod
    try:
        return config_mod.load(path)
    except config_mod.ConfigError as exc:
        raise InsightsError(f'конфиг: {exc}', EXIT_CONFIG) from exc


def load_teams(path):
    if not path.is_file():
        raise InsightsError(f'снимка данных нет ({path}) — сначала соберите отчёт: /actual-sprint', EXIT_CONFIG)
    try:
        teams = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise InsightsError(f'{path} не разбирается как JSON ({exc})') from exc
    if not isinstance(teams, list) or not teams:
        raise InsightsError(f'{path}: ожидается непустой массив команд (формат TEAMS)')
    return teams


def team_keys(team):
    """Все ключи задач, которые есть в данных команды: на них агенту можно ссылаться."""
    keys = set()
    for epic in team['epics']:
        if epic.get('epicKey'):
            keys.add(epic['epicKey'])
        for st in epic['stories']:
            keys.add(st['key'])
            keys.update(sub['key'] for sub in st['subtasks'])
        for it in epic.get('scope') or []:
            keys.add(it['key'])
            keys.update(sub['key'] for sub in it.get('subtasks') or [])
    for group in ('stories', 'subtasks'):
        chart = team['control'].get(group) or {}
        keys.update(p['key'] for p in chart.get('points', []))
        keys.update(r['key'] for r in chart.get('risks', []))
    for sprint in team['metrics'].get('sprints', []):
        keys.update(p['key'] for p in sprint.get('points', []) if isinstance(p, dict) and p.get('key'))
    return keys


# ------------------------------------------------------------------ факты

def r1(x):
    return None if x is None else round(x, 1)


def burndown_facts(tm):
    pace = tm.pace()
    days = pace['days']
    past = [d for d in days if not d['future'] and not d['weekend']]
    # плато: сколько последних рабочих дней подряд число закрытых не росло
    plateau = 0
    for prev, cur in zip(reversed(past[:-1]), reversed(past)):
        if cur['closed'] > prev['closed']:
            break
        plateau += 1
    idx = pace['todayIndex']
    scope_start = days[pace['first']]['scope'] if days else 0
    last3 = past[-4:] if len(past) >= 4 else past
    return {
        'start': pace['start'], 'end': pace['end'], 'overdue': pace['overdue'],
        'workday': pace['workday'], 'workdays': pace['workdays'], 'workdaysLeft': pace['left'],
        'scopeStart': scope_start, 'scopeNow': pace['scope'], 'scopeAdded': pace['scope'] - scope_start,
        'closed': pace['closed'], 'remaining': pace['remaining'],
        'closedPct': round(100 * pace['closed'] / pace['scope']) if pace['scope'] else 0,
        'idealRemainingToday': pace['ideal'][idx] if idx is not None else None,
        'gapToIdeal': pace['gap'],
        'closedToday': pace['dClosed'], 'scopeChangeToday': pace['dScope'],
        'closedLast3Workdays': (last3[-1]['closed'] - last3[0]['closed']) if len(last3) > 1 else 0,
        'plateauWorkdays': plateau,
    }


def velocity_facts(team):
    vel = team['velocity']
    sprints = []
    for s in vel['sprints']:
        sprints.append({'name': s['name'], 'planned': s['planned'], 'done': s['done'],
                        'donePct': round(100 * s['done'] / s['planned']) if s['planned'] else 0,
                        'current': s['name'] == team['sprintName'],
                        'notDone': {b: n for b, n in s['split'].items() if b != 'done' and n}})
    finished = [s for s in sprints if not s['current']]
    trend = None
    if len(finished) >= 2:
        a, b = finished[-2]['done'], finished[-1]['done']
        trend = 'up' if b > a else 'down' if b < a else 'flat'
    return {'unit': vel.get('unit'), 'avgDone': vel.get('avgDone'), 'sprints': sprints,
            'doneTrendFinished': trend}


def control_facts(chart, in_sprint):
    if not chart or not chart.get('points'):
        return {'closedCount': 0, 'note': 'закрытых задач за окно нет'}
    pts = sorted(chart['points'], key=lambda p: p['doneAt'])
    half = len(pts) // 2
    mean = lambda xs: r1(sum(p['cycle'] for p in xs) / len(xs)) if xs else None  # noqa: E731
    median = chart.get('median') or 0
    outliers = sorted((p for p in pts if p['outlier']), key=lambda p: -p['cycle'])
    return {
        'days': chart['days'], 'closedCount': len(pts),
        'median': chart['median'], 'mean': chart['mean'], 'sd': chart['sd'], 'limit': chart['limit'],
        'spread': r1(chart['sd'] / chart['mean']) if chart['mean'] else None,
        'meanFirstHalf': mean(pts[:half]), 'meanSecondHalf': mean(pts[half:]),
        'outlierCount': len(outliers), 'outlierPct': round(100 * len(outliers) / len(pts)),
        'outliers': [{'key': p['key'], 'title': p['title'], 'status': p['status'],
                      'cycle': p['cycle'], 'doneAt': p['doneAt']} for p in outliers],
        'risks': [{'key': r['key'], 'title': r['title'], 'status': r['status'],
                   'assignee': r.get('assignee'), 'elapsed': r['elapsed'],
                   'xMedian': r1(r['elapsed'] / median) if median else None,
                   'inCurrentSprint': r['key'] in in_sprint}
                  for r in sorted(chart.get('risks', []), key=lambda r: -r['elapsed'])],
    }


def team_facts(team, rules):
    core = {k: v for k, v in team.items() if k not in build_mod.OVERLAY_FIELDS}
    tm = model_mod.TeamModel(core, rules)
    blocked, stale = tm.attention()
    in_sprint = {key for _, key, _, _ in tm.items()}
    brief = lambda rows: [{'key': r['key'], 'title': r['title'], 'status': r['status'],  # noqa: E731
                           'days': r['days']} for r in rows]
    return {
        'slug': team['slug'], 'team': team['team'], 'sprintName': team['sprintName'],
        'collectedAt': team['_meta']['collectedAt'],
        'dataHash': build_mod.team_digest(team),
        'charts': {
            'burndown': burndown_facts(tm),
            'velocity': velocity_facts(core),
            'controlStories': control_facts(core['control'].get('stories'), in_sprint),
            'controlSubtasks': control_facts(core['control'].get('subtasks'), in_sprint),
        },
        'sprintNow': {'split': tm.split(), 'blocked': brief(blocked),
                      'staleOver3Days': brief(stale)},
        'trend': trend_facts(core),
    }


def trend_facts(team):
    """Тенденция команды по спринтам отчёта: пропускная способность и сроки."""
    med = lambda m: (m or {}).get('median')  # noqa: E731
    out = []
    for s in team['metrics'].get('sprints', []):
        out.append({'sprint': s['name'], 'total': s['total'], 'closed': s['closed'],
                    'throughputPct': s['throughputPct'],
                    'leadMedian': med(s.get('lead')), 'cycleMedian': med(s.get('cycle')),
                    'leadStoryMedian': med(s.get('leadStory')), 'leadTaskMedian': med(s.get('leadTask'))})
    overall = team['metrics'].get('overall', {})
    return {'sprints': out, 'leadMedianAll': med(overall.get('lead')),
            'cycleMedianAll': med(overall.get('cycle'))}


def facts(teams, only=None):
    rules = buckets_mod.load()
    picked = [t for t in teams if not only or t['slug'] == only]
    if not picked:
        raise InsightsError(f'команды {only} нет в снимке; есть: {", ".join(t["slug"] for t in teams)}',
                            EXIT_CONFIG)
    return {'version': 1, 'teams': [team_facts(t, rules) for t in picked]}


# ------------------------------------------------------------------ проверка

def _numbers(value, out):
    if isinstance(value, bool) or value is None:
        return out
    if isinstance(value, (int, float)):
        for form in {str(value), str(round(value)), f'{value:.1f}', f'{value:.2f}'}:
            out.add(form.rstrip('0').rstrip('.') if '.' in form else form)
    elif isinstance(value, str):
        # «Спринт 73» в тексте — из имени спринта, а не выдумка
        out.update(num for _, num in text_numbers(value))
    elif isinstance(value, dict):
        for v in value.values():
            _numbers(v, out)
    elif isinstance(value, list):
        for v in value:
            _numbers(v, out)
    return out


def text_numbers(text):
    clean = KEY_RE.sub(' ', DATE_RE.sub(' ', text))
    for raw in NUM_RE.findall(clean):
        num = raw.replace(',', '.')
        yield raw, (num.rstrip('0').rstrip('.') if '.' in num else num)


def check(doc, teams):
    """(ошибки, предупреждения). Ошибка — инсайды на страницу не пускаем."""
    errors, warnings = [], []
    root = schema_mod.load_schema(SCHEMA_PATH)
    for err in schema_mod.validate(doc, root, root):
        errors.append(f'схема: {err.path}: {err.message}')
    if errors:
        return errors, warnings
    by_slug = {t['slug']: t for t in teams}
    rules = buckets_mod.load()
    for slug, entry in doc['teams'].items():
        team = by_slug.get(slug)
        if team is None:
            errors.append(f'[{slug}] такой команды нет в снимке; есть: {", ".join(by_slug)}')
            continue
        if entry['dataHash'] != build_mod.team_digest(team):
            errors.append(f'[{slug}] dataHash не совпадает с данными: снимок пересобран после facts. '
                          f'Снова insights.py facts и перепишите инсайды по новым цифрам')
            continue
        keys = team_keys(team)
        allowed = _numbers(team_facts(team, rules), set())
        for n, item in enumerate(entry['observations'], 1):
            where = f'[{slug}] наблюдение #{n}'
            if len(item['text']) > TEXT_MAX:
                errors.append(f'{where}: text длиннее {TEXT_MAX} знаков ({len(item["text"])})')
            if len(item.get('action', '')) > ACTION_MAX:
                errors.append(f'{where}: action длиннее {ACTION_MAX} знаков')
            body = item['text'] + ' ' + item.get('action', '')
            for key in sorted(set(item.get('keys', [])) | set(KEY_RE.findall(body))):
                if key not in keys:
                    errors.append(f'{where}: задачи {key} нет в данных команды')
            for raw, num in text_numbers(body):
                small = num.isdigit() and int(num) <= FREE_INTS
                if not small and num not in allowed:
                    warnings.append(f'{where}: числа {raw} нет в фактах — проверьте, откуда оно')
    return errors, warnings


def read_doc(path):
    if not path.is_file():
        raise InsightsError(f'файла инсайдов нет: {path}. Сначала facts, затем запишите файл')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise InsightsError(f'{path} не разбирается как JSON ({exc})') from exc


# ------------------------------------------------------------------ команды

def cmd_facts(args, cfg):
    teams = load_teams(Path(args.data).resolve() if args.data else cfg.data)
    text = json.dumps(facts(teams, args.team), ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + '\n', encoding='utf-8')
        print(f'факты → {args.out}')
    else:
        print(text)
    return EXIT_OK


def cmd_check(args, cfg, quiet=False):
    teams = load_teams(Path(args.data).resolve() if args.data else cfg.data)
    path = Path(args.file).resolve() if args.file else cfg.insights
    errors, warnings = check(read_doc(path), teams)
    for line in errors:
        print(f'✗ {line}')
    for line in warnings:
        print(f'⚠ {line}')
    if errors:
        print(f'инсайды не приняты: ошибок {len(errors)}. Поправьте {path.name} и проверьте снова.')
        return EXIT_ERROR
    if not quiet:
        print(f'инсайды ✓   предупреждений {len(warnings)}   ← {path}')
    return EXIT_OK


def cmd_apply(args, cfg):
    code = cmd_check(args, cfg, quiet=True)
    if code != EXIT_OK:
        return code
    cmd = [sys.executable, str(RUNNER), '--config', str(cfg.path), 'render']
    if args.data:
        cmd += ['--data', args.data]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    print((proc.stdout + proc.stderr).strip())
    return proc.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description='Инсайды ИИ для сводного отчёта actual-sprint')
    ap.add_argument('--config', default=DEFAULT_CONFIG, help=f'по умолчанию {DEFAULT_CONFIG}')
    ap.add_argument('--data', default=None, help='снимок данных (по умолчанию data конфига)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p_facts = sub.add_parser('facts', help='факты из снимка — вход для агента')
    p_facts.add_argument('--team', default=None, help='slug одной команды')
    p_facts.add_argument('--out', default=None, help='записать в файл вместо stdout')
    for name, text in (('check', 'проверить файл инсайдов'), ('apply', 'проверить и пересобрать страницу')):
        p = sub.add_parser(name, help=text)
        p.add_argument('--file', default=None, help='файл инсайдов (по умолчанию insights конфига)')
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config)
        return {'facts': cmd_facts, 'check': cmd_check, 'apply': cmd_apply}[args.cmd](args, cfg)
    except InsightsError as exc:
        print(f'✗ {exc}')
        return exc.code


if __name__ == '__main__':
    sys.exit(main())
