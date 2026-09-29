// E2E страницы отчёта: комментарии, лог, копирование, приоритеты — в настоящем Chromium.
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

// старые заметки демо-данных переехали в лог, файловых кнопок больше нет
check(await p.$('#notesExport') === null && await p.$('.note-area') === null, 'заметок и выгрузки файлом нет');
check(await p.textContent('#clogCount') === '2', 'заметки прошлой версии перенесены в лог');

// 4: общий комментарий в правом верхнем углу
await p.fill('#genInput', 'Истории по SEO нет в спринте');
await p.press('#genInput', 'Enter');
check((await p.inputValue('#genInput')) === '', 'общее поле очищается после Enter');

// 3: правый клик по эпику в таблице → поле комментария
await p.click('#tableBody tr:nth-child(2) td.epic', { button: 'right' });
check(await p.isVisible('#cpop'), 'правый клик открывает поле комментария');
check((await p.textContent('#cpopTarget')).includes('Эпик'), 'в поле видно, к чему комментарий');
await p.fill('#cpopText', 'Ждём DBA');
await p.press('#cpopText', 'Enter');
check(await p.isHidden('#cpop'), 'Enter сохраняет и закрывает поле');

// правый клик по истории и подзадаче в панели эпика
await p.click('#tableBody tr:nth-child(1)');
await p.waitForTimeout(250);
await p.click('.story-row .story-title-wrap >> nth=0', { button: 'right', position: { x: 200, y: 8 } });
await p.fill('#cpopText', 'строка 1\nстрока 2');
await p.click('#cpopSave');
await p.click('.story-toggle:not([disabled]) >> nth=0');
await p.click('.sub-list.open .story-title-wrap >> nth=0', { button: 'right', position: { x: 120, y: 6 } });
await p.keyboard.press('Escape');
check(await p.isHidden('#cpop') && await p.isVisible('#panelStack'), 'Esc закрывает поле, панель остаётся');
check((await p.$$('.epic-comments .clog-item')).length === 2, 'комментарии эпика видны в его панели');
await p.keyboard.press('Escape');

// 1: лог сверху и копирование текстом
check(await p.textContent('#clogCount') === '5', 'все комментарии в логе сверху');
await p.click('#clogCopy');
await p.waitForTimeout(150);
const text = await p.evaluate(() => navigator.clipboard.readText());
check(text.startsWith('Комментарии к отчёту спринта'), 'копируется текст с шапкой');
check(/3\. .*· Общее\n   Истории по SEO нет в спринте/.test(text), 'общий комментарий в тексте');
check(/История INIT-\d+ «.+» · эпик .* · приоритет \S+/.test(text), 'у задачи в тексте эпик и приоритет');
check(text.includes('   строка 1\n   строка 2'), 'многострочный комментарий сохраняет строки');

// удаление и перезагрузка
await p.click('.clog-del >> nth=0');
check(await p.textContent('#clogCount') === '4', 'комментарий удаляется');
await p.reload();
check(await p.textContent('#clogCount') === '4', 'лог переживает перезагрузку, перенос заметок не повторяется');

// 2: приоритеты у эпиков, историй и подзадач
const prios = await p.$$eval('#tableBody .prio[title^="Приоритет:"]', els => els.length);
check(prios > 0, 'приоритет у эпиков в таблице');
await p.click('#tableBody tr:nth-child(1)');
await p.waitForTimeout(250);
check((await p.$$('.story-row .prio[title^="Приоритет:"]')).length > 0, 'приоритет у историй');
check((await p.$$('.sub-item .prio[title^="Приоритет:"]')).length > 0, 'приоритет у подзадач');

// лог у каждой команды свой
await p.keyboard.press('Escape');
await p.click('[data-team="catalog"]');
check(await p.textContent('#clogCount') === '0', 'у другой команды свой лог');

check(!errors.length, 'ошибок JavaScript нет' + (errors.length ? ': ' + errors.join('; ') : ''));
await browser.close();
if (failures.length) { console.log(`\nупало: ${failures.length}`); process.exit(1); }
console.log('\nвсе проверки прошли');
