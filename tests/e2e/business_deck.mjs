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
// шапка — в меню бургера (shared/burger.html): прежние кнопки скрыты, пункт меню нажимает их
const viaMenu = async (id, tap = false) => {
  const hit = (sel) => (tap ? p.tap(sel) : p.click(sel));
  await hit('#burgerBtn');
  await hit(`#burgerBody [data-bm-click="${id}"]`);
};
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
      'титул, команда, роадмап и «Риски и проблемы» умещаются на экран без прокрутки');
check(deckInfo.toc === deckInfo.slides.length, 'оглавление — по фактическим слайдам');
const kinds = await p.evaluate(() => [...document.querySelectorAll('#deckSlides > .fslide')].map(s => s.className));
const isOps = c => c.includes(' ops') && !c.includes(' members');
check(kinds.filter(isOps).length === TEAMS_N(deckInfo), 'операционный отчёт — один слайд на команду');
check(kinds.every((c, i) => !isOps(c) || kinds[i + 1].includes(' members')), 'сразу после операционного — «Участники»');
check(kinds.every((c, i) => !c.includes(' members') || kinds[i + 1].includes(' roadmap')), 'после «Участников» — роадмап «Инициативы по спринтам»');
check(kinds.every((c, i) => !c.includes(' roadmap') || kinds[i + 1].includes(' risks')), 'после роадмапа — «Риски и проблемы» команды');
check(!kinds.some(c => c.includes(' plans')) && kinds.filter(c => c.includes(' risks')).length === TEAMS_N(deckInfo),
      '«Планов на следующий спринт» нет; «Риски и проблемы» — у каждой команды, общего слайда в конце нет');
check(!kinds.some(c => c.includes(' cycle')), 'слайда «Сроки» нет');
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
  const s = document.querySelector('#deckSlides .fslide.members');
  s.classList.add('cur');
  const over = [...s.querySelectorAll('.mx-row:not(.mx-head) .sbs')].filter(x => {
    const r = x.getBoundingClientRect(), last = x.lastElementChild;
    return last && last.getBoundingClientRect().right > r.right + 1;
  }).length;
  const name = s.querySelector('.mx-row .mx-name').getBoundingClientRect().width / s.getBoundingClientRect().width;
  s.classList.remove('cur');
  return { over, name };
});
check(opsFit.over === 0, 'участники: блоки задач не вылезают за свой столбец');
check(opsFit.name < 0.12, 'участники: колонка имени узкая');
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
// комментарий к выбранной задаче прямо в сайдбаре: уходит в корзину (к ИИ-агенту) с привязкой к задаче
const cbox = async (scope, text) => {
  const before = await p.evaluate(() => loadComments().length);
  await p.fill(scope + ' .cbox-text', text);
  await p.click(scope + ' .cbox-add');
  await p.waitForTimeout(200);
  return p.evaluate(([scope, before, text]) => {
    const box = document.querySelector(scope + ' .cbox'), list = loadComments(), last = list[list.length - 1];
    return { key: box.dataset.key, added: list.length === before + 1, target: last && last.target.key, text: last && last.text,
             shown: box.textContent.includes(text), empty: box.querySelector('.cbox-text').value === '',
             count: +document.getElementById('cCount').textContent };
  }, [scope, before, text]);
};
await goTo('#deckSlides .fslide.ops:not(.cycle):not(.members)');
check(await p.isVisible('#deckSlides .fslide.ops:not(.cycle):not(.members)') &&
      await p.evaluate(() => document.querySelector('#deckTocList a.cur') !== null), 'переход к слайду из списка, текущий отмечен');

// операционный отчёт: без заголовка; крупно производительность и сгорание спринта, под ними — диаграмма управления;
// участники — следующим слайдом
const ops = await p.evaluate(() => {
  const s = document.querySelector('#deckSlides .fslide.ops:not(.cycle):not(.members)');
  return { title: !!s.querySelector('.slide-title'),
           heads: [...s.querySelectorAll('.ops-h')].map(h => h.firstChild.textContent),
           table: !!s.querySelector('table.mtab'), ctl: !!s.querySelector('.cyc[data-ctl] svg circle'), mx: !!s.querySelector('.mx'),
           big: (r => r.width / r.height)(s.querySelector('.ops-chart svg').getBoundingClientRect()),
           legends: s.querySelectorAll('.ops2b .ops-legend').length, small: [...s.querySelectorAll('.ops-h small')].length };
});
check(!ops.title, 'у операционного слайда нет заголовка');
check(ops.heads.join('|') === 'Производительность за 3 спринта|Сгорание спринта',
      'сверху два графика: производительность за 3 спринта и одно сгорание');
