#!/usr/bin/env python3
"""Конфиг, lock-файл и хеши сборщиков.

Формат конфига — TOML: читается stdlib `tomllib` (Python 3.11+), допускает
комментарии и не тянет зависимостей (плагин ставится копированием файлов).

Ошибки конфига — исключение ConfigError с текстом, который называет команду и поле:
runner печатает его как есть (НФТ-9).
"""
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path

PROTOCOL = 1
PLUGIN_VERSION = '1.0.0'
BASE_COLLECTOR = Path(__file__).resolve().parent.parent / 'templates' / 'python' / 'collector.py'
SCHEMA_PATH = Path(__file__).resolve().parent.parent / 'contract' / 'team.schema.json'
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / 'resources' / 'report_template.html'

SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')
DEFAULT_TIMEOUT = 300
HASH_SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', '.mypy_cache', '.pytest_cache'}
HASH_SKIP_SUFFIX = ('.pyc', '.pyo', '.log', '.json.gz')


class ConfigError(Exception):
    """Конфиг нельзя использовать. Текст уже готов к показу человеку."""


class Team:
    """Одна команда конфига: что запускать и с какими params."""

    def __init__(self, slug, name, board, collector, params, root):
        self.slug = slug
        self.name = name
        self.board = board
        self.params = params
        self.root = root
        self.is_base = collector == 'base'
        spec = {} if self.is_base else collector
        self.cmd = list(spec.get('cmd', []))
        self.cwd = (root / spec['cwd']).resolve() if spec.get('cwd') else root
        self.build = list(spec.get('build', [])) or None
        self.timeout = int(spec.get('timeout', DEFAULT_TIMEOUT))

    @property
    def collector_name(self):
        return 'base' if self.is_base else self.slug

    def argv(self):
        """Команда запуска. Для base — интерпретатор плагина и шаблонный сборщик."""
        import sys
        if self.is_base:
            return [sys.executable, str(BASE_COLLECTOR)]
        exe = self.cmd[0]
        if exe.startswith('.') or '/' in exe:
            exe = str((self.cwd / exe).resolve()) if not os.path.isabs(exe) else exe
        return [exe] + self.cmd[1:]

    def digest(self):
        """sha256 сборщика: для base — по шаблону и версии плагина, для своего — по каталогу (ФТ-8)."""
        if self.is_base:
            h = hashlib.sha256()
            h.update(f'base@{PLUGIN_VERSION}\n'.encode())
            h.update(BASE_COLLECTOR.read_bytes())
            return h.hexdigest()
        return dir_digest(self.cwd, skip=self._built_artifacts())

    def _built_artifacts(self):
        """Собираемый бинарник исключаем из хеша: его пересборка не меняет исходники."""
        if not self.build:
            return set()
        out = self.cmd[0] if self.cmd else ''
        return {Path(out).name} if out else set()


def dir_digest(path, skip=()):
    """Устойчивый хеш каталога: относительные пути и содержимое, в отсортированном порядке."""
    path = Path(path)
    if not path.is_dir():
        raise ConfigError(f'каталог сборщика не найден: {path}')
    h = hashlib.sha256()
    files = []
    for p in sorted(path.rglob('*')):
        if not p.is_file():
            continue
        if set(p.relative_to(path).parts) & HASH_SKIP_DIRS or p.name in skip:
            continue
        if p.name.endswith(HASH_SKIP_SUFFIX):
            continue
        files.append(p)
    for p in files:
        h.update(str(p.relative_to(path)).encode())
        h.update(b'\0')
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


class Config:
    def __init__(self, path, data):
        self.path = Path(path).resolve()
        self.root = self.path.parent
        self.raw = data
        self.strict = bool(data.get('strict', True))
        jira = data.get('jira', {})
        self.url_env = jira.get('url_env', 'JIRA_URL')
        self.token_env = jira.get('token_env', 'JIRA_PERSONAL_TOKEN')
        self.ca_bundle = (self.root / jira['ca_bundle']).resolve() if jira.get('ca_bundle') else None
        self.output = (self.root / data.get('output', './reports/sprint-report.html')).resolve()
        self.notes = (self.root / data.get('notes', './reports/sprint-report-notes.json')).resolve()
        self.lock_path = self.root / data.get('lock', './sprint-report.lock.json')
        self.teams = []

    def team(self, slug):
        for t in self.teams:
            if t.slug == slug:
                return t
        known = ', '.join(t.slug for t in self.teams) or '—'
        raise ConfigError(f'команды «{slug}» нет в конфиге. Есть: {known}')

    def jira_url(self):
        url = os.environ.get(self.url_env, '').strip().rstrip('/')
        if not url:
            raise ConfigError(f'переменная окружения {self.url_env} с адресом JIRA не задана '
                              f'(jira.url_env в {self.path.name})')
        return url

    def token(self):
        tok = os.environ.get(self.token_env, '')
        if not tok:
            raise ConfigError(f'переменная окружения {self.token_env} с токеном JIRA не задана '
                              f'(jira.token_env в {self.path.name})')
        return tok


