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

// колода «ФАКТ | спринт»: от целей — OBJ → KR (эпик) → истории спринта
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
  stories: TEAMS.reduce((n, t) => n + t.epics.reduce((m, e) => m + e.stories.length, 0), 0),
  legend: !!document.querySelector('#deckSlides .legend'),
}));
check(deckInfo.open, 'страница открывается сразу колодой');
check(await p.$('#tableBody') === null && await p.$('#deckClose') === null, 'отчёта PO под колодой нет, выйти некуда');
check(deckInfo.slides[0].title.startsWith('ФАКТ | '), 'титул «ФАКТ | спринт»');
check(deckInfo.heroes === deckInfo.teams, 'у каждой команды — разделитель с её именем, в порядке вкладок');
check(deckInfo.slides.some(s => s.title.startsWith('OBJ 1: Партнёрские заказы')), 'слайд — цель: «OBJ 1: название»');
check(deckInfo.slides.some(s => s.title.startsWith('Без привязки к OKR')), 'эпики без цели — «Без привязки к OKR»');
check(!deckInfo.slides.some(s => s.title.startsWith('Стримы')) && !deckInfo.legend, 'нет «Стримы: команда» и пояснения цветов');
check(deckInfo.rows === deckInfo.stories, 'в таблицах — все истории спринта, по строке на историю');
check(deckInfo.slides.every(s => s.h === 720), 'каждый слайд — 1280×720, содержимое не вылезает');
check(deckInfo.toc === deckInfo.slides.length, 'оглавление — по фактическим слайдам');
const kinds = await p.evaluate(() => [...document.querySelectorAll('#deckSlides > .fslide')].map(s => s.className));
check(kinds.filter(c => c.includes(' ops')).length === TEAMS_N(deckInfo), 'операционный отчёт — один слайд на команду');
check(kinds.every((c, i) => !c.includes(' ops') || kinds[i + 1].includes(' plans')), 'сразу после операционного — «Планы на следующий спринт»');
// титул и слайд команды: сводка, а не голый текст; ни подписи про агента, ни «эпик · Sprint Goal» в шапках KR
const heads = await p.evaluate(() => ({
  cards: document.querySelectorAll('.title-slide .t-card').length,
  big: document.querySelector('.title-slide .t-card .t-big').textContent,
  hero: document.querySelector('.hero-slide h1').textContent,
  kpis: document.querySelector('.hero-slide').querySelectorAll('.h-kpis > div').length,
  goals: document.querySelector('.hero-slide').querySelectorAll('.h-goal').length,
  centered: getComputedStyle(document.querySelector('.hero-slide')).textAlign,
  note: document.body.textContent.includes('ИИ-агент PO по данным'),
  krTail: [...document.querySelectorAll('#deckSlides tr.grp td')].some(td => /Sprint Goal|· эпик «/.test(td.textContent)) }));
check(heads.cards === TEAMS_N(deckInfo) && /^\d+%$/.test(heads.big), 'титул: по карточке на команду с долей закрытых историй');
check(heads.hero === deckInfo.teams.split('|')[0] && heads.kpis === 3 && heads.goals >= 1 && heads.centered === 'center',
      'слайд команды по центру: имя, три числа, цели карточками');
check(!heads.note && !heads.krTail, 'нет подписи про агента и «эпик · Sprint Goal» в шапках KR');

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

// операционный отчёт: без заголовка; производительность и диаграмма управления, участники тремя группами
const ops = await p.evaluate(() => {
  const s = document.querySelector('#deckSlides .fslide.ops');
  return { title: !!s.querySelector('.slide-title'),
           heads: [...s.querySelectorAll('.ops-h')].map(h => h.textContent),
           cols: [...s.querySelectorAll('table.mtab thead th')].map(h => h.firstChild.textContent),
           sprints: TEAMS[0].output.sprints.map(x => x.name),
           rows: s.querySelectorAll('table.mtab tbody tr').length,
           members: new Set(TEAMS[0].output.sprints.flatMap(x => x.members.map(m => m.name))).size,
           nums: s.querySelectorAll('table.mtab td.mcell[data-tip] .mc-nums > span:not(.sep)').length,
           cells: s.querySelectorAll('table.mtab td.mcell[data-tip]').length,
           streams: s.querySelectorAll('svg circle').length,
           legend: s.querySelector('.ops-legend').textContent };
});
check(!ops.title, 'у операционного слайда нет заголовка');
check(ops.heads[0].startsWith('Общая производительность команды') && ops.heads[1].startsWith('Диаграмма управления за 3 спринта'),
      'слева производительность и диаграмма управления за 3 спринта');
