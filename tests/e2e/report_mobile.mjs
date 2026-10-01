// E2E страницы отчёта на телефоне: iPhone 15 Pro (393×852), сенсорный экран, режим PWA.
//
//   cd tests/e2e && npm install && npm test
//
// Наведения и правой кнопки на телефоне нет: заметка — долгим нажатием, подсказка
// «i» — тапом. Долгое нажатие шлём настоящими touch-событиями через CDP, а media
// hover:none / pointer:coarse включаем явно — как у Safari на iPhone.
import { chromium, devices } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');
const page = join(mkdtempSync(join(tmpdir(), 'report-mobile-')), 'report.html');
execFileSync('python3', [join(ROOT, '.claude/skills/actual-sprint/scripts/demo_data.py'), '--html', page]);

const failures = [];
const check = (ok, what) => { console.log((ok ? '✓ ' : '✗ ') + what); if (!ok) failures.push(what); };

const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
const { defaultBrowserType, ...iphone } = devices['iPhone 15 Pro'];
// экран целиком: в режиме PWA панелей Safari нет
const ctx = await browser.newContext({ ...iphone, viewport: { width: 393, height: 852 } });
const p = await ctx.newPage();
const cdp = await ctx.newCDPSession(p);
await cdp.send('Emulation.setEmulatedMedia', {
  features: [{ name: 'hover', value: 'none' }, { name: 'pointer', value: 'coarse' }] });
const errors = [];
p.on('pageerror', e => errors.push(e.message));
await p.goto(pathToFileURL(page).href);

const noSideScroll = async () => p.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
const panelOpen = () => p.evaluate(() => document.getElementById('panelStack').classList.contains('open'));
const longPress = async (selector) => {
  await p.locator(selector).first().scrollIntoViewIfNeeded();
  const box = await p.locator(selector).first().boundingBox();
  const pt = { x: box.x + Math.min(60, box.width / 2), y: box.y + box.height / 2 };
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [pt] });
  await p.waitForTimeout(650);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await p.waitForTimeout(250);
};

// PWA: страницу можно добавить на экран «Домой» и открыть без панелей браузера
const head = await p.evaluate(() => ({
  viewport: document.querySelector('meta[name=viewport]')?.content || '',
  capable: document.querySelector('meta[name=apple-mobile-web-app-capable]')?.content,
  title: document.querySelector('meta[name=apple-mobile-web-app-title]')?.content,
  icon: document.querySelector('link[rel=apple-touch-icon]')?.href || '',
}));
check(head.viewport.includes('width=device-width') && head.viewport.includes('viewport-fit=cover'),
      'viewport по ширине устройства, с учётом чёлки');
check(head.capable === 'yes' && !!head.title, 'режим приложения с экрана «Домой» и короткое имя');
check(head.icon.startsWith('data:image/png;base64,'), 'иконка для экрана «Домой» встроена в страницу');
const iconSize = await p.evaluate(src => new Promise(ok => { const i = new Image(); i.onload = () => ok([i.width, i.height]); i.src = src; }), head.icon);
check(iconSize[0] === 180 && iconSize[1] === 180, 'иконка 180×180, как просит iOS');

// главный экран
check(await noSideScroll(), 'главный экран без горизонтальной прокрутки');
const row = await p.locator('#tableBody tr').first().boundingBox();
const title = await p.locator('#tableBody td.epic').first().boundingBox();
check(title.width > row.width * 0.8, 'название эпика во всю ширину строки, а не узкой колонкой');
check(await p.locator('.team-switch').evaluate(el => getComputedStyle(el).flexWrap === 'nowrap'),
      'вкладки команд — в одну строку с прокруткой');

// долгое нажатие — заметка, а не переход в эпик
await longPress('#tableBody tr >> nth=1');
check(await p.isVisible('#cpop'), 'долгое нажатие на эпик открывает поле заметки');
check(!(await panelOpen()), 'и не открывает панель эпика');
check((await p.textContent('#cpopTarget')).includes('Единый каталог позиций'), 'заметка привязана к нажатому эпику');
check(await p.locator('#cpopText').getAttribute('placeholder') === 'Заметка', 'без подсказки про Enter и Esc');
await p.fill('#cpopText', 'Заметка с телефона');
await p.tap('#cpopSave');
check(await p.isHidden('#cpop') && (await p.textContent('#cCount')).trim() === '3', 'заметка сохраняется кнопкой');

