"""Комментарии агента к слайду «Риски и проблемы»: почему зависли и что нужно сделать.

Строки слайда (инициатива · история) страница считает из снимка сама; агент даёт только третий
столбец — до трёх коротких предложений на строку. Тексты живут отдельно от бизнес-блока
(`sprint-risk-notes.json` рядом с ним): блок привязан к снимку (dataHash) и на свежих данных
отбрасывается, а комментарий — к самой задаче и её состоянию (`sig`): история сменила статус,
эпик — срок, и комментарий перестаёт показываться, пока агент не напишет новый.

    business.py risk-todo [--team slug]                       строки риска без свежего комментария
    business.py risk-put --team slug --author кто --file f    записать комментарии своей команды
"""
import fcntl
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import build as build_mod
import model as model_mod

NOTES_NAME = 'sprint-risk-notes.json'
TEXT_LIMIT = 240
SENTENCES = 3
SENT_RE = re.compile(r'[.!?…]+(?=\s|$)')


class NotesError(Exception):
    pass


def path_for(block_path):
    return Path(block_path).parent / NOTES_NAME


def story_sig(st):
    return f'{st.get("status") or ""}@{st.get("statusChanged") or ""}'


def epic_sig(e):
    return f'due@{e.get("epicDue") or ""}'


def candidates(team, rules):
    """Строки, которые могут попасть на слайд: заблокированные истории и эпики со сроком, где не всё закрыто.

    Тот же отбор, что у страницы (блокеры → «Внешнее», срок → «Срок»); какие эпики отстают от
    прогноза, страница решает сама — комментарий к эпику со сроком лишним не будет."""
    core = {k: v for k, v in team.items() if k not in build_mod.OVERLAY_FIELDS}
    tm = model_mod.TeamModel(core, rules)
    hide = set(((team.get('business') or {}).get('hide')) or [])
    out = []
    for e in team.get('epics', []):
        stories = [st for st in e.get('stories', []) if st['key'] not in hide]
        epic = e.get('epicKey')
        init = e.get('epicTitle') if epic else 'Вне эпиков'
        for st in stories:
            if tm.bucket(st['status'], st.get('category', '')) == 'blocked':
                out.append({'key': st['key'], 'kind': 'blocked', 'sig': story_sig(st), 'initiative': init, 'epic': epic,
                            'story': st['title'], 'status': st['status'], 'since': (st.get('statusChanged') or '')[:10],
                            'assignee': st.get('assignee')})
        scope = e.get('scope') or stories
        open_n = sum(1 for it in scope if tm.bucket(it['status'], it.get('category', '')) != 'done')
        if epic and e.get('epicDue') and open_n:
            out.append({'key': epic, 'kind': 'deadline', 'sig': epic_sig(e), 'initiative': init, 'epic': epic,
                        'due': e['epicDue'], 'open': open_n, 'total': len(scope)})
    return out


def read(path):
    try:
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'version': 1, 'teams': {}}
    except ValueError as exc:
        raise NotesError(f'{Path(path).name} не разбирается как JSON ({exc}) — поправьте файл вручную') from exc
    if not isinstance(doc, dict) or not isinstance(doc.get('teams'), dict):
        raise NotesError(f'{Path(path).name}: ожидается объект с полем teams')
    return doc


def check_text(key, text):
    """Ошибка или None: комментарий — до трёх коротких предложений, без деталей."""
    if not isinstance(text, str) or not text.strip():
        return f'{key}: пустой комментарий'
    text = text.strip()
    if len(text) > TEXT_LIMIT:
        return f'{key}: длиннее {TEXT_LIMIT} знаков ({len(text)}) — короче, без деталей'
    if len(SENT_RE.findall(text)) > SENTENCES:
        return f'{key}: больше {SENTENCES} предложений — оставьте «почему стоим» и «что сделать»'
    return None


def put(path, slug, author, draft, rows, now=None):
    """Записать комментарии команды: ключ — из строк risk-todo, sig — текущий. (принято, ошибки).

    Прежние комментарии команды остаются, пока строка на месте и её состояние не сменилось;
    ушедшие из рисков задачи выбрасываются. Ошибка в черновике — файл не меняется."""
    if not isinstance(draft, dict):
        raise NotesError('черновик — объект {"КЛЮЧ": "комментарий", …}')
    by_key = {r['key']: r for r in rows}
    errors = []
    for key, text in draft.items():
        if key not in by_key:
            errors.append(f'{key}: такой строки риска у команды {slug} нет — см. business.py risk-todo --team {slug}')
            continue
        err = check_text(key, text)
        if err:
            errors.append(err)
    if errors:
        return 0, errors
    at = (now or datetime.now(timezone.utc)).astimezone().isoformat(timespec='seconds')
    path = Path(path)
    with open(path.with_suffix('.json.lock'), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        doc = read(path)
        old = (doc['teams'].get(slug) or {}).get('notes') or {}
        notes = {k: v for k, v in old.items() if k in by_key and v.get('sig') == by_key[k]['sig']}
        for key, text in draft.items():
            notes[key] = {'text': text.strip(), 'sig': by_key[key]['sig'], 'at': at}
        doc['teams'][slug] = {'author': author, 'updatedAt': at, 'notes': notes}
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        tmp.replace(path)
    return len(draft), []


def attach(teams, path):
    """Комментарии — в business.riskNotes команды; от снимка не зависят, сверка sig — на странице."""
    try:
        doc = read(path)
    except NotesError:
        return
    for team in teams:
        entry = doc['teams'].get(team['slug']) or {}
        notes = entry.get('notes')
        if not notes:
            continue
        biz = team.setdefault('business', {})
        biz['riskNotes'] = {k: {'text': v.get('text', ''), 'sig': v.get('sig', '')} for k, v in notes.items()}
        biz['riskNotesBy'] = entry.get('author') or ''
