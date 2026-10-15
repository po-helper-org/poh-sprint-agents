#!/usr/bin/env python3
"""Отчёт по блокерам команды: где и почему команда ждала других, где узкие места.

    blockers.py fetch --team slug [--quarter 2026Q3] [--to 2026-10-14]   снимок задач из JIRA
    blockers.py facts --team slug [...]   ожидания по рабочим дням → stdout и файл фактов
    blockers.py check --team slug [...]   файл агента против фактов
    blockers.py apply --team slug [...]   check + страница reports/blockers-<slug>-<квартал>.html

Данные собирает и считает скрипт; агент только раскладывает ожидания по сторонам
(кого и чего ждали) и пишет вывод. Транспорт снимка — MCP-сервер Atlassian
(params.blockers.mcp — команда запуска сервера) или REST с личным токеном.
Коды выхода: 0 — успех, 1 — файл агента не принят или JIRA не ответила, 2 — нет
конфига, снимка или фактов.
"""
import argparse
import json
import shlex
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACTUAL = HERE.parent / 'actual-sprint'
for _p in (HERE, ACTUAL / 'runner'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import report as report_mod  # noqa: E402
import source as source_mod  # noqa: E402
import waits as waits_mod  # noqa: E402

DEFAULT_CONFIG = 'sprint-report.config.toml'
EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2


class BlockersError(Exception):
    def __init__(self, message, code=EXIT_ERROR):
        super().__init__(message)
        self.code = code


def load_config(path):
    import config as config_mod
    if not Path(path).is_file():
        raise BlockersError(f'конфиг {path} не найден — отчёт ещё не настроен (/sprint-setup)', EXIT_CONFIG)
    try:
        return config_mod.load(path)
    except config_mod.ConfigError as exc:
        raise BlockersError(f'конфиг: {exc}', EXIT_CONFIG) from exc


def default_quarter(to):
    """Первый месяц квартала — отчёт за прошлый квартал с хвостом текущего месяца
    (как эталон: III квартал + 1–14 октября). Дальше — текущий квартал."""
    q = (to.month - 1) // 3 + 1
    if (to.month - 1) % 3 == 0:
        return f'{to.year - (q == 1)}Q{4 if q == 1 else q - 1}'
    return f'{to.year}Q{q}'


class Job:
    """Команда, период и пути файлов одного отчёта."""

    def __init__(self, cfg, args):
        import config as config_mod
        try:
            self.team = cfg.team(args.team) if args.team else cfg.teams[0]
        except config_mod.ConfigError as exc:
            raise BlockersError(str(exc), EXIT_CONFIG) from exc
        self.cfg = cfg
        self.params = dict(self.team.params.get('blockers') or {})
        self.to = args.to or date.today().isoformat()
        self.quarter = args.quarter or default_quarter(date.fromisoformat(self.to))
        try:
            self.period = waits_mod.period(self.quarter, self.to, self.params.get('holidays', []))
        except waits_mod.FactsError as exc:
            raise BlockersError(str(exc), EXIT_CONFIG) from exc
        base = cfg.root / 'reports'
        stem = f'{self.team.slug}-{self.quarter}'
        self.snapshot = base / 'blockers' / f'{stem}.snapshot.json'
        self.facts = base / 'blockers' / f'{stem}.facts.json'
        self.doc = base / 'blockers' / f'{stem}.json'
        self.page = base / f'blockers-{stem}.html'

    def read(self, path, what, hint):
        if not path.is_file():
            raise BlockersError(f'{what} нет: {path}. {hint}', EXIT_CONFIG)
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise BlockersError(f'{path} не разбирается как JSON ({exc})') from exc


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def dump_facts(facts):
    """Факты для агента: шапка с отступами, ожидания и сигналы — по строке на запись."""
    head = {k: v for k, v in facts.items() if k not in ('waits', 'signals')}
    one = lambda x: json.dumps(x, ensure_ascii=False, separators=(',', ':'))  # noqa: E731
    lines = [json.dumps(head, ensure_ascii=False, indent=1)[:-2] + ',']
    for name in ('waits', 'signals'):
        items = facts[name]
        lines.append(f' "{name}": [' + ('' if items else '],'))
        for n, item in enumerate(items):
            lines.append('  ' + one(item) + (',' if n < len(items) - 1 else ''))
        if items:
            lines.append(' ],')
    lines[-1] = lines[-1].rstrip(',')
    lines.append('}')
    return '\n'.join(lines)


def now_iso(args):
    return args.now or datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


# ------------------------------------------------------------------ команды

def transport(job, args):
    mcp = args.mcp or job.params.get('mcp')
    if mcp:
        cmd = shlex.split(mcp) if isinstance(mcp, str) else list(mcp)
        return source_mod.McpTransport(cmd)
    import config as config_mod
    try:
        return source_mod.RestTransport(job.cfg.jira_url(), job.cfg.token(), job.cfg.ca_bundle,
                                        replay=job.params.get('replay'))
    except config_mod.ConfigError as exc:
        raise BlockersError(f'{exc}. Либо укажите MCP-сервер: params.blockers.mcp', EXIT_CONFIG) from exc


def cmd_fetch(job, args):
    jql = job.params.get('jql')
    if not jql:
        raise BlockersError(f'у команды {job.team.slug} нет params.blockers.jql — какие задачи считать '
                            f'задачами команды (например, project = KEY)', EXIT_CONFIG)
    team = {'slug': job.team.slug, 'name': job.team.name}
    try:
        with transport(job, args) as tr:
            snap = source_mod.fetch(tr, jql, job.period['from'], job.period['to'], team, now_iso(args))
    except source_mod.SourceError as exc:
        raise BlockersError(str(exc)) from exc
    write_json(job.snapshot, snap)
    print(f'снимок ✓   задач {len(snap["issues"])}   {snap["transport"]}   → {job.snapshot}')
    return EXIT_OK


def cmd_facts(job, args):
    snap = job.read(job.snapshot, 'снимка задач', 'Сначала blockers.py fetch')
    try:
        facts = waits_mod.facts(snap, job.period, job.params)
    except waits_mod.FactsError as exc:
        raise BlockersError(str(exc), EXIT_CONFIG) from exc
    write_json(job.facts, facts)
    if args.quiet:
        print(f'факты ✓   ожиданий {len(facts["waits"])}   → {job.facts}')
    else:
        print(dump_facts(facts))
    return EXIT_OK


def cmd_check(job, args, quiet=False):
    facts = job.read(job.facts, 'фактов', 'Сначала blockers.py facts')
    doc = job.read(Path(args.file).resolve() if args.file else job.doc, 'файла разбора',
                   'Запишите его по фактам (SKILL.md, шаг 2)')
    errors, warnings, view = report_mod.check(doc, facts)
    for line in errors:
        print(f'✗ {line}')
    for line in warnings:
        print(f'⚠ {line}')
    if errors:
        print(f'разбор не принят: ошибок {len(errors)}. Поправьте файл и проверьте снова.')
        return EXIT_ERROR, None
    if not quiet:
        print(f'разбор ✓   случаев {len(view["cases"])}   предупреждений {len(warnings)}')
        print_tables(view)
    return EXIT_OK, view


def print_tables(view):
    """Числа страницы — агент пишет по ним вывод (lead, sections)."""
    wins = view['period']['windows']
    head = ' | '.join(f'{w["label"]} (из {w["workdays"]})' for w in wins)
    print(f'\nдней хотя бы с одним ожиданием: ' + ' | '.join(
        f'{w["label"]} {view["kpi"][w["id"]]["any"]}, внешних {view["kpi"][w["id"]]["external"]}' for w in wins))
    print('задаче-дней ожидания: ' + ' | '.join(
        f'{w["label"]} всего {view["kpi"][w["id"]]["taskDays"]}, других команд {view["kpi"][w["id"]]["externalTaskDays"]}'
        for w in wins))
    print(f'\nкого ждали — задаче-дней / дней: {head}')
    for r in view['sides']:
        print(f'  {r["name"]}: ' + ' | '.join(f'{r["taskDays"][w["id"]]} / {r["win"][w["id"]]}' for w in wins)
              + f'   случаев {r["cases"]}, открыто {r["open"]}')
    print('\nслучаи — рабочих дней:')
    for c in view['cases']:
        print(f'  {c["when"]}  {c["days"]}  {c["side"]}: {c["what"]}  [{c["state"]}]  {", ".join(c["keys"])}')


def cmd_apply(job, args):
    code, view = cmd_check(job, args, quiet=True)
    if code != EXIT_OK:
        return code
    job.page.parent.mkdir(parents=True, exist_ok=True)
    job.page.write_text(report_mod.render(view, now_iso(args)), encoding='utf-8')
    print(f'разбор ✓   случаев {len(view["cases"])}   открыто {view["numbers"]["open"]}   → {job.page}')
    return EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(description='Отчёт по блокерам команды')
    ap.add_argument('--config', default=DEFAULT_CONFIG, help=f'по умолчанию {DEFAULT_CONFIG}')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name, text in (('fetch', 'снимок задач из JIRA'), ('facts', 'ожидания по рабочим дням'),
                       ('check', 'проверить файл агента'), ('apply', 'проверить и собрать страницу')):
        p = sub.add_parser(name, help=text)
        p.add_argument('--team', default=None, help='slug команды (по умолчанию первая в конфиге)')
        p.add_argument('--quarter', default=None, help='квартал, например 2026Q3')
        p.add_argument('--to', default=None, help='дата отчёта YYYY-MM-DD (по умолчанию сегодня)')
        p.add_argument('--now', default=None, help='момент сборки для воспроизводимости')
        if name == 'fetch':
            p.add_argument('--mcp', default=None, help='команда запуска MCP-сервера Atlassian')
        if name == 'facts':
            p.add_argument('--quiet', action='store_true', help='только путь к файлу фактов')
        if name in ('check', 'apply'):
            p.add_argument('--file', default=None, help='файл разбора (по умолчанию reports/blockers/…json)')
    args = ap.parse_args(argv)
    try:
        job = Job(load_config(args.config), args)
        if args.cmd == 'check':
            return cmd_check(job, args)[0]
        return {'fetch': cmd_fetch, 'facts': cmd_facts, 'apply': cmd_apply}[args.cmd](job, args)
    except BlockersError as exc:
        print(f'✗ {exc}')
        return exc.code


if __name__ == '__main__':
    sys.exit(main())
