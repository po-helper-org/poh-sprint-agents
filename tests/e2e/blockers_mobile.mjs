// E2E страницы отчёта по блокерам: десктоп и iPhone 15 Pro (393×852).
//
//   cd tests/e2e && npm install && node blockers_mobile.mjs
//
// Страница статическая (без скриптов): проверяем вёрстку — нет горизонтальной
// прокрутки, на телефоне строка таблицы становится карточкой с подписями столбцов,
// «основание» случая раскрывается тапом.
import { chromium, devices } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const dir = mkdtempSync(join(tmpdir(), 'blockers-'));
const page = join(dir, 'blockers.html');
execFileSync('python3', [join(ROOT, '.claude/skills/sprint-blockers/report.py'), '--demo', page]);
const shots = process.env.SHOTS_DIR;

const failures = [];
const check = (ok, what) => { console.log((ok ? '✓ ' : '✗ ') + what); if (!ok) failures.push(what); };
const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});

const desk = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await desk.goto(pathToFileURL(page).href);
check(await desk.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'десктоп: нет горизонтальной прокрутки');
check(await desk.locator('table.cards thead').first().isVisible(), 'десктоп: таблицы с шапкой');
if (shots) await desk.screenshot({ path: join(shots, 'sprint-blockers.png'), fullPage: true });

const { defaultBrowserType, ...iphone } = devices['iPhone 15 Pro'];
const ctx = await browser.newContext({ ...iphone, viewport: { width: 393, height: 852 } });
const p = await ctx.newPage();
await p.goto(pathToFileURL(page).href);
check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'телефон: нет горизонтальной прокрутки');
check(!(await p.locator('table.cards thead').first().isVisible()), 'телефон: шапки таблиц скрыты, строки — карточки');
const label = await p.locator('table.cards td[data-l]').first().evaluate(td => getComputedStyle(td, '::before').content);
check(label.includes('Кого'), `телефон: у ячейки подпись столбца (${label})`);
const basis = p.locator('details summary', { hasText: 'основание' }).first();
await basis.scrollIntoViewIfNeeded();
await basis.tap();
check(await p.locator('details[open]').count() === 1, 'телефон: основание раскрывается тапом');
const tooWide = await p.evaluate(() => [...document.querySelectorAll('body *')]
  .filter(el => el.getBoundingClientRect().right > innerWidth + 1 && !el.closest('.table-wrap')).map(el => el.tagName));
check(tooWide.length === 0, `телефон: ничего не вылезает за экран ${tooWide.slice(0, 5).join(',')}`);
if (shots) { await p.evaluate(() => scrollTo(0, 0)); await p.screenshot({ path: join(shots, 'sprint-blockers-phone.png') }); }

await browser.close();
if (failures.length) { console.error(`провалено: ${failures.length}`); process.exit(1); }
console.log('blockers e2e ✓');
