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
    const h = s.scrollHeight, ch = s.clientHeight;
    if (!was) s.classList.remove('cur');
    return { title: s.getAttribute('data-title') || (s.querySelector('.slide-title, h1') || {}).textContent || '', h, ch };
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
check(deckInfo.slides[0].title.startsWith('ФАКТ | '), 'титул «ФАКТ | спринт» — в оглавлении');
check(await p.evaluate(() => { const t = document.querySelector('.title-slide');
  return !t.querySelector('h1, .t-kicker, .t-status, .t-period, .t-days, .t-foot') && t.textContent.indexOf('Данные JIRA') === -1; }),
      'на титуле только карточки команд: без «Отчёт о…», статуса, «ФАКТ | период», строки спринтов и подписи');
check(await p.evaluate(() => !document.querySelector('#deckSlides .ln-meta')), 'в строке направления нет «ключ эпика · N задач в спринте»');
check(deckInfo.heroes === deckInfo.teams, 'у каждой команды — разделитель с её именем, в порядке вкладок');
check(deckInfo.slides.some(s => s.title.startsWith('OBJ 1: Партнёрские заказы')), 'слайд — цель: «OBJ 1: название»');
check(deckInfo.slides.some(s => s.title.startsWith('Без привязки к OKR')), 'эпики без цели — «Без привязки к OKR»');
check(!deckInfo.slides.some(s => s.title.startsWith('Стримы')) && !deckInfo.legend, 'нет «Стримы: команда» и пояснения цветов');
check(deckInfo.rows === deckInfo.epics && deckInfo.storyRows === 0, 'строка — эпик (и «Вне эпиков»), историй построчно на слайдах нет');
check(!deckInfo.slides.some(s => /^(Изменения в процессе спринта|Демо|Итоги спринта)/.test(s.title)), 'слайдов «Изменения», «Демо», «Итоги» нет');
check(deckInfo.slides.filter(s => !/^(OBJ|Без привязки|Направления|.+ · операционный)/.test(s.title)).every(s => s.h <= s.ch),
      'титул, команда, «Сроки», «Планы» умещаются на экран без прокрутки');
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
  panels: document.querySelectorAll('.hero-slide .h-panel').length,
  sub: [...document.querySelectorAll('#deckSlides .fslide .slide-sub')].some(x => /строка — направление/.test(x.textContent)),
  centered: getComputedStyle(document.querySelector('.hero-slide')).textAlign,
  note: document.body.textContent.includes('ИИ-агент PO по данным'),
  krTail: [...document.querySelectorAll('#deckSlides tr.erow td.task')].some(td => /Sprint Goal|· эпик «/.test(td.textContent)) }));
check(heads.cards === TEAMS_N(deckInfo) && /^\d+%$/.test(heads.big), 'титул: по карточке на команду с долей закрытых историй');
check(heads.hero === deckInfo.teams.split('|')[0] && heads.kpis === 2 && heads.goals >= 1 && heads.centered === 'center',
      'слайд команды: имя, задачи и SP, цели карточками');
check(heads.panels === 0, 'на слайде команды нет панелей «заблокированы / не успели»');
check(!heads.sub, 'на слайдах направлений нет подписи «строка — направление, истории — по клику»');
check(!heads.note && !heads.krTail, 'нет подписи про агента и «эпик · Sprint Goal» в строках');

// сцена: один слайд на всю площадь, навигация кнопками; «Слайды» — выезжающий сайдбар
const stage = await p.evaluate(() => {
  const cur = document.querySelectorAll('#deckSlides > .fslide.cur');
  const r = cur[0].getBoundingClientRect(), feed = document.getElementById('deckFeed').getBoundingClientRect();
  return { cur: cur.length, first: cur[0] === document.querySelector('#deckSlides > .fslide'), w: r.width, feedW: feed.width,
           h: r.height, feedH: feed.height, shadow: getComputedStyle(cur[0]).boxShadow,
           thumbs: document.querySelectorAll('#deckTocList .thumb-box').length,
           tocOpen: document.getElementById('deckToc').classList.contains('open'), count: document.getElementById('deckCount').textContent };
});
check(stage.cur === 1 && stage.first, 'на сцене — один слайд, с первого');
check(Math.abs(stage.w - stage.feedW) < 2 && Math.abs(stage.h - stage.feedH) < 2 && stage.shadow === 'none',
      'слайд — на всю ширину и высоту сцены, без рамки и тени');
