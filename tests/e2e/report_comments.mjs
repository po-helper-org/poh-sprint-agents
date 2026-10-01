// E2E страницы отчёта: корзина заметок, привязка, правка, промт, приоритеты — в настоящем Chromium.
//
//   cd tests/e2e && npm install && npm test
//
// Браузер: PLAYWRIGHT_BROWSERS_PATH или CHROME_PATH. Демо-страница собирается
// из demo_data.py, в JIRA не ходим. Код выхода 1 — хотя бы одна проверка упала.
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const page = join(mkdtempSync(join(tmpdir(), 'report-e2e-')), 'report.html');
execFileSync('python3', [join(ROOT, '.claude/skills/actual-sprint/scripts/demo_data.py'), '--html', page]);

const failures = [];
const check = (ok, what) => { console.log((ok ? '✓ ' : '✗ ') + what); if (!ok) failures.push(what); };

const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 },
                                       permissions: ['clipboard-read', 'clipboard-write'] });
const p = await ctx.newPage();
const errors = [];
p.on('pageerror', e => errors.push(e.message));
await p.goto(pathToFileURL(page).href);

const TEAMS_N = (info) => info.teams.split('|').length;
const count = async () => (await p.textContent('#cCount')).trim();
const openBasket = async () => { if (!(await p.isVisible('#notesPanel'))) await p.click('#notesToggle'); };

// корзина в правом верхнем углу; файлов и лога над таблицей больше нет
check(await p.$('#notesExport') === null && await p.$('#clog') === null && await p.$('.note-area') === null,
      'ни заметок-файлов, ни лога над таблицей');
check(await p.isHidden('#notesPanel'), 'корзина закрыта, пока её не открыли');
check(await count() === '2', 'заметки прошлой версии перенесены в корзину');

// заметка без привязки — из корзины
await openBasket();
await p.fill('#nText', 'Истории по SEO нет в спринте');
await p.press('#nText', 'Enter');
check(await count() === '3', 'заметка без привязки добавляется из корзины');
check((await p.inputValue('#nText')) === '', 'поле очищается после добавления');

// привязка из корзины: ключ из отчёта и ключ вне отчёта
const epicKey = await p.evaluate(() => TEAMS[0].epics[0].epicKey);
await p.fill('#nText', 'Проверить объём эпика');
await p.fill('#nRef', epicKey);
await p.press('#nText', 'Enter');
await p.fill('#nText', 'Этой истории нет в спринте');
await p.fill('#nRef', 'SEO-77 — перелинковка');
await p.press('#nRef', 'Enter');
let prompt = await p.inputValue('#promptOut');
check(prompt.includes(`[Эпик ${epicKey} «`), 'ключ из отчёта раскрывается в сущность');
check(prompt.includes('[Вне отчёта SEO-77 «перелинковка»] Этой истории нет в спринте'), 'ключ вне отчёта сохраняется как есть');
check(prompt.includes('[без привязки] Истории по SEO нет в спринте'), 'заметка без привязки помечена в промте');

// правка: текст и привязка
await p.hover('.nrow:last-child');
await p.click('.nrow:last-child [data-edit]');
await p.fill('.nedit-text', 'Истории SEO-77 нет в спринте — завести');
await p.fill('.nedit-ref', '');
await p.press('.nedit-text', 'Enter');
prompt = await p.inputValue('#promptOut');
check(prompt.includes('[без привязки] Истории SEO-77 нет в спринте — завести') && !prompt.includes('Вне отчёта'),
      'заметку можно отредактировать и отвязать');
