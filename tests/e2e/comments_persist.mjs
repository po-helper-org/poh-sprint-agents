// E2E: комментарии отчёта не пропадают — ни при перезагрузке, ни при смене спринта,
// ни при битой записи, ни после очистки localStorage (копия в IndexedDB). Корзина
// показывает комментарии всех команд, а не только первой открытой.
//
//   cd tests/e2e && npm install && node comments_persist.mjs
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const page = join(mkdtempSync(join(tmpdir(), 'comments-e2e-')), 'business.html');
execFileSync('python3', [join(ROOT, '.claude/skills/actual-sprint/scripts/demo_data.py'), '--business', page]);

const failures = [];
const check = (ok, what) => { console.log((ok ? '✓ ' : '✗ ') + what); if (!ok) failures.push(what); };

const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const p = await ctx.newPage();
const errors = [];
p.on('pageerror', e => errors.push(e.message));
const open = async () => { await p.goto(pathToFileURL(page).href); await p.waitForTimeout(500); };
const comment = async (sel, text) => {
  await p.evaluate(sel => {
    const s = document.querySelector(sel).closest('#deckSlides > .fslide');
    document.querySelectorAll('#deckTocList a')[[...document.querySelectorAll('#deckSlides > .fslide')].indexOf(s)].click();
  }, sel);
  await p.waitForTimeout(150);
  await p.click(sel, { button: 'right' });
  await p.fill('#cpopText', text);
  await p.press('#cpopText', 'Enter');
  await p.waitForTimeout(100);
};
const panel = async () => p.evaluate(() => ({ n: +document.getElementById('cCount').textContent,
  btn: +document.getElementById('deckNotesN').textContent,
  text: document.getElementById('itemsList').textContent, prompt: document.getElementById('promptOut').value }));

await open();
const teams = await p.evaluate(() => TEAMS.map(t => t.slug));
const base = (await panel()).n;          // в демо-данных — заметки старого формата, перенесённые в корзину
await comment('#deckSlides tr.erow[data-team="' + teams[0] + '"] td.task', 'Комментарий к первой команде');
await comment('#deckSlides tr.erow[data-team="' + teams[1] + '"] td.task', 'Комментарий ко второй команде');

await open();
let s = await panel();
check(s.btn === base + 2, 'кнопка «Комментарии (N)» после перезагрузки показывает все комментарии, а не 0');
check(s.n === base + 2 && s.text.includes('Комментарий к первой команде') && s.text.includes('Комментарий ко второй команде'),
      'после перезагрузки корзина показывает комментарии всех команд, а не только первой');
check(s.prompt.includes('Комментарий ко второй команде') && (s.prompt.match(/Команда «/g) || []).length >= 2,
      'промт для ИИ — по блоку на каждую команду с комментариями');

// прошлый спринт: комментарии старого формата (ключ со спринтом) не теряются
await p.evaluate(slug => localStorage.setItem('actual-sprint:' + slug + ':comments:Спринт 1',
  JSON.stringify([{ id: 'old1', at: '2026-01-01T10:00:00Z', target: { kind: 'general' }, text: 'Комментарий прошлого спринта' }])), teams[0]);
await open();
s = await panel();
check(s.n === base + 3 && s.text.includes('Комментарий прошлого спринта'), 'комментарии прошлых спринтов видны после смены спринта');
check(await p.evaluate(slug => !!localStorage.getItem('actual-sprint:' + slug + ':comments:Спринт 1'), teams[0]),
      'старые ключи не удаляются');

// битая запись не затирается следующим сохранением
const key = await p.evaluate(slug => Object.keys(localStorage).find(k => k === 'actual-sprint:' + slug + ':comments'), teams[0]);
check(!!key, 'комментарии лежат под постоянным ключом команды, без имени спринта');
await p.evaluate(k => localStorage.setItem(k, '[{"id":"x1","text":"битая'), key);
await open();
await comment('#deckSlides tr.erow[data-team="' + teams[0] + '"] td.task', 'После битой записи');
check(await p.evaluate(k => Object.keys(localStorage).some(x => x.startsWith(k + ':corrupt:') &&
      localStorage.getItem(x).includes('битая')), key), 'битая запись сохранена отдельно, а не затёрта');

// localStorage очищен — комментарии возвращаются из копии в IndexedDB
await open();
const before = (await panel()).n;
await p.evaluate(() => Object.keys(localStorage).filter(k => /:comments/.test(k)).forEach(k => localStorage.removeItem(k)));
await open();
await p.waitForTimeout(500);
s = await panel();
check(s.n === before && s.text.includes('Комментарий ко второй команде'), 'после очистки localStorage комментарии восстановлены из IndexedDB');

// удаление — только руками: удалённый комментарий не воскресает из копии
await p.click('#deckNotes');
await p.waitForTimeout(150);
const delText = await p.evaluate(() => document.querySelector('#itemsList .nrow .ntext').textContent);
await p.click('#itemsList .nrow [data-del]');
await p.waitForTimeout(200);
await open();
await p.waitForTimeout(400);
s = await panel();
check(s.n === before - 1 && !s.text.includes(delText.slice(0, 20)), 'удалённый вручную комментарий не возвращается');

// «Очистить комментарии» — стирает всё, после подтверждения; копия в IndexedDB их не возвращает
await open();
await p.waitForTimeout(300);
await p.click('#deckNotes');
await p.waitForTimeout(150);
let asked = '';
p.once('dialog', d => { asked = d.message(); d.accept(); });
await p.click('#clearAll');
await p.waitForTimeout(300);
check(asked.startsWith('Удалить все комментарии') && (await panel()).n === 0, '«Очистить комментарии» — после подтверждения корзина пуста');
await open();
await p.waitForTimeout(500);
check((await panel()).n === 0, 'после перезагрузки комментарии не вернулись');
await p.evaluate(() => Object.keys(localStorage).filter(k => /:comments/.test(k)).forEach(k => localStorage.removeItem(k)));
await open();
await p.waitForTimeout(500);
check((await panel()).n === 0 && await p.evaluate(() => document.getElementById('clearAll').disabled),
      'и из копии в IndexedDB не восстановились; кнопка неактивна, пока корзина пуста');

check(!errors.length, 'ошибок JavaScript нет' + (errors.length ? ': ' + errors.join('; ') : ''));
await browser.close();
if (failures.length) { console.log(`\nупало: ${failures.length}`); process.exit(1); }
console.log('\nвсе проверки прошли');
