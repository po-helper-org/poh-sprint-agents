// E2E бизнес-отчёта «ФАКТ | спринт» (навык sprint-business) — в настоящем Chromium.
//
//   cd tests/e2e && npm install && npm test
//
// Страница собирается из demo_data.py --business, в JIRA не ходим.
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const page = join(mkdtempSync(join(tmpdir(), 'business-e2e-')), 'business.html');
execFileSync('python3', [join(ROOT, '.claude/skills/actual-sprint/scripts/demo_data.py'), '--business', page]);

const failures = [];
const check = (ok, what) => { console.log((ok ? '✓ ' : '✗ ') + what); if (!ok) failures.push(what); };

const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const p = await ctx.newPage();
const errors = [];
p.on('pageerror', e => errors.push(e.message));
await p.goto(pathToFileURL(page).href);
await p.waitForTimeout(400);
const TEAMS_N = (info) => info.teams.split('|').length;

// колода «ФАКТ | спринт»: верхнеуровневая — OBJ → строка = эпик (KR) со сводкой историй
const deckInfo = await p.evaluate(() => ({
  open: !document.getElementById('deck').hidden, hash: location.hash,
  // на сцене виден один слайд: высоту содержимого меряем, показывая каждый по очереди
  slides: [...document.querySelectorAll('#deckSlides > .fslide')].map(s => {
    const was = s.classList.contains('cur');
    s.classList.add('cur');
    const h = s.scrollHeight;
    if (!was) s.classList.remove('cur');
    return { title: (s.querySelector('.slide-title, h1') || {}).textContent || '', h };
  }),
  toc: document.querySelectorAll('#deckTocList a').length,
  heroes: [...document.querySelectorAll('#deckSlides .hero-slide h1')].map(h => h.textContent).join('|'),
  teams: TEAMS.map(t => t.team).join('|'),
  rows: document.querySelectorAll('#deckSlides tr.row').length,
  storyRows: document.querySelectorAll('#deckSlides tr.grp').length,
  epics: TEAMS.reduce((n, t) => n + t.epics.filter(e => e.stories.length).length, 0),
  legend: !!document.querySelector('#deckSlides .legend'),
}));
check(deckInfo.open, 'страница открывается сразу колодой');
check(await p.$('#tableBody') === null && await p.$('#deckClose') === null, 'отчёта PO под колодой нет, выйти некуда');
check(deckInfo.slides[0].title.startsWith('ФАКТ | '), 'титул «ФАКТ | спринт»');
check(deckInfo.heroes === deckInfo.teams, 'у каждой команды — разделитель с её именем, в порядке вкладок');
check(deckInfo.slides.some(s => s.title.startsWith('OBJ 1: Партнёрские заказы')), 'слайд — цель: «OBJ 1: название»');
check(deckInfo.slides.some(s => s.title.startsWith('Без привязки к OKR')), 'эпики без цели — «Без привязки к OKR»');
check(!deckInfo.slides.some(s => s.title.startsWith('Стримы')) && !deckInfo.legend, 'нет «Стримы: команда» и пояснения цветов');
check(deckInfo.rows === deckInfo.epics && deckInfo.storyRows === 0, 'строка — эпик (и «Вне эпиков»), историй построчно на слайдах нет');
check(!deckInfo.slides.some(s => /^(Изменения в процессе спринта|Демо|Итоги спринта)/.test(s.title)), 'слайдов «Изменения», «Демо», «Итоги» нет');
check(deckInfo.slides.filter(s => !/^(OBJ|Без привязки|Направления)/.test(s.title)).every(s => s.h === 720),
      'титул, команда, операционный, «Сроки», «Планы» — ровно 1280×720');