check(ops.legends === 0 && ops.small === 0, 'без подписей «без подзадач · день … · клик» и без легенд');
check(ops.big > 2.2 && ops.ctl && !ops.mx, 'графики вытянуты по ширине; снизу cycle time с точками; участников на слайде нет');
// слайд «Участники»: «из прошлого спринта» и «текущий спринт» (история и под ней её подзадачи), «вне спринта»;
// метрики — в сайдбаре участника
const mx = await p.evaluate(() => {
  const s = document.querySelector('#deckSlides .fslide.members');
  const blocks = [...s.querySelectorAll('.mx-row:not(.mx-head) .sbs:nth-child(2) .sb, .mx-row:not(.mx-head) .sbs:nth-child(3) .sb')];
  const carried = s.querySelectorAll('.mx-row:not(.mx-head) .sbs:nth-child(2) .sb').length;
  return { rows: [...s.querySelectorAll('.mx-row:not(.mx-head)')].length,
           heads: [...s.querySelectorAll('.mx-head span')].map(x => x.textContent).filter(Boolean).join('|'),
           extra: s.querySelectorAll('.mx-btn, .mx-legend, .mx-stuck, .mx-n').length,
           tag: s.querySelector('.ops-tag').textContent, carried,
           blocks: blocks.length, withSubs: blocks.filter(b => b.querySelectorAll('.sb-subs i').length).length,
           off: s.querySelectorAll('.sb.off').length,
           sep: (s.querySelector('.mx-sep') || {}).textContent || '', ext: [...s.querySelectorAll('.mx-name')].filter(n => n.textContent.startsWith('[EXT]')).length };
});
check(/ · участники$/.test(mx.tag), 'отдельный слайд «Команда · участники»');
check(mx.heads === 'Задачи из прошлого спринта|Текущий спринт|Вне спринта' && mx.extra === 0,
      'три столбца: из прошлого спринта, текущий спринт, вне спринта; столбцов SP, задач и подзадач нет');
check(mx.carried > 0, 'история, которая была и в прошлом спринте, — в столбце «из прошлого спринта»');
check(mx.blocks > 0 && mx.withSubs > 0, 'блок на историю: сверху история, под ней её подзадачи');
check(mx.off > 0, 'вне спринта — задачи отдельными блоками');
check(mx.ext > 0 && mx.sep.startsWith('[EXT]'), 'участники вне состава команды — отдельно, с меткой [EXT]');
// подсказка на блоке истории — сколько висит: в текущем статусе, lead time (закрыта — за сколько)
const tips = await p.$$eval('#deckSlides .fslide.members .sb:not(.off)', bs => bs.map(b => b.title));
check(tips.length && tips.every(x => /⏱ (в статусе «[^»]+» \d+ дн\. \(с \d\d\.\d\d\)|закрыта \d\d\.\d\d)/.test(x)),
      'наведение на историю — сколько дней в текущем статусе (закрытая — когда закрыта)');
check(tips.some(x => /⏱ lead time \d+ дн\. \(создана \d\d\.\d\d\)/.test(x)) &&
      tips.some(x => /⏱ cycle time \d+ дн\. \(в работе с \d\d\.\d\d\)/.test(x)),
      'в подсказке lead time (с создания) и cycle time (с начала работы) — до закрытия или до сбора');
await goTo('#deckSlides .fslide.members');
await p.click('#deckSlides .fslide.members .mx-name .mname >> nth=0');
await p.waitForTimeout(300);
const mk = await p.evaluate(() => [...document.querySelectorAll('#storiesBody .mkpis .ck span')].map(x => x.textContent).join('|'));
check((await p.textContent('#stackKey')).startsWith('Участник') &&
      mk === 'SP план / факт|задачи план / факт|LT задач|подзадачи план / факт|LT подзадач|вне спринта',
      'клик по имени — сайдбар участника: SP, задачи и подзадачи план/факт/LT, вне спринта — сверху');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
await p.click('#deckSlides .fslide.members .mx-row:not(.mx-head) .sbs:nth-child(3) .sb >> nth=0');
await p.waitForTimeout(300);
check((await p.$$eval('.side-tab', t => t.map(x => x.textContent.split(' · ')[0]).join('|'))) === 'Все|История|Подзадачи',
      'клик по блоку истории — её активность');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