check((await p.getAttribute('.nrow:last-child', 'title')).includes('изменено'), 'у изменённой заметки время правки в подсказке');
check(await p.$('.nrow:last-child .nref-line') === null, 'у заметки без привязки нет подписи сущности');
check((await p.textContent('.nrow:first-child .nref-line')).startsWith(epicKey), 'у привязанной заметки подпись с ключом');
const hidden = await p.$eval('.nrow:first-child .nacts', el => getComputedStyle(el).opacity);
await p.hover('.nrow:first-child'); await p.waitForTimeout(200);
const shown = await p.$eval('.nrow:first-child .nacts', el => getComputedStyle(el).opacity);
check(hidden === '0' && shown === '1', 'карандаш и мусорка проявляются при наведении');
check(await p.$eval('.nrow:first-child [data-edit] svg', el => !!el) && await p.$eval('.nrow:first-child [data-del] svg', el => !!el), 'действия — иконки');

// правый клик по строке → заметка с привязкой; «Уже оставлено» для той же сущности
await p.keyboard.press('Escape');
await p.click('#tableBody tr:nth-child(1) td.epic', { button: 'right' });
check(await p.isVisible('#cpop'), 'правый клик открывает поле заметки');
check(await p.isVisible('#cpopExisting') && (await p.textContent('#cpopExisting')).includes('Проверить объём эпика'),
      'в поле видно уже оставленное к этой сущности');
await p.fill('#cpopText', 'Ждём DBA');
await p.press('#cpopText', 'Enter');
check(await p.isHidden('#cpop'), 'Enter сохраняет и закрывает поле');

await p.click('#tableBody tr:nth-child(1)');
await p.waitForTimeout(250);
await p.click('.story-row .story-title-wrap >> nth=0', { button: 'right', position: { x: 200, y: 8 } });
await p.fill('#cpopText', 'строка 1\nстрока 2');
await p.click('#cpopSave');
await p.click('.story-toggle:not([disabled]) >> nth=0');
await p.click('.sub-list.open .story-title-wrap >> nth=0', { button: 'right', position: { x: 120, y: 6 } });
await p.keyboard.press('Escape');
check(await p.isHidden('#cpop') && await p.isVisible('#panelStack'), 'Esc закрывает поле, панель остаётся');
check((await p.$$('.story-row .cmark')).length === 1, 'у истории с заметкой счётчик');
await p.keyboard.press('Escape');

// промт и копирование
await openBasket();
check(await count() === '7', 'все заметки в корзине');
await p.click('#copyBtn');
await p.waitForTimeout(150);
const text = await p.evaluate(() => navigator.clipboard.readText());
check(text === await p.inputValue('#promptOut'), 'копируется ровно промт из корзины');
check(text.startsWith('Заметки PO к отчёту спринта'), 'промт начинается с контекста');
check(/\[История INIT-\d+ «.+» · эпик .* · приоритет \S+ · статус .+ · исполнитель .+\] строка 1\n   строка 2/.test(text),
      'у задачи в промте эпик, приоритет, статус, исполнитель; строки сохраняются');

// удаление и перезагрузка
await p.hover('.nrow:first-child');
await p.click('.nrow:first-child [data-del]');
check(await count() === '6', 'заметка удаляется');
await p.reload();
check(await count() === '6', 'корзина переживает перезагрузку, перенос не повторяется');

// приоритеты у эпиков, историй и подзадач
check((await p.$$('#tableBody .prio[title^="Приоритет:"]')).length > 0, 'приоритет у эпиков в таблице');
await p.click('#tableBody tr:nth-child(1)');
await p.waitForTimeout(250);
check((await p.$$('.story-row .prio[title^="Приоритет:"]')).length > 0, 'приоритет у историй');
check((await p.$$('.sub-item .prio[title^="Приоритет:"]')).length > 0, 'приоритет у подзадач');