check(deckInfo.toc === deckInfo.slides.length, 'оглавление — по фактическим слайдам');
const kinds = await p.evaluate(() => [...document.querySelectorAll('#deckSlides > .fslide')].map(s => s.className));
const isOps = c => c.includes(' ops') && !c.includes(' cycle');
check(kinds.filter(isOps).length === TEAMS_N(deckInfo), 'операционный отчёт — один слайд на команду');
check(kinds.every((c, i) => !isOps(c) || kinds[i + 1].includes(' cycle')), 'сразу после операционного — «Сроки»');
check(kinds.every((c, i) => !c.includes(' cycle') || kinds[i + 1].includes(' plans')), 'после «Сроков» — «Планы на следующий спринт»');
// титул и слайд команды: сводка, а не голый текст; ни подписи про агента, ни «эпик · Sprint Goal» в шапках KR
const heads = await p.evaluate(() => ({
  cards: document.querySelectorAll('.title-slide .t-card').length,
  big: document.querySelector('.title-slide .t-card .t-big').textContent,
  hero: document.querySelector('.hero-slide h1').textContent,
  kpis: document.querySelector('.hero-slide').querySelectorAll('.h-kpis > div').length,
  goals: document.querySelector('.hero-slide').querySelectorAll('.h-goal').length,
  panels: [...document.querySelector('.hero-slide').querySelectorAll('.h-panel h3')].map(h => h.textContent),
  blkItems: document.querySelector('.hero-slide').querySelectorAll('.h-blk li:not(.h-none):not(.h-more)').length,
  blocked: TEAMS[0].epics.reduce((n, e) => n + e.stories.filter(st => classifyBucket(st.status, st.category) === 'blocked').length, 0),
  centered: getComputedStyle(document.querySelector('.hero-slide')).textAlign,
  note: document.body.textContent.includes('ИИ-агент PO по данным'),
  krTail: [...document.querySelectorAll('#deckSlides tr.erow td.task')].some(td => /Sprint Goal|· эпик «/.test(td.textContent)) }));
check(heads.cards === TEAMS_N(deckInfo) && /^\d+%$/.test(heads.big), 'титул: по карточке на команду с долей закрытых историй');
check(heads.hero === deckInfo.teams.split('|')[0] && heads.kpis === 4 && heads.goals >= 1 && heads.centered === 'center',
      'слайд команды: имя, четыре числа (в т. ч. заблокировано и не закрыто), цели плашками');
check(heads.panels.length === 2 && heads.panels[0].startsWith('🛑 Заблокированы · ' + heads.blocked) && /^⏳ (Не успели по объёму|Пока не закрыто) · \d+/.test(heads.panels[1]),
      'две панели: «Заблокированы» отдельно от «Не успели по объёму»');
check(heads.blkItems === Math.min(heads.blocked, 6), 'в панели блокеров — заблокированные истории команды');
check(!heads.note && !heads.krTail, 'нет подписи про агента и «эпик · Sprint Goal» в строках');

// сцена: один слайд на всю площадь, навигация кнопками; «Слайды» — выезжающий сайдбар
const stage = await p.evaluate(() => {
  const cur = document.querySelectorAll('#deckSlides > .fslide.cur');
  const r = cur[0].getBoundingClientRect(), feed = document.getElementById('deckFeed').getBoundingClientRect();
  return { cur: cur.length, first: cur[0] === document.querySelector('#deckSlides > .fslide'), w: r.width, feedW: feed.width,
           thumbs: document.querySelectorAll('#deckTocList .thumb-box').length,
           tocOpen: document.getElementById('deckToc').classList.contains('open'), count: document.getElementById('deckCount').textContent };
});
check(stage.cur === 1 && stage.first, 'на сцене — один слайд, с первого');
check(stage.w > stage.feedW - 60, 'слайд растянут на всю ширину сцены');
check(!stage.tocOpen && stage.thumbs === 0, 'постоянной панели миниатюр нет, сайдбар слайдов закрыт');
await p.click('#deckSideTab');
await p.waitForTimeout(300);
const toc = await p.evaluate(() => ({ open: document.getElementById('deckToc').classList.contains('open'),
  first: document.querySelector('#deckTocList a').textContent, x: document.getElementById('deckToc').getBoundingClientRect().left }));
check(toc.open && toc.x >= -1 && /^1 · титул/.test(toc.first), 'ярлык «Слайды» слева открывает сайдбар: «номер · тип · заголовок»');
await p.click('#deckTocList a >> nth=4');
await p.waitForTimeout(300);
check((await p.textContent('#deckCount')).startsWith('5 / ') &&
      !(await p.evaluate(() => document.getElementById('deckToc').classList.contains('open'))), 'выбор слайда — переход, сайдбар закрывается');