check(ops.streams > 10 && ops.legend.startsWith('Не начатоВ работеВыполнено'), 'точки историй и подзадач; три группы статусов');
check(ops.cols.join('|') === ['Участник', ...ops.sprints, 'Lead time'].join('|'), 'таблица: участник, три спринта, Lead time');
check(ops.rows === ops.members + 1, 'по строке на участника и итог команды');
check(ops.nums === ops.cells * 3, 'в ячейке три числа: не начато · в работе · выполнено');
await p.hover('#deckSlides .fslide.ops td.mcell[data-tip] >> nth=1');
await p.waitForTimeout(150);
const outTip = await p.evaluate(() => { const t = document.querySelector('.deck-tip'); return { shown: !t.hidden, text: t.textContent }; });
check(outTip.shown && ['Backlog / To Do', 'В блоке', 'Ревью', 'Отладка', 'Отменено'].every(x => outTip.text.includes(x)),
      'наведение — раскрытые группы: backlog, в блоке; в работе, ревью, отладка; готово, отменено');
await p.click('#deckSlides .fslide.ops button.mname >> nth=0');
await p.waitForTimeout(300);
const mem = await p.evaluate(() => ({ open: document.getElementById('panelStack').classList.contains('open'),
  tabs: [...document.querySelectorAll('.side-tab')].map(x => x.textContent.split(' · ')[0]),
  first: (document.querySelector('#storiesBody .mi-head') || {}).textContent || '',
  rows: document.querySelectorAll('#storiesBody .mi-row').length }));
check(mem.open && mem.tabs.join('|') === ops.sprints.join('|') && mem.first.startsWith('Выполнено — в зачёт'),
      'клик по участнику — сайдбар его задач по спринтам, сначала то, что пошло в зачёт');
await p.click('.side-tab >> nth=0');
await p.click('#storiesBody .mi-row >> nth=0');
await p.waitForTimeout(200);
check(await p.isVisible('#storiesBody .mi-back') && (await p.locator('#storiesBody .log-item').count()) > 0,
      'клик по задаче — смены статуса и комментарии по ней');
await p.click('#storiesBody .mi-back');
check((await p.locator('#storiesBody .mi-row').count()) > 0, '«← Задачи участника» возвращает к списку');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// планы на следующий спринт
await goTo('#deckSlides .fslide.plans');
const plans = await p.evaluate(() => [...document.querySelector('#deckSlides .fslide.plans').querySelectorAll('.pcol')]
  .map(c => [c.querySelector('.pc-head b').textContent, c.querySelectorAll('.pcard').length]));
check(plans.map(x => x[0]).join('|') === 'Взять в работу|Доделать|Эскалировать' && plans.every(x => x[1] <= 4) && plans.some(x => x[1]),
      '«Планы на следующий спринт»: три колонки карточек');
await goTo('#deckSlides tr.row[data-key="INIT-136"]');
const rowCheck = await p.evaluate(() => {
  const tr = document.querySelector('#deckSlides tr.row[data-key="INIT-136"]');
  const auto = document.querySelector('#deckSlides tr.row[data-key="INIT-126"]');
  return { cls: tr.className, res: tr.querySelector('.result').textContent.trim(), how: tr.querySelector('.result span').title,
           done: tr.querySelector('[data-edit="done:INIT-136"]').textContent, next: !!tr.querySelector('[data-edit="next:INIT-136"]'),
           autoDone: auto.querySelector('[data-edit^="done:"]').textContent, autoNext: (auto.querySelector('[data-edit^="next:"]') || {}).textContent,
           kr: !!document.querySelector('#deckSlides tr.grp.kr b[data-edit^="kr:"]') };
});
check(rowCheck.res === '90%' && rowCheck.cls.includes('stat-yellow'), 'история на ревью — 90%, жёлтая строка');
check(rowCheck.how.includes('стадия 90%'), 'как посчитан результат — в подсказке');
check(rowCheck.done === 'Метрики загрузчика собраны, дашборд на ревью.' && rowCheck.next, 'строка: что сделано одним предложением и след. шаг');
check(/^Сделано: .+\(\d+ из \d+ подзадач\)\.$/.test(rowCheck.autoDone) && !!rowCheck.autoNext,
      'без агента текст строки — из данных: закрытые подзадачи и следующая открытая');