// тап по строке — панель на весь экран
await p.tap('#tableBody tr >> nth=0');
await p.waitForTimeout(350);
check(await panelOpen(), 'тап по эпику открывает панель');
const panel = await p.locator('#panelStack').boundingBox();
check(panel.x === 0 && panel.width === 393, 'панель на всю ширину экрана');
const close = await p.locator('.sidebar-close').boundingBox();
check(close.width >= 44 && close.height >= 44, 'крестик не меньше 44×44 — попадает пальцем');
const story = await p.locator('#storiesBody .story-row').first();
const titleBox = await story.locator('.story-title-wrap').boundingBox();
const metaBox = await story.locator('.meta-wrap').boundingBox();
check(metaBox.y > titleBox.y + titleBox.height - 2, 'статус задачи — второй строкой под названием');
await p.tap('#scopeBtn');
await p.tap('.scope-sec[data-sec=left] .sec-head');
check(await noSideScroll(), '«Весь эпик» без горизонтальной прокрутки');
await p.tap('.sidebar-close');
await p.waitForTimeout(300);

// метрики: подсказка «i» по тапу, шторкой снизу
await p.tap('#metricsLink');
await p.waitForTimeout(400);
check(await noSideScroll(), 'сводный отчёт без горизонтальной прокрутки');
const info = '.metrics-section >> nth=0 >> .info';
await p.tap(info);
await p.waitForTimeout(250);
const tip = p.locator('.metrics-section >> nth=0 >> .info-tip');
check(await tip.isVisible(), 'тап по «i» открывает подсказку');
const tipBox = await tip.boundingBox();
check(tipBox.x >= 0 && tipBox.x + tipBox.width <= 393 && tipBox.y + tipBox.height <= 852,
      'подсказка — шторкой в пределах экрана');
await p.tap(info);
await p.waitForTimeout(250);
check(await tip.isHidden(), 'повторный тап закрывает подсказку');
await longPress('.outlier-row');
check(await p.isVisible('#cpop') && /INIT-\d+/.test(await p.textContent('#cpopTarget')),
      'долгое нажатие на задачу-выброс — заметка к ней');
await p.tap('#cpopCancel');
check(await p.isHidden('#cpop'), 'кнопка «Отмена» закрывает поле: Esc на телефоне нет');
await p.tap('.sidebar-close');
await p.waitForTimeout(300);

// корзина: карандаш и мусорка видны без наведения
await p.tap('#notesToggle');
const acts = await p.locator('.nrow .nacts').first().evaluate(el => getComputedStyle(el).opacity);
check(acts === '1', 'карандаш и мусорка видны без наведения');
const fontSize = await p.locator('#nText').evaluate(el => parseFloat(getComputedStyle(el).fontSize));
check(fontSize >= 16, 'поле ввода 16px — iOS не увеличивает страницу при фокусе');
check(await noSideScroll(), 'корзина без горизонтальной прокрутки');

// презентация на телефоне: в портрете слайды лентой, без горизонтальной прокрутки
await p.tap('#notesToggle');
await p.tap('#presBtn');
await p.waitForTimeout(300);
const feed = await p.evaluate(() => {
  const st = document.getElementById('deckStage');
  return { feed: document.getElementById('deck').classList.contains('feed'), noSide: st.scrollWidth <= st.clientWidth,
           visible: [...st.querySelectorAll('.slide')].every(s => getComputedStyle(s).display !== 'none') };
});
check(feed.feed && feed.visible, 'презентация в портрете — все слайды лентой');
check(feed.noSide, 'лента слайдов без горизонтальной прокрутки');
await p.tap('#deckClose');
check(await p.isHidden('#deck'), 'крестик закрывает презентацию');

check(!errors.length, 'ошибок JavaScript нет' + (errors.length ? ': ' + errors.join('; ') : ''));
await browser.close();
if (failures.length) { console.log(`\nупало: ${failures.length}`); process.exit(1); }
console.log('\nвсе проверки прошли');
