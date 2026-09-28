#!/usr/bin/env python3
"""Записывает replay-фикстуры из синтетической JIRA и золотой выход старого collect.py.

Запускается руками при изменении набора данных:

    python3 tests/make_replay_fixtures.py

Пишет:
  tests/fixtures/jira-replay/        сырые ответы JIRA (ключ = как у Jira._key сборщика)
  tests/fixtures/legacy_collect_team.json   выход collect.py до рефакторинга — эталон
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKILL = ROOT / '.claude' / 'skills' / 'actual-sprint'
REPLAY = HERE / 'fixtures' / 'jira-replay'
LEGACY_GOLDEN = HERE / 'fixtures' / 'legacy_collect_team.json'

sys.path.insert(0, str(HERE))
import fake_jira  # noqa: E402


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def request(now=None):
    return {
        'protocol': 1,
        'team': {'slug': 'team-a', 'name': 'Команда А', 'board': fake_jira.BOARD_ID},
        'params': {},
        'jira': {'url': fake_jira.BASE, 'caBundle': None},
        'now': now or fake_jira.iso(fake_jira.NOW),
    }


def record():
    """Гоняет базовый сборщик по синтетической JIRA и складывает ответы в фикстуры."""
    collector_mod = load_module(SKILL / 'templates' / 'python' / 'collector.py', 'base_collector')
    api, _ = fake_jira.make_api()
    REPLAY.mkdir(parents=True, exist_ok=True)
    for old in REPLAY.glob('*.json'):
        old.unlink()

    class Recording(collector_mod.Jira):
        def api(self, path, **params):
            key, canon = self._key(path, params)
            self.requests += 1
            data = api(path, **params)
            (REPLAY / f'{key}.json').write_text(
                json.dumps(data, ensure_ascii=False, sort_keys=True), encoding='utf-8')
            index = REPLAY / '_index.json'
            known = json.loads(index.read_text(encoding='utf-8')) if index.is_file() else {}
            known[key] = canon
            index.write_text(json.dumps(known, ensure_ascii=False, indent=1, sort_keys=True),
                             encoding='utf-8')
            return data

    req = request()
    jira = Recording(fake_jira.BASE, 'не-настоящий-токен')
    rules = collector_mod.load_rules(req['params'])
    data = collector_mod.Collector(jira, req, rules).collect()
    print(f'записано ответов: {jira.requests} → {REPLAY.relative_to(ROOT)}')
    return data


def legacy_golden(legacy_path):
    """Прогоняет старый collect.py по тем же фикстурам — эталон обратной совместимости."""
    legacy = load_module(legacy_path, 'legacy_collect')
    api, _ = fake_jira.make_api()
    legacy.JIRA = fake_jira.BASE
    legacy.TOKEN = 'не-настоящий-токен'
    legacy.api = lambda path, **params: api(path, **params)
    import datetime
    now = fake_jira.NOW
    data = legacy.collect(fake_jira.BOARD_ID, 'Команда А', 'team-a', now)
    LEGACY_GOLDEN.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1),
                             encoding='utf-8')
    print(f'эталон старого сборщика → {LEGACY_GOLDEN.relative_to(ROOT)}')
    return data


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--legacy', default=str(SKILL / 'scripts' / 'collect.py'),
                    help='путь к collect.py до рефакторинга (для золотого файла)')
    ap.add_argument('--skip-legacy', action='store_true')
    a = ap.parse_args()
    fresh = record()
    if not a.skip_legacy and Path(a.legacy).is_file():
        old = legacy_golden(Path(a.legacy))
        same = {k: v for k, v in fresh.items() if k not in ('_meta', 'statusMap')} == old
        print('выход базового сборщика совпадает со старым:', same)