await p.click('#deckSideTab');
await p.waitForTimeout(250);
await p.keyboard.press('Escape');
check(!(await p.evaluate(() => document.getElementById('deckToc').classList.contains('open'))) && await p.isVisible('#deck'),
      'Esc закрывает сайдбар слайдов');
await p.keyboard.press('Home');
check(stage.count === '1 / ' + deckInfo.slides.length, 'счётчик «1 / N»');
await p.click('#deckNext');
await p.keyboard.press('ArrowRight');
check((await p.textContent('#deckCount')).startsWith('3 / '), 'кнопка › и стрелка листают');
await p.click('#deckPrev');
check((await p.textContent('#deckCount')).startsWith('2 / '), 'кнопка ‹ — назад');
const goTo = async (sel) => {
  await p.evaluate(sel => {
    const s = document.querySelector(sel).closest('#deckSlides > .fslide');
    document.querySelectorAll('#deckTocList a')[[...document.querySelectorAll('#deckSlides > .fslide')].indexOf(s)].click();
  }, sel);
  await p.waitForTimeout(100);
};
await goTo('#deckSlides .fslide.ops');
check(await p.isVisible('#deckSlides .fslide.ops') &&
      await p.evaluate(() => document.querySelector('#deckTocList a.cur') !== null), 'переход к слайду из списка, текущий отмечен');

// операционный отчёт: без заголовка; крупно производительность и сгорание спринта, участников здесь нет
const ops = await p.evaluate(() => {
  const s = document.querySelector('#deckSlides .fslide.ops:not(.cycle)');
  return { title: !!s.querySelector('.slide-title'),
           heads: [...s.querySelectorAll('.ops-h')].map(h => h.textContent),
           table: !!s.querySelector('table.mtab'), ctl: !!s.querySelector('[data-ctl]'),
           big: (r => r.width / r.height)(s.querySelector('.ops-chart svg').getBoundingClientRect()),
           legend: s.querySelector('.ops-legend').textContent };
});
check(!ops.title, 'у операционного слайда нет заголовка');
check(ops.heads.length === 3 && ops.heads[0].startsWith('Производительность за 3 спринта') &&
      ops.heads[1].startsWith('Сгорание: истории и задачи') && ops.heads[2].startsWith('Сгорание: с подзадачами'),
      'три графика: производительность за 3 спринта и сгорание — без подзадач и с ними');
check(ops.big > 1.8 && !ops.ctl, 'графики вытянуты по ширине; диаграмма управления — на слайде «Сроки»');
const burn = await p.evaluate(() => [...document.querySelectorAll('#deckSlides .fslide.ops:not(.cycle)')][0]
  .querySelectorAll('.ops-chart svg').length);
check(burn === 3, 'оба сгорания нарисованы (сборщик 1.10.0: storyScope/storyClosed)');
// снизу — истории и подзадачи спринта по участникам: шкала «Числа / Доли», сортировка, клик по имени — сайдбар
const mx = async () => p.evaluate(() => {
  const s = document.querySelector('#deckSlides .fslide.ops:not(.cycle)');
  const names = new Set();
  TEAMS[0].epics.forEach(e => e.stories.forEach(st => { names.add(st.assignee || 'Не назначен'); (st.subtasks || []).forEach(x => names.add(x.assignee || 'Не назначен')); }));
  return { rows: s.querySelectorAll('.mx-row:not(.mx-head)').length, names: names.size,
           list: [...s.querySelectorAll('.mx-row:not(.mx-head) .mx-name')].map(n => n.textContent),
           widths: [...s.querySelectorAll('.mx-bar > span')].map(x => x.style.width),
           on: [...s.querySelectorAll('.mx-btn.on')].map(b => b.textContent).join('|'),
           heads: [...s.querySelectorAll('.mx-head span')].map(x => x.textContent).filter(Boolean).join('|') };
});
let m1 = await mx();
check(m1.rows === m1.names && m1.heads === 'Истории|Подзадачи|SP|Застряли' && m1.on === 'Числа|По застрявшим',
      'по строке на участника: истории, подзадачи, SP, застрявшие; по умолчанию — числа, по застрявшим');