await p.click('#deckSlides .fslide.members .sb.off >> nth=0');
await p.waitForTimeout(300);
check((await p.textContent('#stackKey')).startsWith('Вне доски') && await p.locator('#storiesBody .es-row').count() > 0,
      'клик по блоку «вне спринта» — сайдбар задач вне спринта с активностью');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
await goTo('#deckSlides .fslide.ops:not(.cycle):not(.members)');
await p.click('#deckSlides .fslide.ops:not(.cycle):not(.members) [data-burn]');
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
// низ операционного: cycle time по спринтам со скользящими средними; клик — разбор
await goTo('#deckSlides .fslide.ops:not(.members)');
const cyc = await p.evaluate(() => {
  const s = document.querySelector('#deckSlides .fslide.ops:not(.members)');
  const svg = s.querySelector('.cyc svg');
  return { delta: s.querySelectorAll('.tis-d').length,
           points: svg.querySelectorAll('circle').length, lines: svg.querySelectorAll('path.cyc-avg').length,
           bandsSigma: svg.querySelectorAll('path.cyc-band').length,
           bands: [...svg.querySelectorAll('text')].map(t => t.textContent).filter(t => /^С\d+/.test(t)).length,
           ends: [...svg.querySelectorAll('text')].map(t => t.textContent).filter(t => t === 'Истории' || t === 'Подзадачи').length };
});
check(cyc.delta === 0, 'cycle time: без оценок «хуже / лучше»');
check(cyc.points > 10 && cyc.lines === 2 && cyc.bandsSigma === 2 && cyc.bands === 3 && cyc.ends === 2,
      'точки историй и подзадач, два скользящих средних с коридором ±σ и подписью в конце, полосы трёх спринтов');
await p.click('#deckSlides .fslide.ops:not(.members) .cyc');
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
// роадмап «Инициативы по спринтам»: 3 следующих спринта по 2 недели, строки — инициативы, в ячейках — фазы
const PHASES = ['аналитика', 'дизайн', 'бек', 'фронт', 'разработка', 'qa', 'приёмка', 'релиз', 'контент'];
const rm = await p.evaluate(() => [...document.querySelectorAll('#deckSlides .fslide.roadmap')].map(sl => {
  const t = TEAMS.find(x => x.slug === sl.dataset.team);
  return { team: t.slug, title: sl.querySelector('.slide-title').textContent, end: t.burndown.end, agent: !!(t.business && t.business.roadmap),
    ai: t.business && t.business.roadmap ? t.business.roadmap.rows : null,
    sprints: [...sl.querySelectorAll('.rm-sprint')].map(h => [h.dataset.from, h.dataset.to]),
    names: [...sl.querySelectorAll('.rm-sprint b')].map(b => b.textContent), dates: [...sl.querySelectorAll('.rm-sprint span')].map(x => x.textContent),
    rows: [...sl.querySelectorAll('.rm-row')].map(r => ({ key: r.dataset.key || '', name: r.querySelector('.rm-name').textContent,
      cells: [...r.querySelectorAll('.rm-cell')].map(c => c.textContent.trim()) })),
    openEpics: t.epics.filter(e => e.epicKey && e.scope && e.scope.some(it => classifyBucket(it.status, it.category) !== 'done')).length };
}));
const day = iso => new Date(iso + 'T00:00:00Z').getTime() / 86400000;
const MON = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const hd = iso => iso.slice(8, 10) + ' ' + MON[+iso.slice(5, 7) - 1];
check(rm.length === TEAMS_N(deckInfo), 'роадмап — у каждой команды');
check(await p.evaluate(() => [...document.querySelectorAll('#deckSlides .fslide.roadmap')].every(s => !s.querySelector('.slide-sub'))),
      'под заголовком роадмапа подписи нет');
check(rm.every(r => r.sprints.length === 3 && day(r.sprints[0][0]) === day(r.end) + 1 && r.sprints.every(x => day(x[1]) - day(x[0]) + 1 === 14) &&
      r.sprints.every((x, i) => i === 0 || day(x[0]) === day(r.sprints[i - 1][1]) + 1) &&
      r.title === 'Инициативы по спринтам до ' + hd(r.sprints[2][1])),
      'колонки — 3 спринта подряд после текущего, ровно по 2 недели; заголовок «Инициативы по спринтам до 05 дек»');