// «Смотреть весь эпик»: тот же сайдбар, объём эпика по разделам
await p.keyboard.press('Escape');
const noEpicRow = await p.$$eval('#tableBody tr', trs => trs.findIndex(tr => tr.dataset.row === 'no-epic'));
await p.click(`#tableBody tr:nth-child(${noEpicRow + 1})`);
await p.waitForTimeout(200);
check(await p.isHidden('#scopeBtn'), 'у «Без эпика» кнопки «Смотреть весь эпик» нет');
await p.keyboard.press('Escape');
await p.click('#tableBody tr:nth-child(1)');
await p.waitForTimeout(250);
check(await p.isVisible('#scopeBtn'), 'в шапке панели эпика есть «Смотреть весь эпик»');
const keyLink = await p.$eval('#stackKeyLink', a => ({ text: a.textContent, href: a.href, target: a.target, svg: !!a.querySelector('svg') }));
const headKey = await p.evaluate(() => TEAMS[0].epics[0].epicKey);
check(keyLink.text === headKey && keyLink.href.endsWith('/browse/' + headKey) && keyLink.target === '_blank' && keyLink.svg,
      'ключ эпика в шапке — ссылка в JIRA с иконкой внешней ссылки');
check(!(await p.textContent('.stack-head')).includes('Открыть в JIRA'), 'отдельной кнопки «Открыть в JIRA» нет');
await p.click('#scopeBtn');
const scope = await p.evaluate(() => {
  const e = TEAMS[0].epics[0], map = TEAMS[0].statusMap;
  const done = e.scope.filter(i => map[i.status] === 'done').length;
  return { total: e.scope.length, done, left: e.scope.length - done,
           outside: e.scope.filter(i => !i.inSprint).length };
});
check((await p.textContent('.scope-sum .big')).startsWith(`Сделано ${scope.done} из ${scope.total}`), 'сводка «сделано из» по данным');
check((await p.textContent('.scope-sec[data-sec=left] .sec-head .n')).includes(String(scope.left)), 'раздел «Осталось» со счётчиком');
check((await p.textContent('.scope-sec[data-sec=done] .sec-head .n')).includes(String(scope.done)), 'раздел «Сделано» со счётчиком');
check((await p.$$('.scope-sec .story-row')).length === scope.total, 'в объёме все задачи эпика, не только спринта');
check((await p.$$eval('.chip-sprint', els => els.filter(e => !e.classList.contains('now')).length)) === scope.outside,
      'у задач вне текущего спринта метка спринта');
check(await p.isHidden('.scope-sec[data-sec=left] .sec-body') && await p.isHidden('.scope-sec[data-sec=done] .sec-body'),
      'при открытии разделы свёрнуты: видны итог и заголовки');
await p.click('.scope-sec[data-sec=left] .sec-head');
const grp = '.scope-sec[data-sec=left] .scope-group >> nth=0';
const grpRows = await p.$$eval('.scope-sec[data-sec=left] .scope-group', gs => gs[0].querySelectorAll('.story-row').length);
check(await p.locator(grp + ' >> .grp-head').isVisible() && await p.locator(grp + ' >> .grp-body').isHidden() && grpRows > 0,
      'в «Осталось» статусы свёрнуты: заголовок со счётчиком, задачи скрыты');
await p.click(grp + ' >> .grp-head');
check(await p.locator(grp + ' >> .grp-body').isVisible(), 'статус раскрывается по клику');
await p.click(grp + ' >> .grp-head');
check(await p.locator(grp + ' >> .grp-body').isHidden(), 'и сворачивается обратно');
await p.click(grp + ' >> .grp-head');
await p.click('.scope-sec[data-sec=done] .sec-head');
check(await p.isVisible('.scope-sec[data-sec=done] .sec-body'), 'раздел «Сделано» раскрывается');
await p.click('.scope-sec[data-sec=done] .sec-head');
check(await p.isHidden('.scope-sec[data-sec=done] .sec-body'), 'и сворачивается');
await p.click(grp + ' >> .story-row .story-title-wrap >> nth=0', { button: 'right', position: { x: 220, y: 8 } });
await p.fill('#cpopText', 'Заметка из объёма эпика');
await p.press('#cpopText', 'Enter');
check((await p.inputValue('#promptOut')).includes('Заметка из объёма эпика'), 'правый клик по задаче объёма — заметка');
await p.click('#scopeBtn');
check((await p.textContent('#scopeBtn')) === 'Смотреть весь эпик' && (await p.$$('.scope-sec')).length === 0,
      'кнопка возвращает к задачам спринта');
await p.keyboard.press('Escape');

