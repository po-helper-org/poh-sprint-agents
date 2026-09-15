/**
 * Стили карточки — обычный текст CSS, инжектируемый одним `<style>` в
 * `document.head` (см. `apply()` в index.tsx), а не CSS-модуль: сборка
 * стороннего плагина не умеет `*.module.css`, а отдельный `lib/style.css` пакет
 * не публикует, и вёрстка тихо ломается.
 *
 * Хеширования имён без CSS-модуля нет — коллизии предотвращает префикс `sprint-`
 * на каждом селекторе через ту же карту, по которой строится разметка.
 *
 * Цвета — только токены харнесса `var(--dsw-alias-...)`: карточка стоит в одном
 * списке с карточками самого харнесса и обязана быть от них неотличимой.
 * Геометрия снята с `PluginCard.module.css` (через прецедент
 * dsh-communication-plugin, тот же харнесс, та же вкладка).
 */
export const classNames = {
  card: 'sprint-card',
  cardHead: 'sprint-card-head',
  cardText: 'sprint-card-text',
  cardName: 'sprint-card-name',
  cardDesc: 'sprint-card-desc',
  cardPending: 'sprint-card-pending',
  cardChevron: 'sprint-card-chevron',
  cardBody: 'sprint-card-body',
  cardFoot: 'sprint-card-foot',
  cardNote: 'sprint-card-note',
  cardFailed: 'sprint-card-failed',
  btn: 'sprint-btn',
  btnPrimary: 'sprint-btn-primary',

  strip: 'sprint-strip',
  chip: 'sprint-chip',
  chipName: 'sprint-chip-name',
  chipState: 'sprint-chip-state',

  fields: 'sprint-fields',
  field: 'sprint-field',
  fieldLabel: 'sprint-field-label',
  fieldHint: 'sprint-field-hint',
  status: 'sprint-status',
  subhead: 'sprint-subhead',
  report: 'sprint-report',
} as const

const c = classNames

export const styleText = `
/* ── Карточка вкладки «Плагины» (по PluginCard.module.css харнесса) ──────── */

.${c.card} { list-style: none; border: 1px solid var(--dsw-alias-border-l2); border-radius: 12px; background: var(--dsw-alias-bg-layer-3); font-size: 13px; }
.${c.card}:hover { border-color: var(--dsw-alias-label-dimmed); }
.${c.card}[data-open] { background: var(--dsw-alias-bg-layer-2); border-color: var(--dsw-alias-label-dimmed); }
.${c.cardHead} {
  width: 100%; border: 0; background: none; font: inherit; color: inherit; text-align: left; cursor: pointer;
  display: flex; align-items: center; gap: 12px; padding: 14px 16px; border-radius: 12px;
}
.${c.cardHead}:focus-visible { outline: 2px solid var(--dsw-alias-brand-primary); outline-offset: -2px; }
.${c.cardText} { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.${c.cardName} { font-size: 15px; font-weight: 600; line-height: 1.4; color: var(--dsw-alias-label-primary); }
.${c.cardDesc} { font-size: 13px; line-height: 1.5; color: var(--dsw-alias-label-tertiary); }
.${c.cardPending} { font-size: 12px; color: var(--dsw-static-amber-500); white-space: nowrap; }
.${c.cardChevron} { flex: none; color: var(--dsw-alias-label-tertiary); transition: transform .16s; }
.${c.card}[data-open] .${c.cardChevron} { transform: rotate(180deg); }
.${c.cardBody} { border-top: 1px solid var(--dsw-alias-border-l2); margin: 0 16px; padding-bottom: 8px; }
.${c.cardFoot} { display: flex; align-items: center; gap: 8px; justify-content: flex-end; padding: 12px 0 6px; flex-wrap: wrap; }
.${c.cardNote} { margin: 12px 0 0; font-size: 12px; color: var(--dsw-alias-label-caption); line-height: 1.5; }
.${c.cardFailed} { margin: 0; font-size: 12px; color: var(--dsw-static-red-500); flex-basis: 100%; }
.${c.btn} { border: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-layer-2); color: inherit; font: inherit; border-radius: 8px; padding: 6px 12px; cursor: pointer; }
.${c.btn}:hover { background: var(--dsw-alias-interactive-bg-hover); }
.${c.btn}:disabled { opacity: .45; cursor: default; }
.${c.btnPrimary} { background: var(--dsw-alias-brand-primary); color: var(--dsw-alias-label-primary-foreground); border-color: transparent; }

/* ── Полоса коннекторов: иконка на коннектор, вторая встанет рядом ───────── */

.${c.strip} { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 0 4px; }
.${c.chip} {
  display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px;
  border: 1px solid var(--dsw-alias-border-l2); border-radius: 10px;
  background: var(--dsw-alias-bg-layer-1); color: inherit; font: inherit; cursor: pointer;
}
.${c.chip}:hover { background: var(--dsw-alias-interactive-bg-hover); }
.${c.chip}[data-active] { border-color: var(--dsw-alias-brand-primary); }
.${c.chip}:focus-visible { outline: 2px solid var(--dsw-alias-brand-primary); outline-offset: 1px; }
.${c.chipName} { font-weight: 600; }
.${c.chipState} { font-size: 12px; color: var(--dsw-alias-label-caption); }
.${c.chipState}[data-ready] { color: var(--dsw-static-green-500); }

/* ── Поля коннектора ─────────────────────────────────────────────────────── */

.${c.fields} { display: flex; flex-direction: column; gap: 10px; padding: 12px 0 4px; }
.${c.field} { display: grid; grid-template-columns: 200px 1fr; gap: 12px; align-items: start; }
.${c.fieldLabel} { font-size: 13px; padding-top: 6px; }
.${c.fieldHint} { display: block; font-size: 12px; color: var(--dsw-alias-label-caption); margin-top: 2px; line-height: 1.4; }
.${c.card} input, .${c.card} textarea {
  font: inherit; color: inherit; background: var(--dsw-alias-bg-layer-1);
  border: 1px solid var(--dsw-alias-border-l2); border-radius: 7px; padding: 5px 8px; width: 100%; box-sizing: border-box;
}
.${c.card} textarea { resize: vertical; min-height: 72px; line-height: 1.45; }
.${c.card} input:focus, .${c.card} textarea:focus { outline: 2px solid var(--dsw-alias-brand-primary); outline-offset: -1px; }
.${c.status} { font-size: 12px; margin: 8px 0 0; flex-basis: 100%; text-align: left; }
.${c.status}[data-ok] { color: var(--dsw-static-green-500); }
.${c.status}[data-bad] { color: var(--dsw-static-red-500); }
.${c.subhead} { font-size: 13px; font-weight: 600; margin: 14px 0 0; }
.${c.report} {
  margin: 8px 0 0; padding: 8px 10px; max-height: 200px; overflow: auto; white-space: pre-wrap;
  font-family: var(--ds-font-family-code); font-size: 12px; line-height: 1.45;
  background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); border-radius: 8px;
}
`