// имя спринта — {YYYY}Q{n}-S{s}: квартал — по дате окончания, s — двухнедельный спринт от начала квартала
const code = to => { const y = +to.slice(0, 4), q = Math.ceil(+to.slice(5, 7) / 3), qs = y + '-' + String((q - 1) * 3 + 1).padStart(2, '0') + '-01';
  return y + 'Q' + q + '-S' + (Math.floor((day(to) - day(qs)) / 14) + 1); };
check(rm.every(r => r.names.every((n, i) => n === code(r.sprints[i][1])) && r.dates.every((d, i) => d === hd(r.sprints[i][0]) + ' – ' + hd(r.sprints[i][1]))),
      'спринт — «2026Q4-S3» и человекочитаемые даты «22 окт – 04 ноя»');
check(rm.every(r => r.rows.length && r.rows.every(x => x.cells.length === 6 && x.cells.every(c => !c || PHASES.includes(c)))),
      'строка — инициатива, 6 недельных ячеек; в ячейке — фаза из словаря или пусто');
const agentRm = rm.find(r => r.agent), autoRm = rm.find(r => !r.agent);
check(!!agentRm && agentRm.rows.length === agentRm.ai.length && agentRm.rows.every((x, i) => x.cells.join('|') === agentRm.ai[i].cells.concat(Array(6).fill('')).slice(0, 6).join('|')),
      'роадмап агента (roadmap в бизнес-блоке): строки и фазы как у агента');
check(!!autoRm && autoRm.rows.length === Math.min(autoRm.openEpics, 14) &&
      autoRm.rows.every(x => !x.cells.some(c => c) || (x.cells[0] && x.cells.join('|').replace(/^(.*?)(\|+)?$/, '$1').split('|').every(Boolean))),
      'без агента — каркас из данных: открытые эпики, полоса с текущей недели без разрывов');
await goTo('#deckSlides .fslide.roadmap .rm-row[data-key]');
await p.click('#deckSlides .fslide.roadmap .rm-row[data-key] .rm-name >> nth=0');
await p.waitForTimeout(300);
check(await p.evaluate(() => (document.querySelector('.side-tab.active') || {}).dataset?.tab) === 'scope', 'клик по инициативе — сайдбар «Весь эпик»');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// «Риски и проблемы»: метка, проблема, что будет или где нужна помощь — у каждой команды
const KINDS = ['Внешнее', 'Ресурс', 'Общее', 'Срок'];
const rk = await p.evaluate(() => [...document.querySelectorAll('#deckSlides .fslide.risks')].map(sl => {
  const t = TEAMS.find(x => x.slug === sl.dataset.team), b = t.business || {};
  return { team: t.slug, title: sl.querySelector('.slide-title').textContent, agent: (b.risks || []).length,
    agentKinds: (b.risks || []).map(r => r.kind || 'general'),
    blocked: t.epics.some(e => e.stories.some(st => classifyBucket(st.status, st.category) === 'blocked')),
    rows: [...sl.querySelectorAll('.rk-row')].map(r => ({ kind: r.querySelector('.rk-kind').textContent, title: r.querySelector('.rk-title').textContent,
      text: r.querySelector('.rk-text').textContent })) };
}));
const KIND_RU = { external: 'Внешнее', resource: 'Ресурс', general: 'Общее', deadline: 'Срок' };
check(rk.every(r => r.title === 'Риски и проблемы' && r.rows.length <= 5 && r.rows.every(x => KINDS.includes(x.kind) && x.title && x.text)),
      '«Риски и проблемы»: до 5 строк — метка (Внешнее / Ресурс / Общее / Срок), проблема, что будет или какая помощь');
const agentRk = rk.find(r => r.agent);
check(!!agentRk && agentRk.rows.length === agentRk.agent && agentRk.rows.every((x, i) => x.kind === KIND_RU[agentRk.agentKinds[i]]),
      'риски агента — с его метками (без метки — «Общее»)');
const autoRk = await p.evaluate(() => {
  // команда с блокерами, но без рисков агента: блок агента на время убираем
  const t = TEAMS.find(x => x.epics.some(e => e.stories.some(st => /ожида|блок/i.test(st.status))));
  const saved = t.business;
  t.business = {};
  try { return withTeam(t, () => teamRisks(t, teamStreams(t))); } finally { t.business = saved; }
});
check(!autoRk.agent && autoRk.list.some(x => x.kind === 'external' && /нужна помощь — эскалирует/i.test(x.text)),
      'без агента — из данных: блокеры → «Внешнее» с тем, кто эскалирует');
