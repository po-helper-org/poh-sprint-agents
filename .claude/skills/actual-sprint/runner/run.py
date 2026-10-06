#!/usr/bin/env python3
"""Runner отчёта actual-sprint: конфиг → сборщики → валидация → HTML.

Единственный способ получить данные отчёта. Модель сюда не заглядывает: она
запускает `run` и показывает сводку. Сама в JIRA не ходит.

    run.py doctor    [--config sprint-report.config.toml]
    run.py run       [--config sprint-report.config.toml] [--only team-a,team-b]
    run.py render    [--data снимок.json] [--output страница.html]
    run.py validate  <slug> [--sample 5] [--seed N]
    run.py check     <файл.json> [--all]   схема, инварианты и покрытие экранов готового JSON
    run.py lock      <slug>
    run.py new       <slug> [--lang python]

Коды выхода: 0 — успех, 2 — конфиг, 3 — JIRA недоступна, 1 — остальное.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MIN_PYTHON = (3, 9)
if sys.version_info < MIN_PYTHON:
    sys.exit(f'runner требует Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+, запущен '
             f'{sys.version_info.major}.{sys.version_info.minor}.')

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent / 'contract'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build
import buckets as buckets_mod
import config as config_mod
import validate as validate_mod

EXIT_OK, EXIT_ERROR, EXIT_CONFIG, EXIT_JIRA = 0, 1, 2, 3
DEFAULT_CONFIG = 'sprint-report.config.toml'


class RunFailure(Exception):
    """Сбор одной команды не удался. code — код выхода runner."""

    def __init__(self, message, code=EXIT_ERROR, hint=None):
        super().__init__(message)
        self.code = code
        self.hint = hint


def eprint(*parts):
    print(*parts, file=sys.stderr)


def now_iso(explicit=None):
    if explicit:
        return explicit
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


# --------------------------------------------------------------- запуск сборщика

def collector_env():
    """Окружение сборщика: своё плюс путь к контракту. Токен уже в os.environ."""
    env = dict(os.environ)
    env[buckets_mod.ENV_CONTRACT] = str(config_mod.SCHEMA_PATH.parent)
    env[buckets_mod.ENV_RULES] = str(buckets_mod.DEFAULT_RULES)
    return env


def request_payload(cfg, team, url, now):
    return {
        'protocol': config_mod.PROTOCOL,
        'team': {'slug': team.slug, 'name': team.name, 'board': team.board},
        'params': team.params,
        'jira': {'url': url, 'caBundle': str(cfg.ca_bundle) if cfg.ca_bundle else None},
        'now': now,
    }


def run_build_step(team):
    if not team.build:
        return
    eprint(f'[{team.slug}] сборка: {" ".join(team.build)}')
    proc = subprocess.run(team.build, cwd=str(team.cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RunFailure(f'этап сборки упал (код {proc.returncode})\n{proc.stderr.strip()}')


def run_collector(cfg, team, url, now, extra_args=()):
    """Запускает сборщик по протоколу и возвращает (объект команды, секунды)."""
    run_build_step(team)
    argv = team.argv() + list(extra_args)
    payload = json.dumps(request_payload(cfg, team, url, now), ensure_ascii=False)
    eprint(f'[{team.slug}] запускаю сборщик: {" ".join(argv)}')
    started = datetime.now()
    try:
        # communicate, а не живой поток: так таймаут гарантированно снимает процесс,
        # а stderr показывается целиком и с префиксом команды сразу после
        proc = subprocess.Popen(argv, cwd=str(team.cwd), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=collector_env())
    except FileNotFoundError as exc:
        raise RunFailure(f'сборщик не запускается: {exc}', EXIT_CONFIG) from exc
    try:
        out, err = proc.communicate(payload, timeout=team.timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RunFailure(f'сборщик не уложился в timeout {team.timeout} с и был снят', EXIT_ERROR)
    elapsed = (datetime.now() - started).total_seconds()
    for line in (err or '').splitlines():
        eprint(f'[{team.slug}] {line}')

    if proc.returncode == EXIT_CONFIG:
        raise RunFailure('сборщик отверг конфигурацию или params — проверьте конфиг', EXIT_CONFIG)
    if proc.returncode == EXIT_JIRA:
        raise RunFailure('JIRA недоступна или не авторизует — проверьте VPN и токен', EXIT_JIRA)
    if proc.returncode != 0:
        raise RunFailure(f'сборщик вышел с кодом {proc.returncode} (см. stderr выше)')

    if not (out or '').strip():
        raise RunFailure('сборщик ничего не отдал в stdout — ожидается один JSON-объект команды')
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        head = out.strip()[:200]
        raise RunFailure(f'stdout не разбирается как JSON ({exc}). Начало вывода: {head!r}')
    if not isinstance(data, dict):
        raise RunFailure('в stdout ожидается один JSON-объект команды, получен другой тип')
    got = data.get('_meta', {}).get('protocol')
    if got != config_mod.PROTOCOL:
        raise RunFailure(f'сборщик отвечает по протоколу {got!r}, runner знает '
                         f'{config_mod.PROTOCOL}', EXIT_CONFIG)
    return data, elapsed


def check_lock(cfg, team, lock):
    """strict: непроверенный или изменённый сборщик не запускается (ФТ-8)."""
    state, entry, digest = config_mod.lock_state(team, lock)
    if state == 'ok':
        return f'✓ проверен {str(entry.get("validatedAt", ""))[:10]}'
    if not cfg.strict:
        return {'missing': '⚠ не проверен (strict выключен)',
                'changed': '⚠ изменён после проверки (strict выключен)'}[state]
    raise RunFailure(f'{lock_reason(team, state, entry)}.\n'
                     f'         Запустите /collector-validate {team.slug}. HTML не сгенерирован.',
                     EXIT_CONFIG)


def team_line(team, data, elapsed):
    m = data['metrics']['overall']
    return (f'[{team.slug}] доска «{data["boardName"]}» (#{data["boardId"]}), '
            f'спринт «{data["sprintName"]}» | эпиков {len(data["epics"])} | '
            f'закрыто {m["closed"]}/{m["total"]} | событий {len(data["logs"]["events"])} | '
            f'{data["_meta"]["requests"]} запросов | {elapsed:.1f}s')


def sidecar_path(cfg, team):
    """Сайдкар команды: <workspace>/reports/teams/<slug>.json — последний валидный сбор."""
    return cfg.root / 'reports' / 'teams' / f'{team.slug}.json'


def write_sidecar(cfg, team, data):
    """Пишет объект команды после валидации (атомарно): merge собирает страницу из этих файлов.

    Пишется сразу после успешной команды, до проверки остальных: упадёт соседняя —
    у этой на диске уже свежие данные, у упавшей остаётся её прошлый сайдкар."""
    path = sidecar_path(cfg, team)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)
    return path


DEFAULT_STALE_HOURS = 6


# --------------------------------------------------------------- команды CLI

def lock_reason(team, state, entry):
    """Почему сборщик не считается проверенным — словами, а не кодом состояния.

    У базового сборщика «изменился» почти всегда значит «обновился плагин»:
    это не подозрительная правка, но проверять его всё равно надо заново.
    """
    if state == 'missing':
        return 'не проверен'
    if team.is_base:
        was = entry.get('version') or 'прошлой версии'
        return f'базовый сборщик обновился с проверки ({was} → {config_mod.PLUGIN_VERSION})'
    return f'изменён после проверки (sha {entry["sha256"][:7]} → {team.digest()[:7]})'


def cmd_doctor(args):
    """Проверка стенда до первого похода в JIRA: что на месте, что задано, что проверено.

    Намеренно не ходит в сеть: сетевые и доступовые проблемы показывает первый же
    `validate <slug>`, а здесь отвечаем на вопрос «всё ли разложено по местам».
    """
    ok = True
    print(f'python         ✓ {sys.version_info.major}.{sys.version_info.minor}.'
          f'{sys.version_info.micro}')

    parts = {'схема': config_mod.SCHEMA_PATH,
             'протокол': config_mod.SCHEMA_PATH.parent / 'PROTOCOL.md',
             'правила бакетов': buckets_mod.DEFAULT_RULES,
             'шаблон страницы': config_mod.TEMPLATE_PATH,
             'базовый сборщик': config_mod.BASE_COLLECTOR}
    missing = [name for name, path in parts.items() if not Path(path).is_file()]
    if missing:
        ok = False
        print(f'плагин         ✗ не хватает файлов: {", ".join(missing)}')
    else:
        print(f'плагин         ✓ {config_mod.PLUGIN_VERSION}, контракт и шаблоны на месте')

    try:
        cfg = config_mod.load(args.config)
    except config_mod.ConfigError as exc:
        print(f'конфиг         ✗ {exc}')
        print('\nСтенд не готов. Конфиг пишет /sprint-setup.')
        return EXIT_CONFIG
    print(f'конфиг         ✓ {cfg.path.name}, команд {len(cfg.teams)}, '
          f'strict {"вкл" if cfg.strict else "выкл"}')

    # значения переменных не печатаем никогда: в одной из них токен
    for label, env_name, getter in (('адрес JIRA', cfg.url_env, cfg.jira_url),
                                    ('токен', cfg.token_env, cfg.token)):
        try:
            getter()
            print(f'{label:14} ✓ {env_name} задан')
        except config_mod.ConfigError as exc:
            ok = False
            print(f'{label:14} ✗ {exc}')
    if cfg.ca_bundle:
        print(f'ca_bundle      ✓ {cfg.ca_bundle}')
    else:
        print('ca_bundle      — не задан (нужен, только если инстанс за корпоративным CA)')

    lock = config_mod.read_lock(cfg)
    for team in cfg.teams:
        where = 'base' if team.is_base else os.path.relpath(team.cwd, cfg.root)
        if not team.is_base:
            exe = Path(team.argv()[0])
            if not team.build and not exe.exists() and '/' in team.cmd[0]:
                ok = False
                print(f'[{team.slug}] ✗ сборщик не найден: {exe}')
                continue
        state, entry, digest = config_mod.lock_state(team, lock)
        if state == 'ok':
            print(f'[{team.slug}] ✓ {where}, проверен {str(entry.get("validatedAt", ""))[:10]}')
            continue
        if cfg.strict:
            ok = False
        print(f'[{team.slug}] {"✗" if cfg.strict else "⚠"} {where}, '
              f'{lock_reason(team, state, entry)} — запустите /collector-validate {team.slug}')

    print()
    if ok:
        print('Стенд готов. Первый поход в JIRA — python3 run.py validate <slug> --sample 5')
        return EXIT_OK
    print('Стенд не готов: разберитесь со строками ✗ выше.')
    return EXIT_CONFIG


def cmd_run(args):
    cfg = config_mod.load(args.config)
    url = cfg.jira_url()
    cfg.token()  # проверяем до запуска: без токена сборщик всё равно упадёт
    lock = config_mod.read_lock(cfg)
    now = now_iso(args.now)

    wanted = [s.strip() for s in args.only.split(',')] if args.only else None
    teams = [cfg.team(s) for s in wanted] if wanted else cfg.teams

    collected, reports, failures, codes = [], [], [], set()
    for team in teams:
        try:
            head = check_lock(cfg, team, lock)
            version_tag = f'{team.collector_name}@{config_mod.PLUGIN_VERSION}' if team.is_base \
                else f'{os.path.relpath(team.cwd, cfg.root)}  sha {team.digest()[:7]}'
            print(f'[{team.slug}] {version_tag:30} {head}')
            data, elapsed = run_collector(cfg, team, url, now)
            report = validate_mod.check(data, cfg_team=team)
            reports.append(report)
            if not report.ok:
                failures.append((team.slug, 'валидация не прошла'))
                for line in report.lines():
                    print(line)
                continue
            # sha сборщика знает runner, а не сборщик: подвал страницы показывает,
            # какой именно код дал эти цифры
            data['_meta']['sha'] = team.digest()
            collected.append(data)
            sidecar = write_sidecar(cfg, team, data)
            print(f'[{team.slug}] сайдкар → {os.path.relpath(sidecar, cfg.root)}')
            print(team_line(team, data, elapsed))
            gaps = [r for r in validate_mod.coverage(data) if r[2] != 'есть']
            if gaps:
                print(f'[{team.slug}] без данных или частично: {len(gaps)} экранов '
                      f'({", ".join(r[1] for r in gaps[:3])}{"…" if len(gaps) > 3 else ""}) — run.py check <снимок>')
        except RunFailure as exc:
            print(f'[{team.slug}] ✗ {exc}')
            failures.append((team.slug, str(exc)))
            codes.add(exc.code)
            if exc.code == EXIT_JIRA:
                return EXIT_JIRA

    if failures:
        print(f'\n✗ не собраны команды: {", ".join(s for s, _ in failures)}. '
              f'HTML не сгенерирован, прошлый файл не тронут.')
        # код выхода сохраняет причину: конфиг и lock — это 2, остальное 1
        return EXIT_CONFIG if codes == {EXIT_CONFIG} else EXIT_ERROR

    notes = build.read_notes(cfg.notes)
    picked = build.attach_notes(collected, notes)
    # инсайды прошлого сбора к новым данным не подходят: attach_insights их отсеет по хешу
    ins_line = build.insights_line(*build.attach_insights(collected, build.read_insights(cfg.insights)))
    # порядок команд в файле = порядок в конфиге = порядок вкладок
    order = {t.slug: i for i, t in enumerate(teams)}
    collected.sort(key=lambda d: order.get(d['slug'], 0))
    out = build.write_page(collected, config_mod.TEMPLATE_PATH, cfg.output)
    # снимок пишется только вместе со страницей: у текста и HTML одни и те же цифры
    build.write_atomic(cfg.data, build.snapshot(collected))

    warnings = sum(len(r.warnings) for r in reports)
    invariants = sum(r.passed for r in reports)
    total_inv = sum(r.invariants_total for r in reports)
    for r in reports:
        for w in r.warnings:
            print(f'[{r.slug}] предупреждение: {w}')
    print(f'схема ✓   инварианты {invariants}/{total_inv} ✓   '
          f'предупреждений {warnings}   заметок подхвачено {picked}')
    if ins_line:
        print(ins_line)
    rel = lambda p: os.path.relpath(p, Path.cwd()) if str(p).startswith(str(Path.cwd())) else p  # noqa: E731
    print(f'→ {rel(out)}')
    return EXIT_OK


def cmd_merge(args):
    """Консолидация: сайдкары команд из N workspace'ов → один HTML.

    Не ходит в JIRA: данные уже собраны прошлыми run'ами. Каждый сайдкар
    перевалидируется (схема + инварианты) — протухший или битый не попадает
    на страницу молча.
    """
    import time

    cfg = config_mod.load(args.config)
    slugs = []
    for part in args.slugs:            # 'a,b' тоже поддерживаем на всякий случай
        slugs.extend(s.strip() for s in part.split(','))
    # порядок поиска сайдкара: явный путь → workspace'ы по порядку → корень конфига
    workspaces = [Path(w).resolve() for w in args.workspace] + [cfg.root]

    collected, failures = [], []
    for slug in slugs:
        candidates = ([Path(slug).resolve()] if (':' not in slug and '/' in slug) else []) \
            + [ws / 'reports' / 'teams' / f'{slug}.json' for ws in workspaces]
        found = next((c for c in candidates if c.is_file()), None)
        if found is None:
            print(f'[{slug}] ✗ сайдкар не найден ни в одном workspace: '
                  f'{", ".join(str(c) for c in candidates)}')
            failures.append(slug)
            continue
        try:
            data = json.loads(found.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            print(f'[{slug}] ✗ сайдкар не разбирается как JSON ({exc}): {found}')
            failures.append(slug)
            continue
        age_h = (time.time() - found.stat().st_mtime) / 3600
        if age_h > args.stale_hours and not args.stale_ok:
            print(f'[{slug}] ✗ сайдкар протух: {age_h:.1f} ч (порог {args.stale_hours} ч) '
                  f'— соберите команду заново или --stale-ok. {found}')
            failures.append(slug)
            continue
        report = validate_mod.check(data)
        if not report.ok:
            print(f'[{slug}] ✗ сайдкар не прошёл валидацию: {found}')
            for line in report.lines():
                print(line)
            failures.append(slug)
            continue
        collected.append(data)
        stale_note = f' (⚠ данные {age_h:.1f} ч назад)' if age_h > args.stale_hours else ''
        m = data['metrics']['overall']
        print(f'[{slug}] ✓ эпиков {len(data["epics"])}, закрыто {m["closed"]}/{m["total"]}'
              f'{stale_note} ← {found}')

    if failures:
        print(f'\n✗ не приняты команды: {", ".join(failures)}. HTML не сгенерирован.')
        return EXIT_CONFIG

    # заметки: из всех workspace'ов — локальные заметки PO остаются при командах
    notes = {}
    for ws in dict.fromkeys(workspaces):  # уникальные, порядок сохранён
        notes_file = ws / 'reports' / 'sprint-report-notes.json'
        if notes_file.is_file():
            try:
                notes.update(build.read_notes(notes_file))
            except build.BuildError as exc:
                print(f'заметки: {exc}')
    picked = build.attach_notes(collected, notes)
    ins_line = build.insights_line(*build.attach_insights(collected, build.read_insights(cfg.insights)))
    out = Path(args.output).resolve() if args.output else cfg.output
    written = build.write_page(collected, config_mod.TEMPLATE_PATH, out)
    # снимок для /sprint-status — рядом со страницей, как у run: иначе PDF показывал
    # бы прошлый сбор, а страница — склейку из сайдкаров
    data_out = out.with_name(out.stem + '.data.json') if args.output else cfg.data
    build.write_atomic(data_out, build.snapshot(collected))
    print(f'схема ✓   заметок подхвачено {picked}   команд {len(collected)}')
    if ins_line:
        print(ins_line)
    print(f'→ {written}')
    return EXIT_OK


def cmd_render(args):
    """Пересобрать страницу из снимка данных: без JIRA и без сборщиков.

    Нужен после /sprint-insights: цифры те же, к ним добавляется интерпретация.
    Снимок перевалидируется — правленый руками файл на страницу не попадёт.
    """
    cfg = config_mod.load(args.config)
    data_path = Path(args.data).resolve() if args.data else cfg.data
    if not data_path.is_file():
        raise RunFailure(f'снимка данных нет: {data_path}. Сначала соберите отчёт: run.py run',
                         code=EXIT_CONFIG)
    try:
        teams = json.loads(data_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise RunFailure(f'снимок {data_path} не разбирается как JSON ({exc})') from exc
    if not isinstance(teams, list) or not teams:
        raise RunFailure(f'снимок {data_path}: ожидается непустой массив команд')
    for team in teams:
        core = {k: v for k, v in team.items() if k not in build.OVERLAY_FIELDS}
        report = validate_mod.check(core)
        if not report.ok:
            print(f'[{team.get("slug", "?")}] ✗ снимок не прошёл валидацию: {data_path}')
            for line in report.lines():
                print(line)
            return EXIT_ERROR
    attached, stale = build.attach_insights(teams, build.read_insights(cfg.insights))
    out = Path(args.output).resolve() if args.output else cfg.output
    written = build.write_page(teams, config_mod.TEMPLATE_PATH, out)
    print(f'страница из снимка: команд {len(teams)}   ' +
          (build.insights_line(attached, stale) or f'инсайдов нет ({cfg.insights.name} не найден)'))
    print(f'→ {written}')
    return EXIT_ERROR if stale and not attached else EXIT_OK


def cmd_validate(args):
    cfg = config_mod.load(args.config)
    url = cfg.jira_url()
    cfg.token()
    team = cfg.team(args.slug)
    now = now_iso(args.now)
    try:
        data, elapsed = run_collector(cfg, team, url, now)
    except RunFailure as exc:
        print(f'запуск сборщика ✗ {exc}')
        return exc.code
    print(f'запуск сборщика ✓ (exit 0, {elapsed:.1f}s, {data["_meta"]["requests"]} запросов)')
    report = validate_mod.check(data, cfg_team=team)
    for line in report.lines():
        print(line)
    if not report.ok:
        print(f'\n✗ команда «{team.slug}» не прошла валидацию. Поправьте сборщик и повторите.')
        return EXIT_ERROR
    for line in validate_mod.coverage_lines(data):
        print(line)

    rows, seed = validate_mod.sample(data, args.sample, args.seed)
    print(f'выборка для сверки с JIRA (seed {seed}):')
    for line in validate_mod.format_sample(rows):
        print(line)
    # хеш пишет отдельная команда: подтверждение PO — часть проверки, а не флаг
    print('\nСверьте эти задачи в JIRA поле за полем. Совпало и PO подтвердил → '
          f'python3 {Path(__file__).name} lock {team.slug}')
    return EXIT_OK


def cmd_check(args):
    """Проверить готовый JSON без сборщика и без JIRA: объект команды или снимок-массив.

    Нужен автору своего сборщика (выход на любом языке) и для вопроса «почему слайд
    пустой»: схема и инварианты — как при сборе, плюс покрытие экранов данными.
    """
    path = Path(args.file).resolve()
    if not path.is_file():
        raise RunFailure(f'нет файла {path}', code=EXIT_CONFIG)
    try:
        doc = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise RunFailure(f'{path} не разбирается как JSON ({exc})') from exc
    teams = doc if isinstance(doc, list) else [doc]
    ok = True
    for team in teams:
        if not isinstance(team, dict):
            print('✗ элемент не объект команды')
            ok = False
            continue
        core = {k: v for k, v in team.items() if k not in build.OVERLAY_FIELDS and k != '_comment'}
        report = validate_mod.check(core)
        print(f'[{core.get("slug", "?")}] {core.get("team", "")}')
        for line in report.lines():
            print(line)
        if report.ok:
            for line in validate_mod.coverage_lines(core, full=args.all):
                print(line)
        ok = ok and report.ok
        print()
    print('✓ форма и инварианты в порядке' if ok else '✗ JSON не проходит контракт: поправьте сборщик, не файл')
    return EXIT_OK if ok else EXIT_ERROR


def cmd_lock(args):
    cfg = config_mod.load(args.config)
    team = cfg.team(args.slug)
    entry = config_mod.write_lock(cfg, team.slug, team.digest(), now_iso(args.now),
                                  {'collector': team.collector_name,
                                   'version': config_mod.PLUGIN_VERSION})
    print(f'lock записан: {team.slug} sha {entry["sha256"][:7]} '
          f'({entry["validatedAt"]}) → {cfg.lock_path.name}')
    return EXIT_OK


def cmd_new(args):
    # конфиг может быть ещё не дописан — на этом шаге команды в нём как раз нет
    try:
        cfg = config_mod.load(args.config) if Path(args.config).is_file() else None
    except config_mod.ConfigError:
        cfg = None
    root = cfg.root if cfg else Path(args.config).resolve().parent
    src = Path(__file__).resolve().parent.parent / 'templates' / args.lang
    if not src.is_dir():
        print(f'нет шаблона для языка «{args.lang}». Есть: '
              f'{", ".join(sorted(p.name for p in src.parent.iterdir() if p.is_dir()))}')
        return EXIT_CONFIG
    dest = root / 'collectors' / args.slug
    if dest.exists() and any(dest.iterdir()):
        print(f'каталог уже есть и не пуст: {dest}')
        return EXIT_CONFIG
    dest.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir()):
        if item.is_file() and not item.name.endswith('.pyc'):
            shutil.copy2(item, dest / item.name)
    entry = sorted(p.name for p in dest.iterdir())[0]
    print(f'шаблон скопирован: {dest}')
    print('Дальше:')
    print(f'  1. Правьте точки «# TEAM RULE:» в {dest / entry}')
    print(f'  2. Опишите команду в конфиге:\n'
          f'     [[teams]]\n     slug = "{args.slug}"\n     name = "…"\n     board = 0\n'
          f'     [teams.collector]\n     cmd = ["python3", "collector.py"]\n'
          f'     cwd = "./collectors/{args.slug}"')
    print(f'  3. python3 {Path(__file__).name} validate {args.slug} --sample 5')
    return EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(description='Runner отчёта actual-sprint')
    ap.add_argument('--config', default=DEFAULT_CONFIG, help=f'по умолчанию {DEFAULT_CONFIG}')
    ap.add_argument('--now', default=None, help='ISO-время отчёта; по умолчанию текущее')
    sub = ap.add_subparsers(dest='cmd')

    sub.add_parser('doctor', help='проверить стенд локально, без похода в JIRA')

    p_run = sub.add_parser('run', help='собрать отчёт по всем командам конфига')
    p_run.add_argument('--only', default=None, help='список slug через запятую')

    p_merge = sub.add_parser(
        'merge', help='собрать единый HTML из сайдкаров команд (без похода в JIRA)')
    p_merge.add_argument('slugs', nargs='+',
                         help='slug команды или явный путь к сайдкару (список)')
    p_merge.add_argument('--workspace', action='append', default=[],
                         help='корень workspace для поиска сайдкаров (repeatable)')
    p_merge.add_argument('--output', default=None, help='куда писать HTML (по умолчанию output конфига)')
    p_merge.add_argument('--stale-ok', action='store_true', default=False,
                         help='принять сайдкар старше порога свежести (с пометкой)')
    p_merge.add_argument('--stale-hours', type=float, default=DEFAULT_STALE_HOURS,
                         help=f'порог свежести сайдкара в часах (по умолчанию {DEFAULT_STALE_HOURS})')

    p_render = sub.add_parser(
        'render', help='пересобрать HTML из снимка данных и инсайдов (без похода в JIRA)')
    p_render.add_argument('--data', default=None, help='снимок данных (по умолчанию data конфига)')
    p_render.add_argument('--output', default=None, help='куда писать HTML (по умолчанию output конфига)')

    p_val = sub.add_parser('validate', help='прогнать одну команду: схема, инварианты, выборка')
    p_val.add_argument('slug')
    p_val.add_argument('--sample', type=int, default=5)
    p_val.add_argument('--seed', type=int, default=None)

    p_check = sub.add_parser('check', help='проверить готовый JSON: схема, инварианты, покрытие экранов')
    p_check.add_argument('file', help='объект команды или снимок-массив (reports/sprint-report.data.json)')
    p_check.add_argument('--all', action='store_true', help='показать все экраны, не только пробелы')

    p_lock = sub.add_parser('lock', help='записать хеш проверенного сборщика')
    p_lock.add_argument('slug')

    p_new = sub.add_parser('new', help='скопировать шаблон сборщика под команду')
    p_new.add_argument('slug')
    p_new.add_argument('--lang', default='python')

    args = ap.parse_args(argv)
    handlers = {'run': cmd_run, 'merge': cmd_merge, 'render': cmd_render, 'validate': cmd_validate, 'check': cmd_check,
                'lock': cmd_lock, 'new': cmd_new, 'doctor': cmd_doctor}
    if not args.cmd:
        args.cmd = 'run'
        args.only = None
    try:
        return handlers[args.cmd](args)
    except config_mod.ConfigError as exc:
        print(f'конфиг: {exc}')
        return EXIT_CONFIG
    except build.BuildError as exc:
        print(f'сборка страницы: {exc}')
        return EXIT_ERROR
    except RunFailure as exc:
        print(f'✗ {exc}')
        return exc.code


if __name__ == '__main__':
    sys.exit(main())
