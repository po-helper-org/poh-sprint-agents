#!/usr/bin/env python3
"""Статус спринта одним PDF — из снимка данных actual-sprint.

Модель здесь ничего не считает и не формулирует: лист целиком собирается кодом
из того же снимка, что и HTML-страница /actual-sprint, поэтому цифры одни и те же,
а форма каждый раз одинаковая.

    status.py                        # из снимка по конфигу, без похода в JIRA
    status.py --refresh              # сначала пересобрать отчёт runner'ом
    status.py --team team-a          # одна команда
    status.py --data demo-teams.json # любой файл формата TEAMS (демо, тесты)
    status.py --html-only            # без печати в PDF (нет браузера, отладка макета)

stdout — готовое сообщение для чата: строка подписи и `MEDIA:<путь к PDF>`
(по этой метке Hermes отправляет файл вложением). Лог — в stderr.

Коды выхода: 0 — PDF собран (в том числе на устаревших данных, с пометкой),
2 — нет конфига, снимка или браузера, 1 — снимок не читается или печать упала.
При ненулевом коде в stdout одна строка для человека.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import model as model_mod  # noqa: E402
import page as page_mod  # noqa: E402
import pdf as pdf_mod  # noqa: E402

RUNNER = model_mod.ACTUAL / 'runner' / 'run.py'
EXIT_OK, EXIT_ERROR, EXIT_CONFIG = 0, 1, 2
DEFAULT_CONFIG = 'sprint-report.config.toml'


class StatusError(Exception):
    def __init__(self, message, code=EXIT_ERROR):
        super().__init__(message)
        self.code = code


def log(*parts):
    print(*parts, file=sys.stderr)


# ------------------------------------------------------------------ данные

def load_config(path):
    if not Path(path).is_file():
        raise StatusError(f'конфиг {path} не найден — отчёт по спринту ещё не настроен '
                          f'(/sprint-setup)', EXIT_CONFIG)
    import config as config_mod
    try:
        return config_mod.load(path)
    except config_mod.ConfigError as exc:
        raise StatusError(f'конфиг: {exc}', EXIT_CONFIG) from exc


def refresh(args):
    """Пересобрать отчёт runner'ом. None — успех, иначе короткая причина отказа."""
    cmd = [sys.executable, str(RUNNER), '--config', args.config, 'run']
    if args.team:
        cmd += ['--only', args.team]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    for line in (proc.stdout + proc.stderr).splitlines():
        log(line)
    if proc.returncode == 0:
        return None
    return failure_reason(proc.stdout) or f'runner вышел с кодом {proc.returncode}'


def failure_reason(stdout):
    """Первая причина отказа из вывода runner вместе с её подсказкой.

    Runner печатает отказ команды строкой `[slug] ✗ …`, а следующий шаг — с отступом
    на строках ниже; в сообщение идут обе, без хвоста про HTML.
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


# ------------------------------------------------------------------ сообщение

def caption(models, refresh_error, stale_hours):
    """Подпись к файлу: одна строка, плюс строка-предупреждение, если есть."""
    stamps = [m['collected'] for m in models if m['collected']]
    when = min(stamps).strftime('%d.%m %H:%M') if stamps else '—'
    names = ', '.join(m['team'] for m in models) if len(models) <= 3 else f'{len(models)} команд'
    lines = []
    if refresh_error:
        lines.append(f'⚠ Свежий сбор не удался: {refresh_error}. В PDF — последний снимок.')
    elif stale_hours:
        lines.append(f'⚠ Данные старше {stale_hours} ч — запустите с --refresh.')
    lines.append(f'Статус спринта на {when} — {names}')
    return lines


def stale_hours(models, now, max_age_h):
    stamps = [m['collected'] for m in models if m['collected'] and m['collected'].tzinfo]
    if not stamps or not now:
        return 0
    age = (now - min(stamps)).total_seconds()
    return int(age // 3600) if age > max_age_h * 3600 else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description='Статус спринта одним PDF для чата')
    ap.add_argument('--config', default=DEFAULT_CONFIG, help=f'по умолчанию {DEFAULT_CONFIG}')
    ap.add_argument('--data', default=None, help='файл TEAMS вместо снимка из конфига')
    ap.add_argument('--team', default=None, help='slug одной команды')
    ap.add_argument('--out', default=None,
                    help='куда писать PDF; по умолчанию рядом со снимком: sprint-status-<дата>.pdf')
    ap.add_argument('--refresh', action='store_true',
                    help='сначала собрать свежие данные runner\'ом (нужны VPN и токен)')
    ap.add_argument('--html-only', action='store_true', help='только HTML, без печати в PDF')
    ap.add_argument('--chrome', default=None, help='путь к Chrome/Chromium для печати')
    ap.add_argument('--max-age', type=float, default=12,
                    help='через сколько часов снимок помечается устаревшим (по умолчанию 12)')
    ap.add_argument('--now', default=None, help='ISO-время «сейчас» — для тестов')
    args = ap.parse_args(argv)

    try:
        refresh_error = None
        if args.data:
            if args.refresh:
                raise StatusError('--refresh и --data вместе не имеют смысла', EXIT_CONFIG)
            snapshot = Path(args.data)
        else:
            cfg = load_config(args.config)
            if args.refresh:
                refresh_error = refresh(args)
            snapshot = cfg.data
        teams = load_teams(snapshot, args.team)
        models = model_mod.build(teams)
        now = model_mod.parse_ts(args.now) if args.now else datetime.now().astimezone()

        html = page_mod.render(models, now, args.max_age, refresh_error)
        stamps = [m['collected'] for m in models if m['collected']]
        day = min(stamps).strftime('%Y-%m-%d') if stamps else 'snapshot'
        suffix = f'-{args.team}' if args.team else ''
        out = Path(args.out) if args.out else snapshot.parent / f'sprint-status{suffix}-{day}.pdf'
        out.parent.mkdir(parents=True, exist_ok=True)
        html_path = out.with_suffix('.html')
        html_path.write_text(html, encoding='utf-8')
        lines = caption(models, refresh_error, stale_hours(models, now, args.max_age))

        if args.html_only:
            log(f'HTML: {html_path}')
            print('\n'.join(lines))
            print(f'HTML: {html_path.resolve()}')
            return EXIT_OK
        browser = pdf_mod.find_browser(args.chrome)
        if not browser:
            raise StatusError(f'PDF не собран: нет Chrome/Chromium для печати (укажите --chrome или '
                              f'SPRINT_STATUS_CHROME). Страница без печати — {html_path.resolve()}',
                              EXIT_CONFIG)
        log(f'печать: {browser}')
        pdf_path = pdf_mod.print_pdf(html_path, out, browser)
        print('\n'.join(lines))
        print(f'MEDIA:{pdf_path}')
        return EXIT_OK
    except pdf_mod.PdfError as exc:
        print(f'Статус спринта не собран: PDF — {exc}')
        return EXIT_ERROR
    except StatusError as exc:
        print(f'Статус спринта не собран: {exc}')
        return exc.code


if __name__ == '__main__':
    sys.exit(main())