check(m1.widths.some(w => parseFloat(w) < 100), 'шкала «Числа» — длина полосы по количеству задач');
await p.click('#deckSlides .fslide.ops:not(.cycle) [data-mx-scale="share"]');
await p.click('#deckSlides .fslide.ops:not(.cycle) [data-mx-sort="list"]');
m1 = await mx();
check(m1.widths.every(w => parseFloat(w) === 100) && m1.on === 'Доли|По списку', '«Доли» — все полосы во всю ширину');
check(m1.list.slice(0, -1).every((n, i, a) => !i || a[i - 1] <= n), '«По списку» — по алфавиту');
await p.click('#deckSlides .fslide.ops:not(.cycle) .mx-name .mname >> nth=0');
await p.waitForTimeout(300);
check((await p.textContent('#stackKey')).startsWith('Участник'), 'клик по имени — сайдбар задач участника');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
check(ops.legend.startsWith('Не начатоВ работеВыполнено'), 'три группы статусов в легенде');
check(!ops.table, 'выработки по участникам в бизнес-отчёте нет — она в отчёте PO');
// «Сроки»: cycle time по спринтам со скользящими средними, время в статусах; клик — разбор
await goTo('#deckSlides .fslide.cycle');
const cyc = await p.evaluate(() => {
  const s = document.querySelector('#deckSlides .fslide.cycle');
  const svg = s.querySelector('.cyc svg');
  return { heads: s.querySelectorAll('.ops-h').length, delta: s.querySelectorAll('.tis-d').length,
           points: svg.querySelectorAll('circle').length, lines: svg.querySelectorAll('path.cyc-avg').length,
           bandsSigma: svg.querySelectorAll('path.cyc-band').length,
           bands: [...svg.querySelectorAll('text')].map(t => t.textContent).filter(t => /^С\d+/.test(t)).length,
           ends: [...svg.querySelectorAll('text')].map(t => t.textContent).filter(t => t === 'Истории' || t === 'Подзадачи').length,
           tis: [...s.querySelectorAll('.tis-h')].map(h => h.textContent).join('|'),
           big: [...s.querySelectorAll('.tis-big')].every(b => /\d,\d/.test(b.textContent)),
           bars: s.querySelectorAll('.tis svg rect').length };
});
check(cyc.heads === 0 && cyc.delta === 0, '«Сроки»: без заголовков блоков и без оценок «хуже / лучше»');
check(cyc.points > 10 && cyc.lines === 2 && cyc.bandsSigma === 2 && cyc.bands === 3 && cyc.ends === 2,
      'точки историй и подзадач, два скользящих средних с коридором ±σ и подписью в конце, полосы трёх спринтов');
check(cyc.tis === 'Заблокировано|Ревью|Отладка' && cyc.big && cyc.bars === 9,
      'время в статусах: текущее крупно, столбики по спринтам');
await p.click('#deckSlides .fslide.cycle .cyc');
await p.waitForTimeout(300);
const ctl = await p.evaluate(() => ({ key: document.getElementById('stackKey').textContent,
  tabs: [...document.querySelectorAll('.side-tab')].map(t => t.textContent),
  kpis: document.querySelectorAll('#storiesBody .ck').length,
  chart: !!document.querySelector('#storiesBody .cbig svg'), rows: document.querySelectorAll('#storiesBody table.ctab tbody tr').length }));
check(ctl.key.startsWith('Диаграмма управления') && ctl.tabs.length === 2 && ctl.tabs[0].startsWith('Истории') && ctl.kpis === 7 && ctl.chart && ctl.rows === 3,
      'клик по cycle time — сайдбар: показатели, диаграмма управления, разбивка по спринтам');
