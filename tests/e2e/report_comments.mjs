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
await p.click('.scope-sec[data-sec=done] .sec-head');
check(await p.isHidden('.scope-sec[data-sec=done] .sec-body'), 'раздел сворачивается');
await p.click('.scope-sec[data-sec=left] .story-row .story-title-wrap >> nth=0', { button: 'right', position: { x: 220, y: 8 } });
await p.fill('#cpopText', 'Заметка из объёма эпика');
await p.press('#cpopText', 'Enter');
check((await p.inputValue('#promptOut')).includes('Заметка из объёма эпика'), 'правый клик по задаче объёма — заметка');
await p.click('#scopeBtn');
check((await p.textContent('#scopeBtn')) === 'Смотреть весь эпик' && (await p.$$('.scope-sec')).length === 0,
      'кнопка возвращает к задачам спринта');
await p.keyboard.press('Escape');

// у каждой команды своя корзина
await p.keyboard.press('Escape');
await p.click('[data-team="catalog"]');
check(await count() === '0', 'у другой команды своя корзина');

check(!errors.length, 'ошибок JavaScript нет' + (errors.length ? ': ' + errors.join('; ') : ''));
await browser.close();
if (failures.length) { console.log(`\nупало: ${failures.length}`); process.exit(1); }
console.log('\nвсе проверки прошли');