const opsFit = await p.evaluate(() => {
  const s = document.querySelector('#deckSlides .fslide.ops:not(.cycle)');
  s.classList.add('cur');
  const over = [...s.querySelectorAll('.mx-row:not(.mx-head) .sbs')].filter(x => {
    const r = x.getBoundingClientRect(), last = x.lastElementChild;
    return last && last.getBoundingClientRect().right > r.right + 1;
  }).length;
  const name = s.querySelector('.mx-row .mx-name').getBoundingClientRect().width / s.getBoundingClientRect().width;
  s.classList.remove('cur');
  return { over, name };
});
check(opsFit.over === 0, 'операционный: блоки задач не вылезают за свой столбец');
check(opsFit.name < 0.12, 'операционный: колонка имени узкая');
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
           legends: s.querySelectorAll('.ops-legend').length, small: [...s.querySelectorAll('.ops-h small')].length };
});
check(!ops.title, 'у операционного слайда нет заголовка');
check(ops.heads.join('|') === 'Производительность за 3 спринта|Сгорание спринта', 'два графика: производительность за 3 спринта и одно сгорание');
check(ops.legends === 0 && ops.small === 0, 'без подписей «без подзадач · день … · клик» и без легенд');
check(ops.big > 2.2 && !ops.ctl, 'графики вытянуты по ширине; диаграмма управления — на слайде «Сроки»');
// снизу — участники: «в спринте» (история и под ней её подзадачи) и «вне спринта»; метрики — в сайдбаре участника
const mx = await p.evaluate(() => {
  const s = document.querySelector('#deckSlides .fslide.ops:not(.cycle)');
  const blocks = [...s.querySelectorAll('.mx-row:not(.mx-head) .sbs:nth-child(2) .sb')];
  return { rows: [...s.querySelectorAll('.mx-row:not(.mx-head)')].length,
           heads: [...s.querySelectorAll('.mx-head span')].map(x => x.textContent).filter(Boolean).join('|'),
           extra: s.querySelectorAll('.mx-btn, .mx-legend, .mx-stuck, .mx-n').length,
           blocks: blocks.length, withSubs: blocks.filter(b => b.querySelectorAll('.sb-subs i').length).length,
           off: s.querySelectorAll('.sb.off').length,
           sep: (s.querySelector('.mx-sep') || {}).textContent || '', ext: [...s.querySelectorAll('.mx-name')].filter(n => n.textContent.startsWith('[EXT]')).length };
});
check(mx.heads === 'В спринте|Вне спринта' && mx.extra === 0, 'два графика: в спринте и вне спринта; столбцов SP, задач и подзадач нет');
check(mx.blocks > 0 && mx.withSubs > 0, 'блок на историю: сверху история, под ней её подзадачи');
check(mx.off > 0, 'вне спринта — задачи отдельными блоками');
check(mx.ext > 0 && mx.sep.startsWith('[EXT]'), 'участники вне состава команды — отдельно, с меткой [EXT]');
await p.click('#deckSlides .fslide.ops:not(.cycle) .mx-name .mname >> nth=0');
await p.waitForTimeout(300);
const mk = await p.evaluate(() => [...document.querySelectorAll('#storiesBody .mkpis .ck span')].map(x => x.textContent).join('|'));
check((await p.textContent('#stackKey')).startsWith('Участник') &&
      mk === 'SP план / факт|задачи план / факт|LT задач|подзадачи план / факт|LT подзадач|вне спринта',
      'клик по имени — сайдбар участника: SP, задачи и подзадачи план/факт/LT, вне спринта — сверху');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