await p.click('.side-tab >> nth=1');
check(await p.isVisible('#storiesBody .cbig svg'), 'вкладка «Подзадачи» — своя диаграмма');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// планы на следующий спринт
await goTo('#deckSlides .fslide.plans');
const plans = await p.evaluate(() => [...document.querySelector('#deckSlides .fslide.plans').querySelectorAll('.pcol')]
  .map(c => [c.querySelector('.pc-head b').textContent, c.querySelectorAll('.prow').length,
              Math.max(0, ...[...c.querySelectorAll('.prow')].map(r => r.getBoundingClientRect().height)), +c.querySelector('.pc-head span').textContent,
              c.querySelector('.pr-more') ? +c.querySelector('.pr-more').textContent.replace(/\D/g, '') : 0]));
check(plans.map(x => x[0]).join('|') === 'Взять в работу|Доделать|Возможно войдёт|Эскалировать' && plans.every(x => x[1] <= 15) && plans.some(x => x[1]),
      '«Планы на следующий спринт»: четыре колонки, в т. ч. «Возможно войдёт»');
const pg = await p.evaluate(() => { const s = document.querySelector('#deckSlides .fslide.plans');
  return { heads: s.querySelectorAll('.pg-head').length, keys: s.querySelectorAll('.pr-key').length,
           tip: (s.querySelector('.prow') || {}).title || '' }; });
check(pg.heads > 0 && pg.keys === 0 && /^[A-Z]+-\d+/.test(pg.tip), 'внутри колонок — по направлениям; ключей на слайде нет, ключ — в подсказке');
check(plans.every(x => x[2] < 70 && x[1] + x[4] === x[3]), 'строка на задачу (у «Эскалировать» — с пояснением); что не влезло — «ещё N», счётчик колонки — всё');
await goTo('#deckSlides tr.erow[data-key="INIT-125"]');
const rowCheck = await p.evaluate(() => {
  const tr = document.querySelector('#deckSlides tr.erow[data-key="INIT-125"]');
  const auto = document.querySelector('#deckSlides tr.erow[data-key="INIT-111"]');
  return { cls: tr.className, res: tr.querySelector('.result > span').textContent.trim(), how: tr.querySelector('.result > span').title,
           sub: tr.querySelector('.res-sub').textContent, bar: tr.querySelectorAll('.res-bar i').length,
           tags: [...tr.querySelectorAll('.tag')].map(t => t.textContent).join('|'),
           done: tr.querySelector('[data-edit="sdone:platform:INIT-125"]').textContent,
           blk: (tr.querySelector('[data-edit="sblk:platform:INIT-125"]') || {}).textContent,
           next: (tr.querySelector('[data-edit="snext:platform:INIT-125"]') || {}).textContent,
           autoDone: auto.querySelector('[data-edit^="sdone:"]').textContent,
           kr: tr.querySelector('td.task b').textContent,
           noEpic: [...document.querySelectorAll('#deckSlides tr.erow td.task b')].some(b => b.textContent === 'Вне эпиков') };
});
check(/^\d+%$/.test(rowCheck.res) && /^закрыто \d+ из \d+$/.test(rowCheck.sub) && rowCheck.bar > 0, 'результат строки — процент, «закрыто X из Y» и полоса историй');
check(rowCheck.how.startsWith('среднее «Результата» историй'), 'как посчитан результат — в подсказке');
check(rowCheck.done.startsWith('Метрики загрузчика собраны и на ревью') && rowCheck.blk === 'нет доступа к очереди событий смежной команды' &&
      rowCheck.next === 'эскалация на синке команд в четверг', 'сводка агента: итог, блокер, след. шаг');