def load(path):
    """Читает и проверяет конфиг до любого запуска сборщиков (ФТ-5)."""
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f'конфиг не найден: {path}')
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f'{path.name}: не разбирается как TOML — {exc}') from exc

    version = data.get('version')
    if version != 1:
        raise ConfigError(f'{path.name}: version должен быть 1, получено {version!r}')

    cfg = Config(path, data)
    teams = data.get('teams')
    if not isinstance(teams, list) or not teams:
        raise ConfigError(f'{path.name}: нет ни одной команды — нужен хотя бы один блок [[teams]]')

    seen = set()
    for i, raw in enumerate(teams):
        where = f'{path.name}: [[teams]] #{i + 1}'
        slug = raw.get('slug')
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            raise ConfigError(f'{where}: slug {slug!r} пуст или небезопасен для путей '
                              f'(нужно [a-z0-9] и далее [a-z0-9._-])')
        if slug in seen:
            raise ConfigError(f'{where}: slug «{slug}» повторяется — он же REPORT_ID заметок, '
                              f'должен быть уникален')
        seen.add(slug)
        where = f'{path.name}: команда «{slug}»'
        name = raw.get('name')
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f'{where}: поле name пусто')
        board = raw.get('board')
        if not isinstance(board, int) or isinstance(board, bool):
            raise ConfigError(f'{where}: board должен быть числом (id agile-доски), получено {board!r}')
        collector = raw.get('collector', 'base')
        params = raw.get('params', {})
        if not isinstance(params, dict):
            raise ConfigError(f'{where}: params должен быть таблицей')
        if collector != 'base':
            if not isinstance(collector, dict):
                raise ConfigError(f'{where}: collector — либо "base", либо таблица с cmd')
            cmd = collector.get('cmd')
            if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) for c in cmd):
                raise ConfigError(f'{where}: collector.cmd должен быть непустым списком строк')
        cfg.teams.append(Team(slug, name, board, collector, params, cfg.root))

    for t in cfg.teams:
        where = f'{path.name}: команда «{t.slug}»'
        if t.is_base:
            continue
        if not t.cwd.is_dir():
            raise ConfigError(f'{where}: collector.cwd не найден — {t.cwd}')
        exe = Path(t.argv()[0])
        # бинарник может появиться только после build — тогда проверяем исходники, не его
        if not t.build and not exe.exists() and '/' in t.cmd[0]:
            raise ConfigError(f'{where}: collector.cmd не найден — {exe}. '
                              f'Добавьте collector.build, если файл собирается.')
    if cfg.ca_bundle and not cfg.ca_bundle.is_file():
        raise ConfigError(f'{path.name}: jira.ca_bundle не найден — {cfg.ca_bundle}')
    return cfg


# ---------------------------------------------------------------- lock-файл

def _lock_document(cfg, strict=True):
    """Содержимое lock-файла целиком. Нет файла — пустой документ."""
    empty = {'version': 1, 'collectors': {}}
    if not cfg.lock_path.is_file():
        return empty
    try:
        return json.loads(cfg.lock_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        if not strict:
            return empty
        raise ConfigError(f'{cfg.lock_path.name} повреждён ({exc}). Удалите его и повторите '
                          f'/collector-validate по каждой команде.') from exc


def read_lock(cfg):
    """{slug: запись}. Пишет этот файл только runner, человек его не редактирует (ФТ-6)."""
    return _lock_document(cfg).get('collectors', {})


def write_lock(cfg, slug, digest, collected_at, extra=None):
    # битый lock при записи не спорим, а перезаписываем: он машинный
    data = _lock_document(cfg, strict=False)
    data.setdefault('version', 1)
    entry = {'sha256': digest, 'validatedAt': collected_at}
    entry.update(extra or {})
    data.setdefault('collectors', {})[slug] = entry
    cfg.lock_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                             encoding='utf-8')
    return entry


def lock_state(team, lock):
    """('ok'|'missing'|'changed', запись|None, текущий хеш) — основа strict-режима (ФТ-8)."""
    digest = team.digest()
    entry = lock.get(team.slug)
    if not entry:
        return 'missing', None, digest
    if entry.get('sha256') != digest:
        return 'changed', entry, digest
    return 'ok', entry, digest