await p.click('#deckSlides .fslide.ops:not(.cycle) .mx-row:not(.mx-head) .sbs:nth-child(2) .sb >> nth=0');
await p.waitForTimeout(300);
check((await p.$$eval('.side-tab', t => t.map(x => x.textContent.split(' · ')[0]).join('|'))) === 'Все|История|Подзадачи',
      'клик по блоку истории — её активность');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
await p.click('#deckSlides .fslide.ops:not(.cycle) .sb.off >> nth=0');
await p.waitForTimeout(300);
check((await p.textContent('#stackKey')).startsWith('Вне доски') && await p.locator('#storiesBody .es-row').count() > 0,
      'клик по блоку «вне спринта» — сайдбар задач вне спринта с активностью');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
await p.click('#deckSlides .fslide.ops:not(.cycle) [data-burn]');
await p.waitForTimeout(300);
const burnSide = await p.evaluate(() => ({ key: document.getElementById('stackKey').textContent,
  days: document.querySelectorAll('#storiesBody table.burn-tab tbody tr').length, n: TEAMS[0].burndown.days.length,
  lists: [...document.querySelectorAll('#storiesBody .pane-label')].map(x => x.textContent).join('|'),
  tabs: [...document.querySelectorAll('.side-tab')].map(t => t.textContent.split(' · ')[0]).join('|') }));
check(burnSide.key.startsWith('Сгорание спринта') && burnSide.days === burnSide.n && /Закрыто|Не закрыто/.test(burnSide.lists) &&
      burnSide.tabs === 'Без подзадач|С подзадачами', 'клик по сгоранию — из чего построено: по дням и по задачам, с подзадачами и без');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
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
           tis: [...s.querySelectorAll('.tis-h')].map(h => h.childNodes[0].textContent.trim()).join('|'),
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
check(ctl.key.startsWith('Диаграмма управления') && ctl.tabs.length === 3 && ctl.tabs[0].startsWith('Все') && ctl.kpis === 7 && ctl.chart && ctl.rows === 3,
      'клик по cycle time — сайдбар: «Все / Истории / Подзадачи», показатели, диаграмма управления, разбивка по спринтам');
await p.click('.side-tab >> nth=2');
check(await p.isVisible('#storiesBody .cbig svg'), 'вкладка «Подзадачи» — своя диаграмма');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
await p.click('#deckSlides .fslide.cycle [data-tis="blocked"]');
await p.waitForTimeout(300);
const blkSide = await p.evaluate(() => ({ key: document.getElementById('stackKey').textContent, cards: document.querySelectorAll('#storiesBody .bl-card').length,
  label: document.getElementById('storiesLabel').textContent }));
check(blkSide.key.startsWith('Заблокировано') && /почему/.test(blkSide.label), 'клик по «Заблокировано» — разбор: кто, с какого числа, почему, комментарии');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// планы на следующий спринт
await goTo('#deckSlides .fslide.plans');
const plans = await p.evaluate(() => [...document.querySelector('#deckSlides .fslide.plans').querySelectorAll('.pcol')]
  .map(c => [c.querySelector('.pc-head b').textContent, c.querySelectorAll('.prow').length,
              Math.max(0, ...[...c.querySelectorAll('.prow')].map(r => r.getBoundingClientRect().height)), c.querySelector('.pc-head span').textContent,
              c.querySelector('.pr-more') ? +c.querySelector('.pr-more').textContent.replace(/\D/g, '') : 0]));
check(plans.map(x => x[0]).join('|') === 'Взять в работу|Доделать|Возможно войдёт|Эскалировать' && plans.every(x => x[1] <= 15) && plans.some(x => x[1]),
      '«Планы на следующий спринт»: четыре колонки, в т. ч. «Возможно войдёт»');
const pg = await p.evaluate(() => { const s = document.querySelector('#deckSlides .fslide.plans');
  return { heads: s.querySelectorAll('.pg-head').length, keys: s.querySelectorAll('.pr-key').length,
           tip: (s.querySelector('.prow') || {}).title || '' }; });