check(/^(Закрыто|В работе): .+\.$|^Работа не начата\.$/.test(rowCheck.autoDone), 'без агента сводка — из данных: закрытые истории или что в работе');
check(rowCheck.kr === 'KR 3.1 — платформа выдерживает пиковый сезон', 'строка — KR');
check(rowCheck.noEpic, 'истории без эпика — строка «Вне эпиков»');
check(/не закрыто \d+/.test(rowCheck.tags) || rowCheck.cls.includes('stat-green'), 'незакрытое — меткой «⏳ не закрыто N»');
// клик по строке — активность истории
await goTo('#deckSlides tr.erow[data-key="INIT-111"]');
await p.click('#deckSlides tr.erow[data-key="INIT-111"] td.task');
await p.waitForTimeout(300);
const epicTabs = await p.$$eval('.side-tab', t => t.map(x => x.textContent.split(' · ')[0]).join('|'));
const esRows = await p.$$eval('#storiesBody .es-row', r => r.length);
check(epicTabs === 'Истории спринта|Весь эпик' && esRows === 2, 'клик по строке — сайдбар: истории спринта эпика и «Весь эпик»');
check((await p.textContent('#storiesBody')).includes('Агрегация каталога собрана и ждёт приёмки PO.'), 'у истории в сайдбаре — её текст из бизнес-блока');
await p.click('#storiesBody .es-row:has-text("Агрегация каталога и доступности")');
await p.waitForTimeout(300);
const tabs = await p.$$eval('.side-tab', t => t.map(x => x.textContent));
check(await p.isVisible('#panelStack.open') && (await p.textContent('#stackTitle')) === 'Агрегация каталога и доступности' &&
      tabs.map(x => x.split(' · ')[0]).join('|') === 'Все|История|Подзадачи', 'клик по истории — сайдбар: все события, фильтры «История» и «Подзадачи»');
const story = await p.evaluate(() => {
  const st = TEAMS.flatMap(t => t.epics).flatMap(e => e.stories).find(x => x.key === 'INIT-112');
  const at = [...document.querySelectorAll('#storiesBody .sf-item .sf-time')].length;
  return { cal: !!document.querySelector('#storiesBody .sc svg'), band: document.querySelectorAll('#storiesBody .sc svg rect').length,
           items: document.querySelectorAll('#storiesBody .sf-item').length, events: st.events.length, label: document.getElementById('storiesLabel').textContent,
           first: st.events[0].at < (TEAMS[0].logs.since || '9') };
});
check(story.cal && story.band > 0, 'сверху — календарь активности истории: статус по времени, подзадачи, комментарии');
check(story.items === story.events && story.first, 'лента — вся хронология истории и подзадач, с её создания, а не только за спринт');
check(story.label === '', 'без подписи «Активность за N дн.»');
await p.click('.side-tab >> nth=2');
check((await p.locator('#storiesBody .sf-sub').count()) === (await p.locator('#storiesBody .sf-item').count()), 'фильтр «Подзадачи» — только события подзадач');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
check(await p.isVisible('#deck') && !(await p.isVisible('#panelStack.open')), 'Esc закрывает сайдбар, колода остаётся');
// «Весь эпик» — вкладка сайдбара строки
await goTo('#deckSlides tr.erow[data-key="INIT-101"]');
await p.click('#deckSlides tr.erow[data-key="INIT-101"] td.task');
await p.waitForTimeout(300);
await p.click('.side-tab[data-tab="scope"]');
await p.waitForTimeout(300);
const eb = await p.evaluate(() => ({ chart: !!document.querySelector('#storiesBody .eb svg'),
  bars: document.querySelectorAll('#storiesBody .eb svg rect').length,
  panel: (document.querySelector('#storiesBody .eb-analysis') || {}).textContent || '',
  modes: [...document.querySelectorAll('#storiesBody .eb-mode')].map(b => b.textContent),
  why: !!document.querySelector('#storiesBody .eb-why'),
  secs: [...document.querySelectorAll('#storiesBody .scope-sec .sec-head')].map(h => h.textContent),
  n: [...document.querySelectorAll('#storiesBody .scope-sec .sec-head .n')].reduce((a, x) => a + parseInt(x.textContent.replace('·', ''), 10), 0),
  scope: TEAMS[0].epics[0].scope.length }));
check(eb.chart && eb.bars > 5 && /Плановая дата/.test(eb.panel) && /Расчётная дата/.test(eb.panel) && /Темп сгорания/.test(eb.panel),
      '«Весь эпик» — сгорание эпика по неделям, под ним панель анализа: план, расчёт, темп');
check(eb.modes.join('|') === 'SP|Закрытие историй|Закрытие подзадач', 'основа расчёта: SP, закрытие историй, закрытие подзадач');
check(!eb.why, 'без пояснений словами');
check(eb.secs[0].startsWith('Что осталось') && eb.secs[1].startsWith('Что выполнено') && eb.n === eb.scope,
      'ниже — что осталось и что выполнено: весь объём эпика, как в отчёте PO');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// ПКМ — комментарий
