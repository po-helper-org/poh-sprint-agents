#!/usr/bin/env python3
"""Бизнес-отчёт «ФАКТ | спринт»: детерминированная обвязка навыка sprint-business.

Данные — тот же снимок, что у отчёта PO (runner actual-sprint собирает их скриптом,
без модели). Страница и генерация — свои: агент пишет бизнес-блок, скрипт держит его
в рамках и собирает sprint-business.html.

    business.py facts [--team slug]          факты из снимка (те же, что у sprint-insights)
    business.py check [--file путь]          схема, хеш данных, эпики и истории, длины, числа
    business.py apply [--file путь]          check, затем render
    business.py render [--output путь]       sprint-business.html из снимка, без JIRA

Коды выхода: 0 — успех, 1 — блок не принят, 2 — нет конфига или снимка.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'sprint-insights'))
import insights as ins  # noqa: E402  факты, конфиг и проверка чисел — общие с sprint-insights

import build as build_mod  # noqa: E402
import buckets as buckets_mod  # noqa: E402
import schema as schema_mod  # noqa: E402
import validate as validate_mod  # noqa: E402

SCHEMA_PATH = HERE / 'contract' / 'business.schema.json'
TEMPLATE_PATH = HERE / 'resources' / 'business_template.html'
EXIT_OK, EXIT_ERROR, EXIT_CONFIG = ins.EXIT_OK, ins.EXIT_ERROR, ins.EXIT_CONFIG
# поле → предел длины: слайд не резиновый
LIMITS = {'objective': 100, 'kr': 120, 'promise': 160, 'shown': 160, 'done': 140, 'next': 100, 'blocker': 120,
          'stream_done': 180, 'stream_next': 100, 'stream_blocker': 140,
          'affected': 80, 'before': 120, 'after': 120, 'outcome': 200, 'what': 120, 'title': 80, 'text': 280,
          'plan_title': 80, 'plan_text': 160, 'escalate': 60, 'escalation': 60}
# ключ строки «Вне эпиков» в streams: истории спринта без эпика (как в шаблоне страницы)
NO_EPIC = 'no-epic'


class BusinessError(ins.InsightsError):
    pass


# ------------------------------------------------------------------ проверка

def check(doc, teams):
    """(ошибки, предупреждения). Ошибка — блок на страницу не пускаем."""
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
                          f'Снова business.py facts и перепишите блок по новым цифрам')
            continue
        allowed = ins._numbers(ins.team_facts(team, rules), set())
        check_team(slug, entry, team, ins.team_keys(team), allowed, errors, warnings)
    return errors, warnings


def check_team(slug, biz, team, keys, allowed, errors, warnings):
    """Бизнес-блок презентации: KR — эпики команды, строки — истории её спринта, цели —
    из списка objectives, длины — под слайд, ключи задач — из данных. Числа сверяются с
    фактами там, где они из данных (строки, Sprint Goal); цели OKR, риски и договорённости
    приходят из документов PO — их числа с фактами спринта не сверить."""
    epics = {e['epicKey'] for e in team['epics'] if e.get('epicKey')}
    no_epic = any(not e.get('epicKey') and e['stories'] for e in team['epics'])
    stories = {st['key'] for e in team['epics'] for st in e['stories']}
    objectives = biz.get('objectives', {})
    texts = [(f'objectives.{k}', v, LIMITS['objective'], False) for k, v in objectives.items()]
    for key, st in biz.get('streams', {}).items():
        if key == NO_EPIC:
            if not no_epic:
                errors.append(f'[{slug}] streams.{NO_EPIC}: историй без эпика в спринте нет')
            if 'obj' in st or 'kr' in st:
                errors.append(f'[{slug}] streams.{NO_EPIC}: у строки «Вне эпиков» нет цели и KR — только done/next/blocker')
        elif key not in epics:
            errors.append(f'[{slug}] streams: эпика {key} нет в спринте команды; есть: {", ".join(sorted(epics))}')
        if 'obj' in st and st['obj'] not in objectives:
            warnings.append(f'[{slug}] streams.{key}: цели {st["obj"]} нет в objectives — заголовок слайда будет без названия')
        texts += [(f'streams.{key}.kr', st['kr'], LIMITS['kr'], False)] if 'kr' in st else []
        texts += [(f'streams.{key}.{f}', st[f], LIMITS[f], True) for f in ('promise', 'shown') if f in st]
        texts += [(f'streams.{key}.{f}', st[f], LIMITS['stream_' + f], True) for f in ('done', 'next', 'blocker') if f in st]
    for key, row in biz.get('rows', {}).items():
        if key not in stories:
            errors.append(f'[{slug}] rows: истории {key} нет в спринте команды')
        texts += [(f'rows.{key}.{f}', row[f], LIMITS[f], True) for f in ('done', 'next', 'blocker') if f in row]
        texts += [(f'rows.{key}.escalate', row['escalate'], LIMITS['escalate'], False)] if 'escalate' in row else []
    for key in biz.get('hide', []):
        if key not in stories:
            errors.append(f'[{slug}] hide: задачи {key} нет в спринте команды')
    texts += [('escalation', biz['escalation'], LIMITS['escalation'], False)] if 'escalation' in biz else []
    for i, c in enumerate(biz.get('changes', []), 1):
        texts += [(f'changes #{i}.{f}', c[f], LIMITS[f], False) for f in ('affected', 'before', 'after', 'outcome') if f in c]
    texts += [(f'demo #{i}', d['what'], LIMITS['what'], False) for i, d in enumerate(biz.get('demo', []), 1)]
    for i, r in enumerate(biz.get('risks', []), 1):
        texts += [(f'risks #{i}.title', r['title'], LIMITS['title'], False),
                  (f'risks #{i}.text', r['text'], LIMITS['text'], False)]
    for col, cards in biz.get('plans', {}).items():
        for i, c in enumerate(cards, 1):
            texts += [(f'plans.{col} #{i}.title', c['title'], LIMITS['plan_title'], True)]
            texts += [(f'plans.{col} #{i}.text', c['text'], LIMITS['plan_text'], True)] if 'text' in c else []
            for key in c.get('keys', []):
                if key not in keys:
                    errors.append(f'[{slug}] plans.{col} #{i}: задачи {key} нет в данных команды')
    for where, text, limit, numbers in texts:
        where = f'[{slug}] {where}'
        if len(text) > limit:
            errors.append(f'{where}: длиннее {limit} знаков ({len(text)}) — на слайд не влезет')
        for key in sorted(set(ins.KEY_RE.findall(text))):
            if key not in keys:
                errors.append(f'{where}: задачи {key} нет в данных команды')
        for raw, num in (ins.text_numbers(text) if numbers else ()):
            small = num.isdigit() and int(num) <= ins.FREE_INTS
            if not small and num not in allowed:
                warnings.append(f'{where}: числа {raw} нет в фактах — проверьте, откуда оно')
    from_okr = objectives or any('kr' in st for st in biz.get('streams', {}).values()) or biz.get('risks')
    if from_okr and not biz.get('goalsSource'):
        warnings.append(f'[{slug}] цели OKR и риски без goalsSource — укажите, откуда они (OKR, roadmap, со слов PO)')


# ------------------------------------------------------------------ страница

def read_doc(path, required=True):
    path = Path(path)
    if not path.is_file():
        if required:
            raise BusinessError(f'файла бизнес-блока нет: {path}. Сначала facts, затем запишите файл')
        return None
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise BusinessError(f'{path} не разбирается как JSON ({exc})') from exc
    if not isinstance(doc, dict) or not isinstance(doc.get('teams'), dict):
        raise BusinessError(f'{path}: ожидается объект с полем teams — см. contract/business.schema.json')
    return doc


def attach(teams, doc):
    """Блок — в поле business команды, только если он написан по этим же данным."""
    attached, stale = [], []
    for team in teams:
        team.pop('business', None)
        entry = (doc or {}).get('teams', {}).get(team['slug'])
        if not isinstance(entry, dict):
            continue
        if entry.get('dataHash') != build_mod.team_digest(team):
            stale.append(team['slug'])
            continue
        team['business'] = {k: v for k, v in entry.items() if k != 'dataHash'}
        if (doc or {}).get('jiraNative'):
            team['business']['jiraNative'] = doc['jiraNative']
        attached.append(team['slug'])
    return attached, stale


def load_snapshot(path):
    teams = ins.load_teams(path)
    for team in teams:
        core = {k: v for k, v in team.items() if k not in build_mod.OVERLAY_FIELDS}
        report = validate_mod.check(core)
        if not report.ok:
            raise BusinessError(f'[{team.get("slug", "?")}] снимок не прошёл валидацию: {path}\n' +
                                '\n'.join(report.lines()))
    return teams


def render(cfg, data=None, file=None, output=None):
    teams = load_snapshot(Path(data).resolve() if data else cfg.data)
    path = Path(file).resolve() if file else cfg.business_data
    attached, stale = attach(teams, read_doc(path, required=False))
    out = build_mod.write_page(teams, TEMPLATE_PATH, Path(output).resolve() if output else cfg.business)
    parts = [f'бизнес-отчёт из снимка: команд {len(teams)}']
    if attached:
        parts.append(f'цели и формулировки агента: {", ".join(attached)}')
    if stale:
        parts.append(f'блок устарел (данные пересобраны): {", ".join(stale)} — /sprint-business')
    if not attached and not stale:
        parts.append(f'блока агента нет ({path.name}) — текст строк из данных')
    print('   '.join(parts))
    print(f'→ {out}')
    return EXIT_OK


# ------------------------------------------------------------------ команды

def cmd_facts(args, cfg):
    teams = ins.load_teams(Path(args.data).resolve() if args.data else cfg.data)
    text = json.dumps(ins.facts(teams, args.team), ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + '\n', encoding='utf-8')
        print(f'факты → {args.out}')
    else:
        print(text)
    return EXIT_OK


def cmd_check(args, cfg, quiet=False):
    teams = ins.load_teams(Path(args.data).resolve() if args.data else cfg.data)
    path = Path(args.file).resolve() if args.file else cfg.business_data
    errors, warnings = check(read_doc(path), teams)
    for line in errors:
        print(f'✗ {line}')
    for line in warnings:
        print(f'⚠ {line}')
    if errors:
        print(f'бизнес-блок не принят: ошибок {len(errors)}. Поправьте {path.name} и проверьте снова.')
        return EXIT_ERROR
    if not quiet:
        print(f'бизнес-блок ✓   предупреждений {len(warnings)}   ← {path}')
    return EXIT_OK


def cmd_apply(args, cfg):
    code = cmd_check(args, cfg, quiet=True)
    if code != EXIT_OK:
        return code
    return render(cfg, args.data, args.file, getattr(args, 'output', None))


def cmd_render(args, cfg):
    return render(cfg, args.data, args.file, args.output)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Бизнес-отчёт «ФАКТ | спринт» (навык sprint-business)')
    ap.add_argument('--config', default=ins.DEFAULT_CONFIG, help=f'по умолчанию {ins.DEFAULT_CONFIG}')
    ap.add_argument('--data', default=None, help='снимок данных (по умолчанию data конфига)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    p_facts = sub.add_parser('facts', help='факты из снимка — вход для агента')
    p_facts.add_argument('--team', default=None, help='slug одной команды')
    p_facts.add_argument('--out', default=None, help='записать в файл вместо stdout')
    for name, text in (('check', 'проверить бизнес-блок'), ('apply', 'проверить и собрать страницу'),
                       ('render', 'собрать страницу из снимка')):
        p = sub.add_parser(name, help=text)
        p.add_argument('--file', default=None, help='бизнес-блок (по умолчанию business_data конфига)')
        if name != 'check':
            p.add_argument('--output', default=None, help='куда писать HTML (по умолчанию business конфига)')
    args = ap.parse_args(argv)
    try:
        cfg = ins.load_config(args.config)
        return {'facts': cmd_facts, 'check': cmd_check, 'apply': cmd_apply, 'render': cmd_render}[args.cmd](args, cfg)
    except (ins.InsightsError, build_mod.BuildError) as exc:
        print(f'✗ {exc}')
        return getattr(exc, 'code', EXIT_ERROR)


if __name__ == '__main__':
    sys.exit(main())