check(rk.some(r => !r.agent && r.rows.some(x => x.kind === 'Срок' && /по темпу/i.test(x.text))),
      'без агента — сдвиг сроков из данных: «Срок», по темпу сгорания — к дд.мм');
await goTo('#deckSlides tr.erow[data-key="INIT-125"]');
const rowCheck = await p.evaluate(() => {
  const tr = document.querySelector('#deckSlides tr.erow[data-key="INIT-125"]');
  const auto = document.querySelector('#deckSlides tr.erow[data-key="INIT-111"]');
  return { cls: tr.className, res: tr.querySelector('.result > span').textContent.trim(), how: tr.querySelector('.result > span').title,
           sub: (tr.querySelector('.res-sub') || {}).textContent || null, bar: tr.querySelectorAll('.res-bar i').length,
           tags: tr.querySelectorAll('.tag').length, badge: (tr.querySelector('.blk-badge') || {}).textContent || '',
           done: tr.querySelector('[data-edit="sdone:platform:INIT-125"]').textContent,
           blk: (tr.querySelector('[data-edit="sblk:platform:INIT-125"]') || {}).textContent,
           next: (tr.querySelector('[data-edit="snext:platform:INIT-125"]') || {}).textContent,
           autoDone: auto.querySelector('[data-edit^="sdone:"]').textContent,
           kr: tr.querySelector('td.task b').textContent,
           noEpic: [...document.querySelectorAll('#deckSlides tr.erow td.task b')].some(b => b.textContent === 'Вне эпиков') };
});
check(/^\d+%$/.test(rowCheck.res) && rowCheck.sub === null && rowCheck.bar > 0, 'результат спринта — процент и полоса историй, без «закрыто X из Y»');
check(!rowCheck.how, 'подсказки «как посчитано» у процента нет');
// типографика как в отчётной колоде: Arial 8 pt слайда 16:9 (≈14px на 1280), «Дальше:» и «Блокер:» — обычный текст в строку
const typo = await p.evaluate(() => {
  const td = document.querySelector('#deckSlides tr.erow[data-key="INIT-125"] td.sum'), cs = getComputedStyle(td);
  return { font: cs.fontFamily, size: cs.fontSize, lines: [...td.querySelectorAll('.lbl')].map(l => {
    const ls = getComputedStyle(l), ps = getComputedStyle(l.parentElement);
    return { text: l.parentElement.textContent, same: ls.color === cs.color && ps.color === cs.color && ls.fontSize === cs.fontSize &&
      ls.textTransform === 'none' && ls.fontWeight === cs.fontWeight && ls.display === 'inline' };
  }) };
});
check(/Arial/.test(typo.font) && typo.size === '14px', 'текст строки — Arial 14px (8 pt на слайде 16:9)');
check(typo.lines.length === 2 && typo.lines.every(l => l.same) && /^Дальше: /.test(typo.lines[0].text) && /^Блокер: /.test(typo.lines[1].text),
      '«Дальше:» и «Блокер:» — обычный текст в строку: тот же цвет, кегль и начертание, без капса');
check(rowCheck.done.startsWith('Метрики загрузчика собраны и на ревью') && rowCheck.blk === 'нет доступа к очереди событий смежной команды' &&
      rowCheck.next === 'эскалация на синке команд в четверг', 'сводка агента: итог, блокер, след. шаг');
check(/^(Закрыто|В работе): .+\.$|^Работа не начата\.$/.test(rowCheck.autoDone), 'без агента сводка — из данных: закрытые истории или что в работе');
check(rowCheck.kr === 'KR 3.1 — платформа выдерживает пиковый сезон', 'строка — KR');
const po = await p.evaluate(() => { const tr = document.querySelector('#deckSlides tr.erow[data-key="INIT-111"]');
  return { res: tr.querySelector('.result > span').textContent, tag: !!tr.querySelector('.res-po'), how: tr.querySelector('.result > span').title }; });
