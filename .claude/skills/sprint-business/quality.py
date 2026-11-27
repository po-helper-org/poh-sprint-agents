"""Ваншот-качество бизнес-отчёта «ФАКТ | спринт»: детерминированные проверки блока агента против снимка.

`business.py apply/check` отказывает записи, если в полях, которые она меняет, есть ошибки (кроме правок PO);
`business.py quality` — метрика и все замечания колоды; `business.py quality --eval` — регрессия на кейсах
из замечаний PO (examples/quality-cases.json). Правила и разбор замечаний — docs/oneshot-quality.md.

Отчёт без правок — это когда PO не нужно ничего дописывать на слайде. Разбор 263 замечаний PO
к отчёту за 30 дней дал повторяющиеся классы ошибок; здесь — те, что
ловятся без модели:

  goal          эпик спринта без цели OBJ (кроме noObjective PO) или с другой целью, чем в карте sprint-goals.json
  slop          служебные метки модели на слайде: [УТОЧНИТЬ], «предложен агентом», «по слову PO», TODO…
  risk_owner    блокер без «от кого / кто снимает» (человек из данных команды или роль: DevOps, ИБ, PO…)
  risk_due      блокер без срока: к какой дате / дню / спринту снимут (дата «с 30.10» — давность, не срок)
  risk_missing  в эпике заблокированные истории, а явной эскалации (blocker агента) нет
  evidence      «закрыто / на проде / принято», а в спринте эпика ни одной закрытой задачи и нет оценки PO
  risk_impact   (предупреждение) блокер без влияния: что сорвётся, если не снимут
  stale         (предупреждение) история в работе/ревью без движения 7+ дней — в тексте не названа
  risk_false    (предупреждение) блокер при готовности PO 100% или без опоры в данных
  jargon        (предупреждение) голые номера задач («3031», «2967/3013») — руководитель их не читает
  foreign       (предупреждение) в тексте строки — задача другого эпика спринта
  next_due      (предупреждение) «Дальше» без срока
  autotext      строка без текста агента — на слайде автотекст из данных (только при полной проверке)

Поля, которые последним правил PO («Редактировать текст» → версия с автором PO), не проверяются:
слова PO — достоверный источник. Строка «ваншот», если по ней нет ошибок; метрика — доля таких
строк и доля явных эскалаций (у риска есть и кто, и срок).
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

NO_EPIC = 'no-epic'
PO_AUTHORS = {'PO'}


def is_po(author):
    """Правка PO (виджет колоды пишет автором «PO»): слова PO — достоверный источник, не проверяются."""
    a = (author or '').strip()
    return a in PO_AUTHORS or a.startswith('PO ') or a.startswith('PO:')
STALE_DAYS = 7
ERRORS = ('goal', 'slop', 'risk_owner', 'risk_due', 'risk_missing', 'evidence', 'autotext')
WARNINGS = ('risk_impact', 'stale', 'risk_false', 'jargon', 'foreign', 'next_due')
LABELS = {
    'goal': 'не та цель / без OBJ', 'slop': 'служебная метка модели', 'risk_owner': 'риск без «от кого»',
    'risk_due': 'риск без срока', 'risk_missing': 'пропущенный блокер', 'evidence': 'достижение без доказательства',
    'risk_impact': 'риск без влияния', 'stale': 'висит без движения', 'risk_false': 'блокер без опоры',
    'jargon': 'голые номера задач', 'foreign': 'задача другого эпика', 'next_due': '«Дальше» без срока',
    'autotext': 'нет текста агента',
}

SLOP_RE = re.compile(
    r'\[\s*(?:УТОЧНИТЬ|уточнить|TODO|TBD|\?+)\s*\]|\bTODO\b|\bTBD\b|предложен\w* агент\w*|по слов[уа]м? PO'
    r'|\(по слову PO\)|\?\?\?|\bN/A\b|lorem ipsum|как (?:ИИ|языковая модель)|<[^>]{1,20}>|\{\{|\}\}', re.I)
MONTHS = r'(?:янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек)\w*'
DATE_RE = re.compile(r'(?<![\d.])\d{1,2}\.\d{1,2}(?:\.\d{2,4})?(?![\d.])|\b\d{1,2}\s+' + MONTHS, re.I)
SINCE_RE = re.compile(r'(?:\bс|\bот|\bпосле|\bбыл[аио]?|прош[её]л\w*|истек\w*|истёк)\s*$', re.I)
DUE_WORDS_RE = re.compile(
    r'\bсегодня\b|\bзавтра\b|послезавтра|\b(?:пн|вт|ср|чт|пт)\b|понедельник|вторник|\bсред[ау]\b|четверг|пятниц'
    r'|к концу (?:спринта|недели|месяца|квартала|дня)|до конца (?:спринта|недели|месяца|квартала)'
    r'|на (?:этой|следующей) неделе|в следующем спринте|\bS\d+\b|\bQ[1-4]\b|\d{4}Q[1-4]'
    r'|на (?:синке|дейли|планёрке|планерке|груминге|встрече|демо)|\bдо \d', re.I)
ROLE_RE = re.compile(
    r'\b(?:DevOps|девопс\w*|ИБ|PO|CPO|PMO|QA|SA|техлид\w*|тимлид\w*|партн[её]р\w*|подрядчик\w*|вендор\w*|'
    r'заказчик\w*|бизнес\w*|юрист\w*|аналитик\w*|тестировщик\w*|архитектор\w*|дизайнер\w*|поддержк\w*|'
    r'команд[аыеуой]\w*|смежн\w*|TC|ТС|TicketsCloud|П24|Сбер\w*|ВТБ|VK|ВК|MindBox|Mindbox|Zion|Vibe|Bartello|'
    r'Яндекс\w*|МТС\s?Pay|МТС\s?Банк\w*|ОБИ|ДИТ|СОРМ|руководител\w*|владел\w*)\b')
IMPACT_RE = re.compile(
    r'сорв|сдвиг|сдвин|под угроз|не успе|влия|блокир|без (?:этого|него|неё|них)|иначе|если не|риск|потер|уйд[её]т'
    r'|перен[оеё]с|задерж|стоит|стоп|не (?:можем|сможем|выйд|запуст|выкат)|держ\w* (?:релиз|запуск|сборк)'
    r'|вход релиза|срок\w* (?:KR|эпика|запуска)|за квартал|запуск\w*|релиз\w*|продаж\w*|выручк\w*', re.I)
CLAIM_RE = re.compile(
    r'закрыт|закрыли|готов[оаы]?\b(?! к)|в проде|на проде|на прод\b|выкачен|выкатил|принят|сдан[оаы]?\b'
    r'|завершен[оаы]?\b|завершён'
    r'|доставлен|запущен|сделан[оаы]?\b|в бою|исправлен|починен', re.I)
NEG_CLAIM_RE = re.compile(r'не (?:начат|готов|закрыт|принят|выкачен|сделан|запущен)|не подтвержд', re.I)
BARE_NUM_RE = re.compile(r'(?<![\w.:/%№#-])(\d{3,5})(?![\w.%:,]?\d)(?!\s*(?:%|млн|тыс|руб|₽|дн|ч\b|мин|задач|истори|заказ|билет|SP\b))')
KEY_RE = re.compile(r'\b([A-Z][A-Z0-9_]+)-(\d+)\b')


def _parse_dt(text):
    if not text:
        return None
    text = re.sub(r'(\.\d+)?([+-]\d{2})(\d{2})$', r'\2:\3', str(text))
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text[:10])
        except ValueError:
            return None


def has_due(text):
    """В тексте есть срок: дата (не «с 30.10» — это давность) или слова-сроки."""
    for m in DATE_RE.finditer(text):
        if not SINCE_RE.search(text[:m.start()]):
            return True
    return bool(DUE_WORDS_RE.search(text))


def _stems(names):
    out = set()
    for full in names:
        for tok in re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', full or ''):
            out.add(tok[:max(4, len(tok) - 2)].lower())
    return out


OWNER_PREP_RE = re.compile(r'(?:^|[\s(«,;:—-])(?:у|от|за|с|к|через|ждём|ждем|ждут|просим|эскалац\w*)\s+[А-ЯЁA-Z][а-яёa-z]{2,}')


def has_owner(text, stems):
    if ROLE_RE.search(text) or OWNER_PREP_RE.search(text):
        return True
    for word in re.findall(r'[А-ЯЁA-Z][а-яёa-z]{3,}', text):
        w = word.lower()
        if any(w.startswith(s) for s in stems):
            return True
    return False


def _bucket(status, status_map, category=''):
    b = (status_map or {}).get(status)
    if b:
        return b
    return {'Выполнено': 'done', 'К выполнению': 'open'}.get(category, 'progress')


def last_authors(block_path):
    """{путь-кортеж: автор последней правки} по истории версий блока (<блок>.versions/v*.json)."""
    path = Path(block_path)
    vdir = path.parent / (path.stem + '.versions')
    out = {}
    if not vdir.is_dir():
        return out
    versions = []
    for p in vdir.glob('v*.json'):
        try:
            versions.append(json.loads(p.read_text(encoding='utf-8')))
        except (OSError, ValueError):
            continue
    for v in sorted(versions, key=lambda v: v.get('n', 0)):
        for p, _ in v.get('patch') or ():
            out[tuple(p)] = v.get('author')
    return out


class Row:
    def __init__(self, slug, key):
        self.slug, self.key = slug, key
        self.issues = []          # (code, field, message)

        self.has_blocker = False  # строка — риск: блокер в тексте или заблокированные истории

    def add(self, code, field, message):
        self.issues.append((code, field, message))

    def issues_with(self, code):
        return [i for i in self.issues if i[0] == code]

    @property
    def errors(self):
        return [i for i in self.issues if i[0] in ERRORS]

    @property
    def ok(self):
        return not self.errors


def _texts(*values):
    return ' '.join(v for v in values if isinstance(v, str))


def check_team(slug, biz, team, goals=None, authors=None, only=None):
    """Строки колоды команды → [Row]. only — множество путей (patch записи): проверять только их."""
    authors = authors or {}
    goals = goals or {}
    biz = biz or {}
    streams = biz.get('streams') or {}
    rows_txt = biz.get('rows') or {}
    hide = set(biz.get('hide') or [])
    is_stream = biz.get('kind') == 'stream' or team is None

    def po_field(*path):
        return is_po(authors.get(('teams', slug) + path))

    def wanted(*path):
        return only is None or ('teams', slug) + path in only

    # данные команды
    epics, story_epic, names = {}, {}, set(biz.get('members') or [])
    status_map = (team or {}).get('statusMap') or {}
    collected = _parse_dt(((team or {}).get('_meta') or {}).get('collectedAt')) or datetime.now().astimezone()
    prefixes = set()
    for e in (team or {}).get('epics') or []:
        key = e.get('epicKey') or NO_EPIC
        stories = [s for s in e.get('stories') or [] if s.get('key') not in hide]
        if not stories and key != NO_EPIC and not e.get('stories'):
            continue
        epics[key] = {'stories': stories, 'scope': {x.get('key') for x in e.get('scope') or []}}
        for s in stories:
            story_epic[s['key']] = key
            names.add(s.get('assignee') or '')
            for ev in s.get('events') or []:
                names.add(ev.get('by') or '')
            m = KEY_RE.match(s['key'])
            if m:
                prefixes.add(m.group(1))
    stems = _stems(names)
    known = set(story_epic) | {k for e in epics.values() for k in e['scope']}
    gteam = (goals.get('teams') or {}).get(slug) or {}
    gmap = gteam.get('epics') or {}
    no_obj = set(gteam.get('noObjective') or [])     # PO решил: у эпика цели нет — не ошибка
    objectives = biz.get('objectives') or gteam.get('objectives') or {}

    keys = list(epics) if not is_stream else list(streams)
    out = []
    for key in keys:
        st = streams.get(key) or {}
        row = Row(slug, key)
        info = epics.get(key, {'stories': [], 'scope': set()})
        stories = info['stories']
        buckets = {s['key']: _bucket(s.get('status'), status_map, s.get('category')) for s in stories}
        blocked = [s for s in stories if buckets[s['key']] == 'blocked']
        done = [s for s in stories if buckets[s['key']] == 'done'
                or any(_bucket(x.get('status'), status_map, x.get('category')) == 'done' for x in s.get('subtasks') or [])]
        readiness = st.get('readiness')
        texts = {f: st[f] for f in ('done', 'next', 'blocker', 'kr') if isinstance(st.get(f), str)}
        story_texts = {k: r for k, r in rows_txt.items() if story_epic.get(k) == key and isinstance(r, dict)}
        all_text = _texts(*texts.values(), *(v for r in story_texts.values() for v in r.values()))

        if only is None and not is_stream and not st and key != NO_EPIC:
            row.add('autotext', 'done', 'строки нет в блоке — на слайде автотекст из данных')

        # цель
        if not is_stream and key != NO_EPIC and wanted('streams', key, 'obj') and not po_field('streams', key, 'obj'):
            obj = st.get('obj')
            if objectives and not obj and key not in no_obj:
                row.add('goal', 'obj', 'эпик без цели OBJ — уйдёт на слайд «Без привязки к OKR»; спроси PO-агента и запиши в sprint-goals.json')
            elif obj and gmap.get(key) and gmap[key] != obj:
                row.add('goal', 'obj', f'в блоке {obj}, а в карте целей sprint-goals.json — {gmap[key]}')
            elif obj and objectives and obj not in objectives:
                row.add('goal', 'obj', f'цели {obj} нет в objectives команды')

        # слоп и жаргон — во всех текстах строки
        for f, text in texts.items():
            if po_field('streams', key, f) or not wanted('streams', key, f):
                continue
            m = SLOP_RE.search(text)
            if m:
                row.add('slop', f, f'служебная метка «{m.group(0)}» на слайде — реши вопрос или убери')
            bare = [n for n in BARE_NUM_RE.findall(text) if any(f'{p}-{n}' in known for p in prefixes)]
            if bare:
                row.add('jargon', f, f'голые номера задач ({", ".join(bare[:4])}) — назови суть, ключ — в сайдбаре')
            for pk, num in KEY_RE.findall(text):
                k = f'{pk}-{num}'
                other = story_epic.get(k)
                if other and other != key:
                    row.add('foreign', f, f'{k} — задача эпика {other}, не этой строки')
        for k, r in story_texts.items():
            for f, text in r.items():
                if isinstance(text, str) and not po_field('rows', k, f) and wanted('rows', k, f):
                    m = SLOP_RE.search(text)
                    if m:
                        row.add('slop', f'rows.{k}.{f}', f'служебная метка «{m.group(0)}»')

        # доказательство достижения
        dtext = texts.get('done', '')
        if (not is_stream and dtext and wanted('streams', key, 'done') and not po_field('streams', key, 'done')
                and readiness is None and not done and CLAIM_RE.search(dtext)
                and not NEG_CLAIM_RE.search(dtext[:CLAIM_RE.search(dtext).end() + 15])):
            row.add('evidence', 'done', f'«{CLAIM_RE.search(dtext).group(0)}» — а в спринте эпика нет закрытых задач и нет оценки PO; '
                                        'дай ссылку на закрытую задачу/демо или оценку PO (readiness)')

        # риски
        btext = texts.get('blocker', '')
        risk_text = _texts(btext, texts.get('next'))
        if btext and not po_field('streams', key, 'blocker') and wanted('streams', key, 'blocker'):
            if not has_owner(risk_text, stems):
                row.add('risk_owner', 'blocker', 'не сказано, от кого ждём / кто снимает блокер (человек или роль: DevOps, ИБ, PO, партнёр…)')
            if not has_due(risk_text):
                row.add('risk_due', 'blocker', 'нет срока: к какой дате/дню снимут блокер или когда эскалируем')
            if not IMPACT_RE.search(risk_text):
                row.add('risk_impact', 'blocker', 'не сказано, на что влияет: что сдвинется, если не снимут')
            if readiness == 100:
                row.add('risk_false', 'blocker', 'оценка PO 100% — а блокер на слайде; снять или пояснить')
        if not is_stream and blocked and readiness != 100 and wanted('streams', key, 'blocker'):
            explicit = btext or any(isinstance(r.get('blocker'), str) for r in story_texts.values())
            if not explicit:
                ks = ', '.join(s['key'] for s in blocked[:3])
                row.add('risk_missing', 'blocker', f'заблокировано {len(blocked)} ({ks}) — нужна явная эскалация: '
                                                   'что стоит, от кого ждём, к какому сроку, что сдвинется')
        if not is_stream and stories and wanted('streams', key, 'done'):
            for s in stories:
                if buckets[s['key']] not in ('progress', 'review'):
                    continue
                changed = _parse_dt(s.get('statusChanged'))
                if not changed:
                    continue
                try:
                    days = (collected - changed).days
                except TypeError:
                    days = (collected.replace(tzinfo=None) - changed.replace(tzinfo=None)).days
                num = s['key'].rsplit('-', 1)[-1]
                if days >= STALE_DAYS and s['key'] not in all_text and not re.search(rf'(?<!\d){num}(?!\d)', all_text):
                    row.add('stale', 'done', f'{s["key"]} «{s.get("status")}» без движения {days} дн. — не названа в тексте')
        if (not is_stream and btext and not blocked and readiness != 100 and not po_field('streams', key, 'blocker')
                and wanted('streams', key, 'blocker') and not row.issues_with('stale')):
            row.add('risk_false', 'blocker', 'в Jira блок не отражён (ни одной задачи «В ожидании» или без движения 7+ дн.) — переведи задачу в ожидание или сними блокер')

        ntext = texts.get('next', '')
        if ntext and not has_due(ntext) and not re.search(r'заверш|закрыть эпик|новых задач|нет\b', ntext, re.I) \
                and not po_field('streams', key, 'next') and wanted('streams', key, 'next'):
            row.add('next_due', 'next', '«Дальше» без срока — когда')
        row.has_blocker = bool(btext) or bool(row.issues_with('risk_missing'))
        out.append(row)
    return out


def assess(block, teams, goals=None, authors=None, team=None, only=None):
    """Блок + снимок → {slug: [Row]}."""
    by_slug = {t.get('slug'): t for t in teams or []}
    out = {}
    for slug, biz in ((block or {}).get('teams') or {}).items():
        if team and slug != team:
            continue
        data = by_slug.get(slug)
        if data is None and (biz or {}).get('kind') != 'stream':
            continue
        out[slug] = check_team(slug, biz, data, goals, authors, only)
    for slug, data in by_slug.items():
        if slug not in out and (not team or team == slug):
            out[slug] = check_team(slug, {}, data, goals, authors, only)
    return out


def summary(result):
    """{teams: {slug: {...}}, total: {...}} — метрика ваншот-качества."""
    def agg(rows):
        risk = [r for r in rows if r.has_blocker]
        explicit = [r for r in risk if not r.issues_with('risk_owner') and not r.issues_with('risk_due')
                    and not r.issues_with('risk_missing')]
        counts = {}
        for r in rows:
            for c, _, _ in r.issues:
                counts[c] = counts.get(c, 0) + 1
        n = len(rows)
        ok = sum(r.ok for r in rows)
        return {'rows': n, 'oneshot': ok, 'oneshotPct': round(100 * ok / n) if n else 100,
                'riskRows': len(risk), 'riskExplicit': len(explicit),
                'riskExplicitPct': round(100 * len(explicit) / len(risk)) if risk else 100,
                'errors': sum(len(r.errors) for r in rows),
                'warnings': sum(len(r.issues) - len(r.errors) for r in rows), 'counts': counts}
    teams = {slug: agg(rows) for slug, rows in result.items()}
    return {'teams': teams, 'total': agg([r for rows in result.values() for r in rows])}


def format_text(result, warnings=True, limit=None):
    lines = []
    s = summary(result)
    for slug, rows in result.items():
        t = s['teams'][slug]
        lines.append(f'[{slug}] ваншот {t["oneshot"]}/{t["rows"]} строк ({t["oneshotPct"]}%), '
                     f'явные эскалации {t["riskExplicit"]}/{t["riskRows"]}')
        shown = 0
        for r in rows:
            for code, field, msg in r.issues:
                if code in WARNINGS and not warnings:
                    continue
                if limit is not None and shown >= limit:
                    break
                mark = '✗' if code in ERRORS else '⚠'
                lines.append(f'  {mark} {r.key} · {field}: {msg} [{code}]')
                shown += 1
    tot = s['total']
    lines.append(f'Итого: ваншот {tot["oneshot"]}/{tot["rows"]} ({tot["oneshotPct"]}%), явные эскалации '
                 f'{tot["riskExplicit"]}/{tot["riskRows"]} ({tot["riskExplicitPct"]}%), ошибок {tot["errors"]}, '
                 f'предупреждений {tot["warnings"]}')
    return '\n'.join(lines)


def to_json(result):
    return {'summary': summary(result),
            'issues': [{'team': slug, 'row': r.key, 'code': c, 'level': 'error' if c in ERRORS else 'warning',
                        'field': f, 'message': m}
                       for slug, rows in result.items() for r in rows for c, f, m in r.issues]}


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


# ------------------------------------------------------------------ eval: замечания PO → регрессионные кейсы

CASES = Path(__file__).resolve().parent / 'examples' / 'quality-cases.json'


def _case_team(case, collected, status_map):
    def stories(rows):
        return [{'key': k, 'status': st, 'statusChanged': f'{day}T10:00:00+03:00', 'assignee': 'Иванов Иван',
                 'category': {'done': 'Выполнено', 'open': 'К выполнению'}.get(status_map.get(st), 'В работе'),
                 'subtasks': [], 'events': []} for k, st, day in rows]
    epics = [{'epicKey': case['epic'], 'stories': stories(case['stories']), 'scope': []}]
    if case.get('other'):
        epics.append({'epicKey': case['other']['epic'], 'stories': stories(case['other']['stories']), 'scope': []})
    return {'slug': case['team'], 'statusMap': status_map, '_meta': {'collectedAt': collected}, 'epics': epics}


def run_case(case, collected, status_map):
    """Кейс → (поднятые коды строки эпика кейса)."""
    team = _case_team(case, collected, status_map)
    biz = {'dataHash': 'x'}
    if case.get('stream') is not None:
        biz['streams'] = {case['epic']: case['stream']}
        if case.get('other'):
            biz['streams'][case['other']['epic']] = {'done': 'Доработки закрыты, приняты 18.11.', 'next': 'Приёмка 28.11'}
    goals = {'teams': {case['team']: case['goals']}} if case.get('goals') else {}
    if not goals and case.get('stream') and case['stream'].get('obj'):
        goals = {'teams': {case['team']: {'objectives': {case['stream']['obj']: 'цель'}, 'epics': {}}}}
    if goals:
        biz['objectives'] = goals['teams'][case['team']].get('objectives', {})
    rows = check_team(case['team'], biz, team, goals)
    row = next(r for r in rows if r.key == case['epic'])
    return {c for c, _, _ in row.issues}


def evaluate(path=CASES):
    """Прогон кейсов → {total, caught, clean, falsePositive, misses: [...], byCategory: {...}}."""
    doc = json.loads(Path(path).read_text(encoding='utf-8'))
    out = {'total': 0, 'caught': 0, 'clean': 0, 'cleanOk': 0, 'misses': [], 'byCategory': {}}
    for case in doc['cases']:
        got = run_case(case, doc['collectedAt'], doc['statusMap'])
        want = set(case['expect'])
        cat = out['byCategory'].setdefault(case['category'], {'total': 0, 'ok': 0})
        cat['total'] += 1
        if want:
            out['total'] += 1
            ok = want <= got
            out['caught'] += ok
        else:
            out['clean'] += 1
            ok = not got
            out['cleanOk'] += ok
        cat['ok'] += ok
        if not ok:
            out['misses'].append({'id': case['id'], 'want': sorted(want), 'got': sorted(got)})
    return out
