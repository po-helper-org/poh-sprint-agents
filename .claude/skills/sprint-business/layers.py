"""Версии бизнес-блока: каждая запись — слой, итог — наложение слоёв по хронологии.

Агент пишет `sprint-business.json` целиком, но в историю ложится только то, что он
действительно поменял относительно версии, которую читал (`revision` в файле). Поэтому
две записи подряд не затирают друг друга: чужая правка, которой агент не касался,
остаётся; одно и то же поле — у более поздней записи (и об этом есть предупреждение).

    <блок>.versions/v0001.json   {"n", "at", "author", "base", "patch": [[путь, значение|null], …]}
    <блок>                       итог всех слоёв + "revision": n — его читают агент и страница

Гранулярность пути: objectives.<OBJ>; streams.<эпик>.<поле>; rows.<история>.<поле>;
остальные поля команды (members, hide, roadmap, plans, …) и jiraNative — целиком.
null в patch — поле удалено. Удаления — только у команд, которые есть в записи, и только
если известна база (`revision`): запись без базы — чистое наложение, ничего не стирает.
"""
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

KEYED = ('objectives',)          # ключ → значение
NESTED = ('streams', 'rows')     # ключ → поле → значение
META = ('version', 'generatedAt', 'author', 'revision', 'teams')


class LayersError(Exception):
    pass


def flatten(doc):
    """Документ → {путь (кортеж): значение}."""
    flat = {}
    for k, v in (doc or {}).items():
        if k not in META:
            flat[(k,)] = v
    for slug, team in ((doc or {}).get('teams') or {}).items():
        if not isinstance(team, dict):
            continue
        for k, v in team.items():
            base = ('teams', slug, k)
            if k in KEYED and isinstance(v, dict):
                for key, val in v.items():
                    flat[base + (key,)] = val
            elif k in NESTED and isinstance(v, dict):
                for key, fields in v.items():
                    if isinstance(fields, dict):
                        for f, val in fields.items():
                            flat[base + (key, f)] = val
            else:
                flat[base] = v
    return flat


def unflatten(flat):
    doc = {'teams': {}}
    for path, val in sorted(flat.items(), key=lambda kv: kv[0]):
        if val is None:
            continue
        if path[0] != 'teams':
            doc[path[0]] = val
            continue
        node = doc['teams'].setdefault(path[1], {})
        for p in path[2:-1]:
            node = node.setdefault(p, {})
        node[path[-1]] = val
    return doc


def diff(new, base, teams, deletions):
    """Что запись поменяла относительно базы: [(путь, значение | None)]."""
    out = [(p, v) for p, v in new.items() if base.get(p) != v]
    if deletions:
        out += [(p, None) for p, v in base.items()
                if p not in new and v is not None and (p[0] != 'teams' or p[1] in teams)]
    return sorted(out, key=lambda pv: pv[0])


class Store:
    def __init__(self, block):
        self.block = Path(block)
        self.dir = self.block.parent / (self.block.stem + '.versions')

    def exists(self):
        return self.dir.is_dir() and any(self.dir.glob('v*.json'))

    def versions(self):
        out = []
        for p in sorted(self.dir.glob('v*.json')) if self.dir.is_dir() else ():
            try:
                out.append(json.loads(p.read_text(encoding='utf-8')))
            except (OSError, ValueError) as exc:
                raise LayersError(f'битая версия {p.name}: {exc}') from exc
        return sorted(out, key=lambda v: v['n'])

    def latest(self):
        vs = self.versions()
        return vs[-1]['n'] if vs else 0

    @staticmethod
    def fold(versions, upto=None):
        flat = {}
        for v in versions:
            if upto is not None and v['n'] > upto:
                break
            for path, val in v['patch']:
                if val is None:
                    flat.pop(tuple(path), None)
                else:
                    flat[tuple(path)] = val
        return flat

    def materialize(self, upto=None, versions=None):
        """Итог слоёв документом схемы (+ revision). Слоёв нет — None."""
        vs = self.versions() if versions is None else versions
        vs = [v for v in vs if upto is None or v['n'] <= upto]
        if not vs:
            return None
        doc = unflatten(self.fold(vs))
        last = vs[-1]
        return {'version': 1, 'generatedAt': last['at'], 'author': last.get('author') or 'агент',
                'revision': last['n'], **{k: v for k, v in doc.items() if k != 'teams'}, 'teams': doc['teams']}

    def plan(self, doc, versions=None):
        """Чем станет запись: (patch, итог-документ, перекрытые правки, база, без базы ли)."""
        vs = self.versions() if versions is None else versions
        latest = vs[-1]['n'] if vs else 0
        rev = doc.get('revision')
        known = isinstance(rev, int) and 0 <= rev <= latest
        base_n = rev if known else latest
        base = self.fold(vs, base_n)
        patch = diff(flatten(doc), base, set((doc.get('teams') or {})), deletions=known)
        later = {}
        for v in vs:
            if v['n'] > base_n:
                for path, _ in v['patch']:
                    later[tuple(path)] = v
        overridden = sorted({(later[p]['n'], later[p].get('author') or '?') for p, _ in patch if p in later})
        flat = self.fold(vs)
        for p, v in patch:
            if v is None:
                flat.pop(p, None)
            else:
                flat[p] = v
        merged = unflatten(flat)
        result = {'version': 1, 'generatedAt': doc.get('generatedAt') or _now(),
                  'author': doc.get('author') or 'агент', 'revision': latest + (1 if patch else 0),
                  **{k: v for k, v in merged.items() if k != 'teams'}, 'teams': merged['teams']}
        return patch, result, overridden, base_n, not known

    @contextmanager
    def lock(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / '.lock', 'w') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def record(self, patch, base_n, author, at=None):
        """Новый слой. Вызывать под lock(); пустой patch — слоя нет. → номер версии."""
        n = self.latest()
        if not patch:
            return n
        n += 1
        entry = {'n': n, 'at': at or _now(), 'author': author or 'агент', 'base': base_n,
                 'patch': [[list(p), v] for p, v in patch]}
        path = self.dir / f'v{n:04d}.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(entry, fh, ensure_ascii=False, indent=1)
        return n

    def write_block(self, doc):
        """Итог — в сам файл блока, атомарно: его читают агент (с revision) и виджет."""
        tmp = self.block.with_name(self.block.name + '.tmp')
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        os.replace(tmp, self.block)


def _now():
    return datetime.now().astimezone().isoformat(timespec='seconds')
