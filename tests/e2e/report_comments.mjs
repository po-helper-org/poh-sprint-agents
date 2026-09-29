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
await p.click('#nAdd');
await p.fill('#nText', 'Этой истории нет в спринте');
await p.fill('#nRef', 'SEO-77 — перелинковка');
await p.press('#nRef', 'Enter');
let prompt = await p.inputValue('#promptOut');
check(prompt.includes(`[Эпик ${epicKey} «`), 'ключ из отчёта раскрывается в сущность');
check(prompt.includes('[Вне отчёта SEO-77 «перелинковка»] Этой истории нет в спринте'), 'ключ вне отчёта сохраняется как есть');
check(prompt.includes('[без привязки] Истории по SEO нет в спринте'), 'заметка без привязки помечена в промте');

// правка: текст и привязка
const lastEdit = '.nitem:last-child [data-edit]';
await p.click(lastEdit);
await p.fill('.nedit-text', 'Истории SEO-77 нет в спринте — завести');
await p.fill('.nedit-ref', '');
await p.click('.nedit [data-save]');
prompt = await p.inputValue('#promptOut');
check(prompt.includes('[без привязки] Истории SEO-77 нет в спринте — завести') && !prompt.includes('Вне отчёта'),
      'заметку можно отредактировать и отвязать');
check((await p.textContent('.nitem:last-child .when')).includes('изм.'), 'у изменённой заметки пометка');

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
await p.click('.nitem:first-child [data-del]');
check(await count() === '6', 'заметка удаляется');
await p.reload();
check(await count() === '6', 'корзина переживает перезагрузку, перенос не повторяется');

// приоритеты у эпиков, историй и подзадач
check((await p.$$('#tableBody .prio[title^="Приоритет:"]')).length > 0, 'приоритет у эпиков в таблице');
await p.click('#tableBody tr:nth-child(1)');
await p.waitForTimeout(250);
check((await p.$$('.story-row .prio[title^="Приоритет:"]')).length > 0, 'приоритет у историй');
check((await p.$$('.sub-item .prio[title^="Приоритет:"]')).length > 0, 'приоритет у подзадач');

// у каждой команды своя корзина
await p.keyboard.press('Escape');
await p.click('[data-team="catalog"]');
check(await count() === '0', 'у другой команды своя корзина');

check(!errors.length, 'ошибок JavaScript нет' + (errors.length ? ': ' + errors.join('; ') : ''));
await browser.close();
if (failures.length) { console.log(`\nупало: ${failures.length}`); process.exit(1); }
console.log('\nвсе проверки прошли');