await goTo('#deckSlides tr.erow[data-key="INIT-125"]');
await p.click('#deckSlides tr.erow[data-key="INIT-125"] td.task', { button: 'right' });
check(await p.isVisible('#cpop') && (await p.textContent('#cpopTarget')).includes('INIT-125'), 'правый клик по строке — комментарий к эпику');
await p.fill('#cpopText', 'Уточнить дату выкатки');
await p.press('#cpopText', 'Enter');
check(await p.evaluate(() => document.querySelector('#deckSlides tr.erow[data-key="INIT-125"]').classList.contains('commented')),
      'строка с комментарием помечена');
// редактирование текста
await p.click('#deckEdit');
const edEl = p.locator('[data-edit="sdone:platform:INIT-125"]');
await edEl.click();
// курсор — в конец всего текста: в многострочной сводке End уводит лишь в конец видимой строки
await edEl.evaluate(el => { const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
  const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); });
await p.keyboard.type(' Показали PO.');
await p.keyboard.press('Enter');
check(!(await p.isVisible('#panelStack.open')), 'в режиме правки клик не открывает сайдбар');
await p.click('#deckEdit');
await p.reload();
await p.waitForTimeout(300);
await goTo('[data-edit="sdone:platform:INIT-125"]');
await p.waitForTimeout(300);
check((await p.textContent('[data-edit="sdone:platform:INIT-125"]')).endsWith('Показали PO.'), 'правка текста сохраняется и переживает перезагрузку');
p.once('dialog', d => d.accept());
await p.click('#deckReset');
await p.waitForTimeout(200);
check((await p.textContent('[data-edit="sdone:platform:INIT-125"]')).endsWith('приём не включён.'), '«Вернуть текст» возвращает исходный');
await p.keyboard.press('Escape');
check(await p.isVisible('#deck'), 'Esc колоду не закрывает: это сама страница');

// высокий слайд прокручивается внутри: «↓ ещё ниже», ↓ сначала докручивает, потом листает
await goTo('#deckSlides tr.erow');
const tall = await p.evaluate(() => {
  const s = document.querySelector('#deckSlides > .fslide.cur');
  s.querySelector('table.rep tbody').insertAdjacentHTML('beforeend', '<tr><td colspan="3" style="height:900px">заполнитель</td></tr>');
  s.dispatchEvent(new Event('scroll'));
  return { sh: s.scrollHeight, ch: s.clientHeight, count: document.getElementById('deckCount').textContent };
});
await p.waitForTimeout(100);
check(tall.sh > tall.ch && await p.isVisible('#deckMore'), 'слайд выше 720 — внутри прокрутка и «↓ ещё ниже»');
await p.keyboard.press('ArrowDown');
await p.waitForTimeout(600);
check((await p.textContent('#deckCount')) === tall.count &&
      await p.evaluate(() => document.querySelector('#deckSlides > .fslide.cur').scrollTop > 0), '↓ на высоком слайде — прокрутка, а не следующий слайд');
await p.keyboard.press('End');
await p.reload();
await p.waitForTimeout(400);

// «Для техлидов» — промт на отчёт PO с вопросами с бизнес-отчёта
await p.click('#techBtn');
await p.waitForTimeout(150);
const techPrompt = await p.inputValue('#genText');
check(await p.isVisible('#genWrap') && techPrompt.includes('/actual-sprint') && techPrompt.includes('Уточнить дату выкатки'),
      '«Для техлидов» — промт на технический отчёт с комментариями со слайдов');
await p.keyboard.press('Escape');
check(await p.isHidden('#genWrap') && await p.isVisible('#deck'), 'Esc закрывает окно промта, колода на месте');

check(!errors.length, 'ошибок JavaScript нет' + (errors.length ? ': ' + errors.join('; ') : ''));
await browser.close();
if (failures.length) { console.log(`\nупало: ${failures.length}`); process.exit(1); }
console.log('\nвсе проверки прошли');
