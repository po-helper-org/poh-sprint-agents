#!/usr/bin/env python3
"""Краткий текстовый статус спринта для чата — из снимка данных actual-sprint.

Модель здесь ничего не считает и не формулирует: текст целиком собирается кодом
из того же снимка, что и HTML-страница, поэтому цифры в чате и на странице одни.
Форма отчёта фиксирована — одинаковый снимок даёт одинаковый текст.

    status.py                        # из снимка по конфигу, без похода в JIRA
    status.py --refresh              # сначала пересобрать отчёт runner'ом, потом текст
    status.py --team team-a          # одна команда
    status.py --data demo-teams.json # любой файл формата TEAMS (демо, тесты)

Коды выхода: 0 — текст напечатан (в том числе на устаревших данных, с пометкой),
2 — нет конфига или снимка, 1 — снимок не читается. При ненулевом коде в stdout
всё равно идёт одна строка для человека: cron-доставка покажет её как есть.
"""
import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACTUAL = HERE.parent / 'actual-sprint'
RUNNER = ACTUAL / 'runner' / 'run.py'
for _p in (ACTUAL / 'runner', ACTUAL / 'contract'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import buckets as buckets_mod  # noqa: E402

EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2
DEFAULT_CONFIG = 'sprint-report.config.toml'

STALE_DAYS = 3          # как на странице: дольше — «стоит без движения»
MAX_ATTENTION = 5       # строк «Внимание» на команду; остальное числом
MAX_RISKS = 3           # задач из зоны риска поимённо
MAX_EPICS = 8           # строк эпиков; остальное числом
TITLE_LEN = 48

BUCKET_LABELS = [('open', 'открыто'), ('blocked', 'блок'), ('progress', 'в работе'),
                 ('testing', 'тест'), ('review', 'ревью'), ('done', 'готово')]
ACTIVE = {'progress', 'testing', 'review'}


class StatusError(Exception):
    def __init__(self, message, code=EXIT_ERROR):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ помощники

def parse_ts(value):
    if not value:
        return None
    value = value.strip().replace('Z', '+00:00')
    # JIRA отдаёт смещение без двоеточия: +0300
    if len(value) > 5 and value[-5] in '+-' and value[-3] != ':':
        value = value[:-2] + ':' + value[-2:]
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def ddmm(value):
    d = value if isinstance(value, date) else date.fromisoformat(value[:10])
    return d.strftime('%d.%m')


def short(text, limit=TITLE_LEN):
    text = ' '.join((text or '').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def person(name):
    """«Фамилия Имя Отчество» → «Фамилия И.»; не назначен → «без исполнителя»."""
    if not name:
        return 'без исполнителя'
    parts = name.split()
    return parts[0] if len(parts) == 1 else f'{parts[0]} {parts[1][0]}.'


def plural(n, one, few, many):
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def days_word(n):
    return 'меньше дня' if n == 0 else f'{n} {plural(n, "день", "дня", "дней")}'


def signed(n):
    return f'+{n}' if n > 0 else str(n)


# ------------------------------------------------------------------ разбор команды

class TeamView:
    """Всё, что нужно тексту, посчитанное из объекта команды (team.schema.json)."""

    def __init__(self, team, rules):
        self.t = team
        self.rules = rules
        self.status_map = team.get('statusMap') or {}
        self.collected = parse_ts(team['_meta']['collectedAt'])

    def bucket(self, status, category):
        return self.status_map.get(status) or self.rules.bucket(status, category)

    def age(self, iso):
        ts = parse_ts(iso)
        if not ts or not self.collected:
            return None
        # одна из меток без смещения — сравниваем как местное время сбора
        if (ts.tzinfo is None) != (self.collected.tzinfo is None):
            ts = ts.replace(tzinfo=self.collected.tzinfo)
        return max(0, (self.collected - ts).days)

    # --- сроки и темп: burndown, та же идеальная прямая, что на графике страницы
    def pace(self):
        bd = self.t['burndown']
        days = bd['days']
        past = [d for d in days if not d['future']]
        today = past[-1] if past else days[0]
        idx = days.index(today)
        workdays = [d for d in days if not d['weekend']]
        passed = sum(1 for d in workdays if not d['future'])
        left = sum(1 for d in workdays if d['future'])
        span = len(days) - 1
        ideal = round(days[0]['scope'] * (1 - idx / span)) if span else 0
        prev = days[idx - 1] if idx > 0 else None
        overdue = bool(self.collected) and self.collected.date().isoformat() > bd['end']
        return {'today': today, 'prev': prev, 'ideal': ideal, 'end': bd['end'],
                'workday': max(passed, 1) if past else 0, 'workdays': len(workdays),
                'left': left, 'started': bool(past), 'overdue': overdue}

    def split(self):
        """Статусы всех задач активного спринта (с подзадачами) — последний столбец velocity."""
        sprints = self.t['velocity']['sprints']
        return sprints[-1]['split'] if sprints else None

    # --- что требует внимания: блокеры и то, что стоит, по всей иерархии эпиков
    def items(self):
        for epic in self.t['epics']:
            for st in epic['stories']:
                yield epic, st['key'], st['title'], st
                for sub in st['subtasks']:
                    yield epic, sub['key'], sub['summary'], sub

    def attention(self):
        blocked, stale = [], []
        for _, key, title, it in self.items():
            b = self.bucket(it['status'], it.get('category', ''))
            age = self.age(it.get('statusChanged'))
            row = (key, title, it['status'], age, it.get('assignee'))
            if b == 'blocked':
                blocked.append(row)
            elif b in ACTIVE and age is not None and age > STALE_DAYS:
                stale.append(row)
        order = lambda r: (-(r[3] or 0), r[0])  # noqa: E731
        return sorted(blocked, key=order), sorted(stale, key=order)

    def risks(self):
        """Зона риска только по задачам активного спринта.

        control.*.risks сборщик считает по всем sprints_back спринтам — для графика
        это правильно, а в статусе спринта хвосты прошлых спринтов раздували бы число
        сверх объёма самого спринта.
        """
        in_sprint = {key for _, key, _, _ in self.items()}
        ctl = self.t['control']
        rows, medians = {}, []
        for group in ('stories', 'subtasks'):
            chart = ctl.get(group) or {}
            picked = [r for r in chart.get('risks', []) if r['key'] in in_sprint]
            if chart.get('median') is not None and picked:
                medians.append(chart['median'])
            for r in picked:
                rows.setdefault(r['key'], r)
        return sorted(rows.values(), key=lambda r: (-r['elapsed'], r['key'])), medians

    def epics(self):
        out = []
        for epic in self.t['epics']:
            counts = dict.fromkeys(buckets_mod.BUCKETS, 0)
            for st in epic['stories']:
                counts[self.bucket(st['status'], st.get('category', ''))] += 1
                for sub in st['subtasks']:
                    counts[self.bucket(sub['status'], sub.get('category', ''))] += 1
            title = epic.get('epicTitle') or epic.get('epicKey') or 'Без эпика'
            out.append((title, counts))
        return out


# ------------------------------------------------------------------ текст

def render_team(team, rules):
    v = TeamView(team, rules)
    lines = []
    pace = v.pace()
    today, prev = pace['today'], pace['prev']

    head = f'{team["team"]} · {team["sprintName"]}'
    if not pace['started']:
        head += f' — стартует {ddmm(team["burndown"]["start"])}, до {ddmm(pace["end"])}'
    elif pace['overdue']:
        head += f' — срок истёк {ddmm(pace["end"])}, в JIRA спринт не закрыт'
    elif pace['left'] == 0:
        head += f' — последний день {ddmm(pace["end"])}'
    else:
        head += (f' — день {pace["workday"]} из {pace["workdays"]}, до {ddmm(pace["end"])} '
                 f'(осталось {pace["left"]} раб. {plural(pace["left"], "день", "дня", "дней")})')
    lines.append(head)

    scope, closed, remaining = today['scope'], today['closed'], today['remaining']
    pct = round(100 * closed / scope) if scope else 0
    line = f'Готово {closed} из {scope} ({pct}%)'
    if pace['started']:
        gap = remaining - pace['ideal']
        if gap > 0:
            line += f' · отстаём от идеального темпа на {gap}'
        elif gap < 0:
            line += f' · опережаем идеальный темп на {-gap}'
        else:
            line += ' · идём по идеальному темпу'
    lines.append(line)

    if prev:
        d_closed = today['closed'] - prev['closed']
        d_scope = today['scope'] - prev['scope']
        parts = [f'закрыто {signed(d_closed)}' if d_closed else 'закрытий нет']
        if d_scope:
            parts.append(f'объём {signed(d_scope)}')
        lines.append('За сутки: ' + ', '.join(parts))

    split = v.split()
    if split:
        lines.append('Статусы: ' + ' · '.join(f'{label} {split.get(b, 0)}'
                                              for b, label in BUCKET_LABELS))

    blocked, stale = v.attention()
    shown = []
    for key, title, status, age, who in blocked:
        tail = f', {days_word(age)}' if age is not None else ''
        shown.append(f'· блок: {key} {short(title)} — {person(who)}, «{status}»{tail}')
    for key, title, status, age, who in stale:
        shown.append(f'· стоит {days_word(age)}: {key} {short(title)} — {person(who)}, «{status}»')
    if shown:
        lines.append('')
        lines.append(f'Внимание: блокеров {len(blocked)}, без движения >{STALE_DAYS} дн. — {len(stale)}')
        lines.extend(shown[:MAX_ATTENTION])
        if len(shown) > MAX_ATTENTION:
            lines.append(f'· ещё {len(shown) - MAX_ATTENTION} — на странице отчёта')

    risks, medians = v.risks()
    if risks:
        top = ', '.join(f'{r["key"]} ({round(r["elapsed"])} дн.)' for r in risks[:MAX_RISKS])
        med = f' {max(medians):g} дн.' if len(medians) == 1 else ''
        lines.append(f'Зона риска: {len(risks)} в работе дольше медианы{med}; '
                     f'дольше всех — {top}')

    epics = v.epics()
    if epics:
        lines.append('')
        lines.append('Эпики (готово/всего):')
        for title, c in epics[:MAX_EPICS]:
            total = sum(c.values())
            extra = f', блок {c["blocked"]}' if c['blocked'] else ''
            lines.append(f'· {short(title)} — {c["done"]}/{total}{extra}')
        if len(epics) > MAX_EPICS:
            lines.append(f'· ещё {len(epics) - MAX_EPICS} эпиков — на странице отчёта')

    return lines


def render(teams, rules, now, max_age_h, refresh_error=None):
    out = []
    if refresh_error:
        out.append(f'⚠ Свежий сбор не удался: {refresh_error}. Ниже — последний снимок.')
        out.append('')
    for i, team in enumerate(teams):
        if i:
            out.append('')
            out.append('—')
            out.append('')
        out.extend(render_team(team, rules))

    stamps = sorted({t['_meta']['collectedAt'] for t in teams})
    collected = parse_ts(stamps[0])
    footer = f'Данные JIRA на {collected.strftime("%d.%m %H:%M")}' if collected else 'Данные JIRA'
    warnings = sum(len(t['_meta'].get('warnings', [])) for t in teams)
    if warnings:
        footer += f' · предупреждений сбора {warnings}'
    out.append('')
    if collected and now and collected.tzinfo and now - collected > timedelta(hours=max_age_h):
        hours = int((now - collected).total_seconds() // 3600)
        out.append(f'⚠ {footer} — старше {hours} ч, цифры могут не совпадать с доской')
    else:
        out.append(footer)
    return '\n'.join(out) + '\n'


# ------------------------------------------------------------------ CLI

def snapshot_path(args):
    if args.data:
        return Path(args.data)
    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        raise StatusError(f'конфиг {cfg_path} не найден — отчёт по спринту ещё не настроен '
                          f'(/sprint-setup)', EXIT_CONFIG)
    import config as config_mod
    try:
        return config_mod.load(cfg_path).data
    except config_mod.ConfigError as exc:
        raise StatusError(f'конфиг: {exc}', EXIT_CONFIG) from exc


def refresh(args):
    """Пересобрать отчёт runner'ом. None — успех, иначе короткая причина отказа."""
    cmd = [sys.executable, str(RUNNER), '--config', args.config, 'run']
    if args.team:
        cmd += ['--only', args.team]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    for line in (proc.stdout + proc.stderr).splitlines():
        print(line, file=sys.stderr)
    if proc.returncode == 0:
        return None
    return failure_reason(proc.stdout) or f'runner вышел с кодом {proc.returncode}'


def failure_reason(stdout):
    """Первая причина отказа из вывода runner вместе с её подсказкой.

    Runner печатает отказ команды строкой `[slug] ✗ …`, а следующий шаг — с отступом
    на строках ниже; в чат идут обе, без хвоста про HTML.
    """
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        text = line.strip()
        if not ('✗' in text or text.startswith('конфиг:')):
            continue
        parts = [text.replace('✗ ', '', 1)]
        for more in lines[i + 1:]:
            if not more.startswith(' ') or not more.strip():
                break
            parts.append(more.strip())
        reason = ' '.join(p.rstrip('.') for p in parts)
        return reason.replace(' HTML не сгенерирован', '').rstrip('.')
    return None


def load_teams(path, only=None):
    if not path.is_file():
        raise StatusError(f'снимка данных нет ({path}) — сначала соберите отчёт: /actual-sprint '
                          f'или status.py --refresh', EXIT_CONFIG)
    try:
        teams = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise StatusError(f'{path} не разбирается как JSON ({exc})') from exc
    if not isinstance(teams, list) or not teams:
        raise StatusError(f'{path}: ожидается непустой массив команд (формат TEAMS)')
    if only:
        teams = [t for t in teams if t.get('slug') == only]
        if not teams:
            raise StatusError(f'в снимке нет команды «{only}»', EXIT_CONFIG)
    return teams


def main(argv=None):
    ap = argparse.ArgumentParser(description='Краткий текстовый статус спринта для чата')
    ap.add_argument('--config', default=DEFAULT_CONFIG, help=f'по умолчанию {DEFAULT_CONFIG}')
    ap.add_argument('--data', default=None, help='файл TEAMS вместо снимка из конфига')
    ap.add_argument('--team', default=None, help='slug одной команды')
    ap.add_argument('--refresh', action='store_true',
                    help='сначала собрать свежие данные runner\'ом (нужны VPN и токен)')
    ap.add_argument('--max-age', type=float, default=12,
                    help='через сколько часов снимок помечается устаревшим (по умолчанию 12)')
    ap.add_argument('--now', default=None, help='ISO-время «сейчас» — для тестов')
    args = ap.parse_args(argv)

    try:
        refresh_error = None
        if args.refresh:
            if args.data:
                raise StatusError('--refresh и --data вместе не имеют смысла', EXIT_CONFIG)
            refresh_error = refresh(args)
        teams = load_teams(snapshot_path(args), args.team)
        now = parse_ts(args.now) if args.now else datetime.now().astimezone()
        sys.stdout.write(render(teams, buckets_mod.load(), now, args.max_age, refresh_error))
        return EXIT_OK
    except StatusError as exc:
        print(f'Статус спринта не собран: {exc}')
        return exc.code


if __name__ == '__main__':
    sys.exit(main())