// сводный отчёт: под графиками только легенда, расшифровка — в «i», инсайды ИИ — разделом внизу
await p.click('#metricsLink');
await p.waitForTimeout(300);
check(!(await p.textContent('#storiesBody')).includes('Зелёная точка'), 'под диаграммами нет длинной расшифровки');
check((await p.$$('.metrics-section h3 .info')).length === 4, 'у каждого графика иконка «i»');
const tip = '.metrics-section >> nth=2 >> .info-tip';
check(await p.locator(tip).isHidden(), 'подсказка скрыта до наведения');
await p.locator('.metrics-section >> nth=2 >> .info').hover();
await p.waitForTimeout(250);
check(await p.locator(tip).isVisible(), 'наведение открывает подсказку');
const tipText = await p.locator(tip).textContent();
check(tipText.includes('Как читать') && !tipText.includes('Инсайды ИИ'), 'в подсказке только как читать график');
const tipBox = await p.locator(tip).boundingBox();
check(tipBox.y >= 0 && tipBox.y + tipBox.height <= 900 + 1, 'подсказка целиком в окне');
await p.mouse.move(5, 5);
const ai = await p.evaluate(() => {
  const sec = document.getElementById('aiInsights');
  const all = [...document.querySelectorAll('#storiesBody .metrics-section')];
  return { last: all[all.length - 1] === sec, items: sec.querySelectorAll('.ai-item').length,
           first: sec.querySelector('.ai-item')?.className || '', text: sec.textContent,
           expected: TEAMS[0].insights.observations.length,
           keys: [...sec.querySelectorAll('.ai-keys a')].every(a => a.href.includes('/browse/') && a.target === '_blank') };
});
check(ai.last, 'раздел «Инсайды ИИ» — последним в сводном отчёте');
check(ai.items === ai.expected && ai.items >= 3, 'в разделе все наблюдения агента');
check(ai.first.includes('lv-risk') && ai.text.includes('нужна реакция'), 'первым — главное, с уровнем');
check(ai.text.includes('На что обратить внимание PO') && ai.text.includes('Интерпретация ИИ, не данные'),
      'подзаголовок для PO и пометка «интерпретация, не данные»');
check(ai.keys, 'ключи задач у наблюдения — ссылки в JIRA');
await p.locator('#aiInsights .ai-item >> nth=0').click({ button: 'right', position: { x: 200, y: 30 } });
check((await p.textContent('#cpopTarget')).includes('Инсайд ИИ'), 'правый клик по наблюдению — заметка к нему');
await p.keyboard.press('Escape');
await p.locator('.outlier-row >> nth=0').click({ button: 'right', position: { x: 40, y: 8 } });
await p.fill('#cpopText', 'Разобрать выброс на ретро');
await p.press('#cpopText', 'Enter');
const outPrompt = await p.inputValue('#promptOut');
check(outPrompt.includes('Разобрать выброс на ретро') && /INIT-\d+/.test(outPrompt.split('\n').pop()),
      'правый клик по строке «Выбиваются из коридора» — заметка к задаче');
// Esc снимает слои по одному: поле заметки → корзина → панель
for (let i = 0; i < 4 && await p.evaluate(() => document.getElementById('overlay').classList.contains('open')); i++) {
  await p.keyboard.press('Escape');
  await p.waitForTimeout(100);
}
await p.click('[data-team="mobile"]');
await p.click('#metricsLink');
await p.waitForTimeout(300);
check((await p.textContent('#aiInsights')).includes('/sprint-insights') && !(await p.$('#aiInsights .ai-item')),
      'нет инсайдов для сбора — раздел на месте и говорит, как их получить');
await p.keyboard.press('Escape');
await p.click('[data-team="platform"]');

// у каждой команды своя корзина
await p.keyboard.press('Escape');
await p.click('[data-team="catalog"]');
check(await count() === '0', 'у другой команды своя корзина');