check(po.res === '80%' && po.tag && !po.how, 'готовность по оценке PO — в «Результате» с пометкой «оценка PO»');
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
const bc = await cbox('#storiesBody .bl-card:nth-child(1)', 'Блок снят, вернуть в работу');
check(bc.added && bc.target === bc.key && bc.shown && bc.empty, 'в карточке блокатора — комментарий к этой задаче (актуализировать статус, дать команду)');
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
// редизайн сайдбара: меньше акцентов — без капса с разрядкой, рамок у карточек, статусов и графика, без легенды;
// событие ленты — одна строка, подзадача — серым префиксом в той же строке
const look = await p.evaluate(() => {
  const cs = el => el ? getComputedStyle(el) : null;
  const caps = [...document.querySelectorAll('.stack-head .eyebrow, #storiesLabel, #storiesBody .kl-head, #storiesBody .sf-day')]
    .filter(el => el.offsetParent).map(el => cs(el).textTransform);
  const item = document.querySelector('#storiesBody .kl-item'), tab = document.querySelector('.side-tab:not(.active)');
  const st = document.querySelector('#storiesBody .kr-detail .sf .status');
  const row = [...document.querySelectorAll('#storiesBody .kr-detail .sf-item')].find(r => r.querySelector('.status') && r.querySelector('.sf-sub'));
  const lineH = parseFloat(cs(document.querySelector('#storiesBody .kr-detail .sf-item')).lineHeight) || 18;
  return { caps, itemBorder: cs(item).borderTopWidth, itemLeft: cs(item).borderLeftWidth, tabBorder: cs(tab).borderTopWidth,
           statusBorder: st ? cs(st).borderTopWidth : 'нет статусов', chartBorder: cs(document.querySelector('#storiesBody .sc')).borderTopWidth,
           legend: !!document.querySelector('#storiesBody .sc-legend'),
           oneLine: row ? row.getBoundingClientRect().height < lineH * 1.9 : null };
});
check(look.caps.length >= 3 && look.caps.every(t => t === 'none'), 'в шапке, группах и датах ленты нет капса с разрядкой');
check(look.itemBorder === '0px' && look.itemLeft === '0px', 'задачи слева — без рамок и цветной полосы, выбранная — фоном');
check(look.tabBorder === '0px', 'вкладки — подчёркиванием, без рамок-таблеток');
check(look.statusBorder === '0px' && look.chartBorder === '0px' && !look.legend, 'статусы в ленте — текстом без рамок; график без рамки и легенды');
check(look.oneLine === true, 'событие подзадачи — одна строка: «ключ подзадача · Было → Стало»');
const kc = await cbox('#storiesBody .kr-detail', 'Перевести в «Готово», ревью принято');
check(kc.added && kc.target === kc.key && kc.text === 'Перевести в «Готово», ревью принято' && kc.shown && kc.empty && kc.count > 0,
      'в сайдбаре эпика у выбранной задачи — поле комментария: заметка в корзине с привязкой к задаче и видна под задачей');
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
  secs: [...document.querySelectorAll('#storiesBody .scope-sec:not([data-sec="iter"]) .sec-head')].map(h => h.textContent),
  n: [...document.querySelectorAll('#storiesBody .scope-sec:not([data-sec="iter"]) .sec-head .n')].reduce((a, x) => a + parseInt(x.textContent.replace('·', ''), 10), 0),
  scope: TEAMS[0].epics[0].scope.length }));
check(eb.chart && eb.bars > 5 && /Плановая дата/.test(eb.panel) && /Расчётная дата/.test(eb.panel) && /Темп сгорания/.test(eb.panel),
      '«Весь эпик» — сгорание эпика по неделям, под ним панель анализа: план, расчёт, темп');
check(eb.modes.join('|') === 'SP|Закрытие историй|Закрытие подзадач', 'основа расчёта: SP, закрытие историй, закрытие подзадач');
check(!eb.why, 'без пояснений словами');
check(eb.secs[0].startsWith('Что осталось') && eb.secs[1].startsWith('Что выполнено') && eb.n === eb.scope,
      'ниже — что осталось и что выполнено: весь объём эпика, как в отчёте PO');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// «Прогресс инициативы» — весь эпик в миниатюре: только «N% (+n%)» и полоса todo / в работе (блок) / QA / готово;
