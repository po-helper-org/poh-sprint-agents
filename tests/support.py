"""Общие помощники тестов actual-sprint: пути, запуск сборщика, доступ к модулям runner."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILL = ROOT / '.claude' / 'skills' / 'actual-sprint'
RUNNER = SKILL / 'runner'
CONTRACT = SKILL / 'contract'
BASE_COLLECTOR = SKILL / 'templates' / 'python' / 'collector.py'
REPLAY = HERE / 'fixtures' / 'jira-replay'
LEGACY_GOLDEN = HERE / 'fixtures' / 'legacy_collect_team.json'
CUSTOM_COLLECTOR = HERE / 'fixtures' / 'collectors' / 'team-b'

NOW = '2026-09-15T17:00:00.000+0300'
FAKE_TOKEN = 'токен-который-не-должен-утечь-42'

for path in (RUNNER, CONTRACT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def request(slug='team-a', name='Команда А', board=101, params=None, now=NOW, url=None):
    return {
        'protocol': 1,
        'team': {'slug': slug, 'name': name, 'board': board},
        'params': params if params is not None else {},
        'jira': {'url': url or 'https://jira.demo-workspace.local', 'caBundle': None},
        'now': now,
    }


def run_collector(script=BASE_COLLECTOR, req=None, args=(), env=None, replay=REPLAY):
    """Запускает сборщик так же, как это делает runner: запрос на stdin, JSON в stdout."""
    payload = dict(req or request())
    if replay is not None:
        payload.setdefault('params', {})
        payload['params'] = dict(payload['params'])
        payload['params'].setdefault('replay', str(replay))
    environ = dict(os.environ)
    environ.setdefault('JIRA_PERSONAL_TOKEN', FAKE_TOKEN)
    environ['ACTUAL_SPRINT_CONTRACT'] = str(CONTRACT)
    environ.update(env or {})
    proc = subprocess.run([sys.executable, str(script), *args],
                          input=json.dumps(payload, ensure_ascii=False),
                          capture_output=True, text=True, env=environ, timeout=180)
    return proc


def collect_ok(**kwargs):
    proc = run_collector(**kwargs)
    assert proc.returncode == 0, f'сборщик вышел с {proc.returncode}: {proc.stderr}'
    return json.loads(proc.stdout)