check(pg.heads > 0 && pg.keys === 0 && /^[A-Z]+-\d+/.test(pg.tip), 'внутри колонок — по направлениям; ключей на слайде нет, ключ — в подсказке');
check(plans.every(x => x[2] < 70 && x[1] + x[4] === parseInt(x[3], 10)), 'строка на задачу (у «Эскалировать» — с пояснением); что не влезло — «ещё N», счётчик колонки — всё');
await p.click('#deckSlides .fslide.plans .pc-head[data-plancol="take"]');
await p.waitForTimeout(300);
const planSide = await p.evaluate(() => ({ key: document.getElementById('stackKey').textContent, rows: document.querySelectorAll('#storiesBody table.plan-tab tr').length,
  keys: document.querySelectorAll('#storiesBody .klink').length, tabs: document.querySelectorAll('.side-tab').length }));
check(planSide.key.startsWith('Планы на следующий спринт') && planSide.rows > 0 && planSide.keys === planSide.rows && planSide.tabs === 4,
      'клик по колонке «Планов» — читаемый список: ключ, суть, приоритет, статус, пояснение');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
await goTo('#deckSlides tr.erow[data-key="INIT-125"]');
const rowCheck = await p.evaluate(() => {
  const tr = document.querySelector('#deckSlides tr.erow[data-key="INIT-125"]');
  const auto = document.querySelector('#deckSlides tr.erow[data-key="INIT-111"]');
  return { cls: tr.className, res: tr.querySelector('.result > span').textContent.trim(), how: tr.querySelector('.result > span').title,
           sub: tr.querySelector('.res-sub').textContent, bar: tr.querySelectorAll('.res-bar i').length,
           tags: tr.querySelectorAll('.tag').length, badge: (tr.querySelector('.blk-badge') || {}).textContent || '',
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
const po = await p.evaluate(() => { const tr = document.querySelector('#deckSlides tr.erow[data-key="INIT-111"]');
  return { res: tr.querySelector('.result > span').textContent, tag: !!tr.querySelector('.res-po'), how: tr.querySelector('.result > span').title }; });
check(po.res === '80%' && po.tag && po.how.startsWith('оценка PO: 80%; по задачам спринта — '), 'готовность по оценке PO — в «Результате», расчёт по задачам — в подсказке');
check(rowCheck.noEpic, 'истории без эпика — строка «Вне эпиков»');
check(rowCheck.tags === 0, 'в комментарии нет меток «не закрыто N» — это видно по результату');
const badge = await p.evaluate(() => { const b = document.querySelector('#deckSlides tr.erow .blk-badge');
  const tr = b && b.closest('tr'); return b ? { text: b.textContent, key: tr.dataset.key || '' } : null; });
check(!!badge && /^🛑 блокаторы: \d+$/.test(badge.text), 'в «Результате» — метка «блокаторы: N»');
check(!!rowCheck.next && await p.evaluate(() => [...document.querySelectorAll('#deckSlides tr.erow')].every(tr => tr.querySelector('[data-edit^="snext:"]'))),
      'следующий шаг есть всегда, у каждой строки');
await goTo('#deckSlides tr.erow .blk-badge');
await p.click('#deckSlides tr.erow .blk-badge >> nth=0');
await p.waitForTimeout(300);
const bl = await p.evaluate(() => ({ key: document.getElementById('stackKey').textContent, text: document.getElementById('storiesBody').textContent,
  cards: document.querySelectorAll('#storiesBody .bl-card').length }));
check(bl.key.startsWith('Блокаторы') && bl.cards > 0 && bl.text.includes('Исполнитель:') && bl.text.includes('Эскалирует:'),
      'клик по «блокаторы» — сайдбар: блокер, исполнитель, кто эскалирует');
await p.click('#storiesBody .bl-open >> nth=0');
await p.waitForTimeout(300);
check(await p.isVisible('.panel-back') && (await p.$$eval('.side-tab', t => t.map(x => x.textContent.split(' · ')[0]).join('|'))) === 'Все|История|Подзадачи',
      'из блокатора — активность истории, в шапке «← Назад»');
await p.click('.panel-back');
await p.waitForTimeout(300);
check((await p.textContent('#stackKey')).startsWith('Блокаторы') && !(await p.isVisible('.panel-back')), '«← Назад» возвращает на прошлый экран');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// ключ задачи: при наведении — JIRA в браузере или JIRA-native (виджет)
await goTo('#deckSlides tr.erow[data-key="INIT-125"]');
await p.click('#deckSlides tr.erow[data-key="INIT-125"] td.task');
await p.waitForTimeout(300);
await p.hover('#stackKey .klink');
await p.waitForTimeout(150);
const km = await p.evaluate(() => [...document.querySelectorAll('.kmenu a')].map(a => a.textContent + '=' + a.getAttribute('href')));
check(km.length === 2 && km[0].startsWith('JIRA — в браузере=') && /\/browse\/INIT-125$/.test(km[0]) && km[1].startsWith('JIRA-native — виджет=') && km[1].includes('INIT-125'),
      'ключ эпика (шапка сайдбара) при наведении: «JIRA — в браузере» и «JIRA-native — виджет»');
await p.mouse.move(5, 5);
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// клик по строке — активность истории
await goTo('#deckSlides tr.erow[data-key="INIT-111"]');
await p.click('#deckSlides tr.erow[data-key="INIT-111"] td.task');
await p.waitForTimeout(300);
const epicTabs = await p.$$eval('.side-tab', t => t.map(x => x.textContent.split(' · ')[0]).join('|'));
const es = await p.evaluate(() => ({ items: document.querySelectorAll('#storiesBody .kr-list .kl-item').length,
  heads: [...document.querySelectorAll('#storiesBody .kl-head')].map(c => c.textContent.split(' · ')[0]),
  wide: document.getElementById('panelStack').classList.contains('wide'),
  cols: getComputedStyle(document.querySelector('#storiesBody .kr2')).gridTemplateColumns.split(' ').length,
  detail: document.querySelectorAll('#storiesBody .kr-detail .sc svg').length }));
check(epicTabs === 'Задачи спринта|Весь эпик' && es.items === 2, 'клик по строке — сайдбар: задачи спринта эпика и «Весь эпик»');
check(es.wide && es.cols === 2, 'сайдбар KR широкий, в два столбца');
check(es.heads.length >= 1, 'слева задачи сгруппированы по статусам');
check(es.detail === 1, 'справа — первая незакрытая задача с активностью');
await p.click('#storiesBody .kl-item:has-text("Агрегация каталога и доступности")');
await p.waitForTimeout(300);
const story = await p.evaluate(() => {
  const st = TEAMS.flatMap(t => t.epics).flatMap(e => e.stories).find(x => x.key === 'INIT-112');
  const box = document.querySelector('#storiesBody .kr-detail');
  return { title: box.querySelector('.kd-title').textContent, text: box.textContent.includes('Агрегация каталога собрана и ждёт приёмки PO.'),
           on: (document.querySelector('#storiesBody .kl-item.on') || {}).textContent || '',
           cal: !!box.querySelector('.sc svg'), items: box.querySelectorAll('.sf-item').length, events: st.events.length,
           first: st.events[0].at < (TEAMS[0].logs.since || '9') };
});
check(story.title === 'Агрегация каталога и доступности' && story.on.includes('Агрегация каталога') && story.text,
      'клик по задаче слева — справа её итог из бизнес-блока');
check(story.cal, 'справа — календарь активности задачи, без перехода');
check(story.items === story.events && story.first, 'лента — вся хронология задачи и подзадач, с её создания, а не только за спринт');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
check(await p.isVisible('#deck') && !(await p.isVisible('#panelStack.open')), 'Esc закрывает сайдбар, колода остаётся');await p.keyboard.press('Escape');
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