// сделано, срок и прогноз — в подсказке полосы; опоздание и просрочка — красным процентом; клик — «Весь эпик»
const SEGS = ['todo', 'progress', 'blocked', 'qa', 'done'];
const ini = await p.evaluate((SEGS) => {
  const th = [...document.querySelector('#deckSlides table.rep.epics thead tr').children].map(x => x.textContent);
  const cells = [...document.querySelectorAll('#deckSlides tr.erow')].map(tr => {
    const c = tr.querySelector('td.init');
    if (!c) return { key: tr.dataset.key || '', missing: true, segs: [] };
    const team = TEAMS.find(t => t.slug === tr.dataset.team);
    const e = tr.dataset.key && team.epics.find(x => x.epicKey === tr.dataset.key);
    const bar = c.querySelector('.ini-bar'), pct = c.querySelector('.ini-pct');
    return { key: tr.dataset.key || '', text: c.textContent.trim(), pct: pct ? pct.textContent : '', pctTitle: pct ? pct.title : '',
             red: !!c.querySelector('.ini-pct.late'), extra: c.querySelectorAll('.res-sub, .ini-due, .ini-fc').length,
             segs: bar ? [...bar.querySelectorAll('i')].map(i => i.dataset.seg) : [],
             n: bar ? [...bar.querySelectorAll('i')].reduce((a, i) => a + parseFloat(i.style.flexGrow), 0) : 0,
             tip: bar ? bar.title : '',
             delta: (c.querySelector('.ini-delta') || {}).textContent || '', deltaTip: (c.querySelector('.ini-delta') || {}).title || '',
             inSprint: e && e.scope ? e.scope.filter(it => classifyBucket(it.status, it.category) === 'done' && it.doneAt &&
               it.doneAt.slice(0, 10) >= team.burndown.start.slice(0, 10)).length : 0,
             scope: e && e.scope ? e.scope.length : null, epicDue: e ? e.epicDue || null : null,
             done: e && e.scope ? e.scope.filter(it => classifyBucket(it.status, it.category) === 'done').length : 0 };
  });
  return { th, cells, order: cells.every(c => c.segs.every((s, i) => i === 0 || SEGS.indexOf(c.segs[i - 1]) < SEGS.indexOf(s))) };
}, SEGS);
const withEpic = ini.cells.filter(c => c.key && c.scope);
const dm = iso => iso.slice(8, 10) + '.' + iso.slice(5, 7);
check(ini.th.join('|') === 'Направление|Итог спринта|Результат спринта|Прогресс инициативы',
      'колонки слайда: «Результат спринта» и рядом «Прогресс инициативы»');
check(ini.cells.every(c => !c.missing), 'у каждой строки-направления есть «Прогресс инициативы»');
check(withEpic.length > 0 && withEpic.every(c => c.n === c.scope && c.pct === Math.round(100 * c.done / c.scope) + '%' &&
      c.text === c.pct + c.delta && !c.extra && !c.pctTitle),
      'в ячейке только «N% (+n%)» и полоса на весь объём эпика: без «сделано», срока, прогноза и подсказки «как посчитано»');
check(ini.order && withEpic.every(c => c.segs.length && c.segs.every(s => SEGS.includes(s))),
      'полоса по порядку: не начато → в работе (блок рядом) → QA → готово');
check(withEpic.every(c => c.tip.includes('сделано ' + c.done + ' из ' + c.scope) && /не начато|в работе|QA|готово/.test(c.tip) &&
      (c.epicDue ? c.tip.includes('срок ' + dm(c.epicDue)) : c.tip.includes('срок не задан'))),
      'в подсказке полосы — сделано X из Y, срок эпика (или «срок не задан»), прогноз и числа по статусам');
check(withEpic.every(c => c.red === /позже срока|просрочен/.test(c.tip)) && withEpic.some(c => c.red),
      'опоздание по прогнозу или просрочка — красный процент, причина — в подсказке');
const overdue = await p.evaluate(() => {
  const t = TEAMS[0], e = t.epics.find(x => x.epicKey && x.scope && x.scope.some(it => classifyBucket(it.status, it.category) !== 'done'));
  const past = Object.assign({}, e, { epicDue: '2026-01-05' });
  const cell = initCell({ epic: past, init: initiative(t, past) }, 'x');
  return { cell, ok: initiative(t, e).overdue === (e.epicDue < t._meta.collectedAt.slice(0, 10)) };
});
check(overdue.ok && /class="ini-pct late"/.test(overdue.cell) && /срок 05\.01 — просрочен/.test(overdue.cell),
      'срок прошёл, а эпик не закрыт — красный процент и «просрочен» в подсказке, даже без прогноза');
check(withEpic.every(c => c.delta === '(+' + Math.round(100 * c.inSprint / c.scope) + '%)' && c.deltaTip.includes('в этом спринте')) &&
      withEpic.some(c => c.inSprint > 0), 'рядом с процентом — «(+n%)»: вклад спринта = задачи эпика, закрытые с начала спринта, от всего объёма');