// презентация «ФАКТ | спринт»: от целей — OBJ → KR (эпик) → истории спринта
await p.keyboard.press('Escape');
await p.click('#presBtn');
await p.waitForTimeout(400);
const deckInfo = await p.evaluate(() => ({
  open: !document.getElementById('deck').hidden, hash: location.hash,
  slides: [...document.querySelectorAll('#deckSlides .fslide')].map(s => ({
    title: (s.querySelector('.slide-title, h1') || {}).textContent || '', h: Math.round(s.getBoundingClientRect().height) })),
  toc: document.querySelectorAll('#deckTocList a').length,
  heroes: [...document.querySelectorAll('#deckSlides .hero-slide h1')].map(h => h.textContent).join('|'),
  teams: TEAMS.map(t => t.team).join('|'),
  rows: document.querySelectorAll('#deckSlides tr.row').length,
  stories: TEAMS.reduce((n, t) => n + t.epics.reduce((m, e) => m + e.stories.length, 0), 0),
  legend: !!document.querySelector('#deckSlides .legend'),
}));
check(deckInfo.open && deckInfo.hash === '#presentation', 'кнопка «Презентация» открывает колоду, адрес — #presentation');
check(deckInfo.slides[0].title.startsWith('ФАКТ | '), 'титул «ФАКТ | спринт»');
check(deckInfo.heroes === deckInfo.teams, 'у каждой команды — разделитель с её именем, в порядке вкладок');
check(deckInfo.slides.some(s => s.title.startsWith('OBJ 1: Партнёрские заказы')), 'слайд — цель: «OBJ 1: название»');
check(deckInfo.slides.some(s => s.title.startsWith('Без привязки к OKR')), 'эпики без цели — «Без привязки к OKR»');
check(!deckInfo.slides.some(s => s.title.startsWith('Стримы')) && !deckInfo.legend, 'нет «Стримы: команда» и пояснения цветов');
check(deckInfo.rows === deckInfo.stories, 'в таблицах — все истории спринта, по строке на историю');
check(deckInfo.slides.every(s => s.h === 720), 'каждый слайд — 1280×720');
check(deckInfo.toc === deckInfo.slides.length, 'оглавление — по фактическим слайдам');
check(deckInfo.slides.filter(s => s.title.startsWith('Операционный отчёт')).length === 3 * TEAMS_N(deckInfo),
      'операционный отчёт — три слайда на команду');
const ops = await p.evaluate(() => [...document.querySelectorAll('#deckSlides .fslide.ops')].slice(0, 2)
  .map(s => [...s.querySelectorAll('.metric-card h3')].map(h => h.textContent)));
check(ops.every(t => t.length === 3 && t[0].startsWith('Общий') && t[1].startsWith('Прошлые 2 недели') && t[2].startsWith('Текущие 2 недели')),
      'управление по историям и подзадачам: общий, прошлые и текущие 2 недели');
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
await p.click('#deckSlides tr.grp.kr >> nth=0');
await p.waitForTimeout(300);
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
check((await p.textContent('[data-edit="done:INIT-136"]')).endsWith('Показали PO.'), 'правка текста сохраняется и переживает перезагрузку');
p.once('dialog', d => d.accept());
await p.click('#deckReset');
await p.waitForTimeout(200);
check((await p.textContent('[data-edit="done:INIT-136"]')) === 'Метрики загрузчика собраны, дашборд на ревью.', '«Вернуть текст» возвращает исходный');
await p.keyboard.press('Escape');
check(await p.isHidden('#deck') && (await p.evaluate(() => location.hash)) === '', 'Esc закрывает презентацию и чистит адрес');
await p.goto(pathToFileURL(page).href + '#presentation');
await p.reload();
await p.waitForTimeout(300);
check(await p.isVisible('#deck'), 'ссылка с #presentation открывает сразу колоду');

check(!errors.length, 'ошибок JavaScript нет' + (errors.length ? ': ' + errors.join('; ') : ''));
await browser.close();
if (failures.length) { console.log(`\nупало: ${failures.length}`); process.exit(1); }
console.log('\nвсе проверки прошли');