check(rowCheck.kr, 'шапка группы — KR');
// клик по строке — активность истории
await goTo('#deckSlides tr.row[data-key="INIT-112"]');
await p.click('#deckSlides tr.row[data-key="INIT-112"] td.task');
await p.waitForTimeout(300);
const tabs = await p.$$eval('.side-tab', t => t.map(x => x.textContent));
check(await p.isVisible('#panelStack.open') && (await p.textContent('#stackTitle')) === 'Агрегация каталога и доступности' &&
      tabs[0].startsWith('История') && tabs[1].startsWith('Подзадачи'), 'клик по строке — сайдбар: активность истории и подзадач');
check((await p.textContent('#storiesBody')).includes('Бэклог'), 'в активности — перемещение статуса из ленты');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
check(await p.isVisible('#deck') && !(await p.isVisible('#panelStack.open')), 'Esc закрывает сайдбар, колода остаётся');
// клик по KR — объём эпика
await goTo('#deckSlides tr.grp.kr');
await p.click('#deckSlides tr.grp.kr >> nth=0');
await p.waitForTimeout(300);
const eb = await p.evaluate(() => ({ chart: !!document.querySelector('#storiesBody .eb svg'),
  kpis: document.querySelector('#storiesBody .eb-kpis') && document.querySelector('#storiesBody .eb-kpis').textContent,
  first: document.querySelector('#storiesBody').firstElementChild.className }));
check(eb.chart && eb.first === 'eb' && /осталось задач/.test(eb.kpis) && /плановая дата/.test(eb.kpis) && /прогноз/.test(eb.kpis),
      'клик по KR — сверху сгорание эпика: осталось, плановая дата, прогноз');
const krTabs = await p.$$eval('.side-tab', t => t.map(x => x.textContent.split(' · ')[0]));
check(krTabs.join('|') === 'Выполнено|В работе|Осталось', 'клик по KR — сайдбар «Выполнено / В работе / Осталось»');
const krSum = await p.evaluate(() => {
  const e = TEAMS[0].epics[0], n = [...document.querySelectorAll('.side-tab')].reduce((a, b) => a + parseInt(b.textContent.split(' · ')[1], 10), 0);
  return { n, scope: e.scope.length };
});
check(krSum.n === krSum.scope, 'в сайдбаре KR — весь объём эпика');
await p.keyboard.press('Escape');
await p.waitForTimeout(200);
// ПКМ — комментарий
await goTo('#deckSlides tr.row[data-key="INIT-136"]');
await p.click('#deckSlides tr.row[data-key="INIT-136"] td.task', { button: 'right' });
check(await p.isVisible('#cpop') && (await p.textContent('#cpopTarget')).includes('INIT-136'), 'правый клик по строке — комментарий к истории');
await p.fill('#cpopText', 'Уточнить дату выкатки');
await p.press('#cpopText', 'Enter');
check(await p.evaluate(() => document.querySelector('#deckSlides tr.row[data-key="INIT-136"]').classList.contains('commented')),
      'строка с комментарием помечена');
// редактирование текста
await p.click('#deckEdit');
const edEl = p.locator('[data-edit="done:INIT-136"]');
await edEl.click();
await p.keyboard.press('End');
await p.keyboard.type(' Показали PO.');
await p.keyboard.press('Enter');
check(!(await p.isVisible('#panelStack.open')), 'в режиме правки клик не открывает сайдбар');
await p.click('#deckEdit');
await p.reload();
await p.waitForTimeout(300);
await goTo('[data-edit="done:INIT-136"]');
await p.waitForTimeout(300);
check((await p.textContent('[data-edit="done:INIT-136"]')).endsWith('Показали PO.'), 'правка текста сохраняется и переживает перезагрузку');
p.once('dialog', d => d.accept());
await p.click('#deckReset');
await p.waitForTimeout(200);
check((await p.textContent('[data-edit="done:INIT-136"]')) === 'Метрики загрузчика собраны, дашборд на ревью.', '«Вернуть текст» возвращает исходный');
await p.keyboard.press('Escape');
check(await p.isVisible('#deck'), 'Esc колоду не закрывает: это сама страница');

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