check(ini.cells.filter(c => !c.key).every(c => c.text === '—'), '«Вне эпиков» — прочерк вместо прогресса инициативы');
const lateCell = withEpic.find(c => /прогноз \d\d\.\d\d/.test(c.tip) && c.epicDue) || withEpic.find(c => c.epicDue) || withEpic[0];
await goTo('#deckSlides tr.erow[data-key="' + lateCell.key + '"]');
await p.click('#deckSlides tr.erow[data-key="' + lateCell.key + '"] td.init');
await p.waitForTimeout(300);
const iniSide = await p.evaluate(() => ({ tab: (document.querySelector('.side-tab.active') || {}).dataset?.tab,
  chart: !!document.querySelector('#storiesBody .eb svg'),
  cells: Object.fromEntries([...document.querySelectorAll('#storiesBody .ea-cell')].map(c => [c.querySelector('.ea-label').textContent, c.querySelector('b').textContent])) }));
check(iniSide.tab === 'scope' && iniSide.chart, 'клик по «Прогрессу инициативы» — сайдбар сразу на «Весь эпик» со сгоранием');
const fcTip = (/прогноз (\d\d\.\d\d)/.exec(lateCell.tip) || [])[1];
check((!lateCell.epicDue || iniSide.cells['Плановая дата'].startsWith(dm(lateCell.epicDue))) &&
      (!fcTip || iniSide.cells['Расчётная дата'].startsWith(fcTip)),
      'срок и прогноз из подсказки совпадают с «Плановой» и «Расчётной датой» сайдбара');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
await p.click('#deckSlides tr.erow[data-key="' + lateCell.key + '"] td.result');
await p.waitForTimeout(300);
check(await p.evaluate(() => (document.querySelector('.side-tab.active') || {}).dataset?.tab) === 'sprint',
      'клик по «Результату спринта» — по-прежнему «Задачи спринта»');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// «Весь эпик»: перед «Что осталось» — «Что сделали за эту итерацию (+n%)» с расчётом и закрытыми задачами
const iterCell = withEpic.find(c => c.inSprint > 0);
await goTo('#deckSlides tr.erow[data-key="' + iterCell.key + '"]');
await p.click('#deckSlides tr.erow[data-key="' + iterCell.key + '"] td.init');
await p.waitForTimeout(300);
const iter = await p.evaluate(() => {
  const secs = [...document.querySelectorAll('#storiesBody .scope-sec')];
  const it = document.querySelector('#storiesBody .scope-sec[data-sec="iter"]');
  return { order: secs.map(x => x.dataset.sec), head: it ? it.querySelector('.sec-head').textContent : '',
           how: it ? (it.querySelector('.iter-how') || {}).textContent || '' : '', rows: it ? it.querySelectorAll('.story-item').length : 0,
           sum: (document.querySelector('#storiesBody .scope-sum .sub') || {}).textContent || '' };
});
check(iter.order.slice(0, 2).join('|') === 'iter|left', '«Весь эпик»: «Что сделали за эту итерацию» стоит перед «Что осталось»');
check(iter.head.startsWith('Что сделали за эту итерацию ' + iterCell.delta) && iter.rows === iterCell.inSprint,
      'в заголовке — тот же «(+n%)», что в строке слайда; внутри — закрытые в спринте задачи');
check(iter.how.includes(iterCell.delta.replace(/[()]/g, '')) && iter.how.includes('÷ ' + iterCell.scope) && /с \d\d\.\d\d/.test(iter.how) &&
      iter.sum.includes(iterCell.delta.replace(/[()]/g, '') + ' за этот спринт'),
      'как посчитано: «+n% = закрыто в спринте X ÷ Y в эпике», с какой даты; итог эпика дополнен «+n% за этот спринт»');
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
await viaMenu('deckEdit');
const edEl = p.locator('[data-edit="sdone:platform:INIT-125"]');
await edEl.click();
// курсор — в конец всего текста: в многострочной сводке End уводит лишь в конец видимой строки
await edEl.evaluate(el => { const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
  const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); });
await p.keyboard.type(' Показали PO.');
await p.keyboard.press('Enter');
check(!(await p.isVisible('#panelStack.open')), 'в режиме правки клик не открывает сайдбар');
await viaMenu('deckEdit');
await p.reload();
await p.waitForTimeout(300);
await goTo('[data-edit="sdone:platform:INIT-125"]');
await p.waitForTimeout(300);
check((await p.textContent('[data-edit="sdone:platform:INIT-125"]')).endsWith('Показали PO.'), 'правка текста сохраняется и переживает перезагрузку');
p.once('dialog', d => d.accept());
await viaMenu('deckReset');
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
await viaMenu('techBtn');
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
