/**
 * Карточка раздела в «Настройки → Плагины → Конфигурация плагинов»: полоса
 * коннекторов и поля выбранного. Сторона разметки.
 *
 * Собственная вёрстка, а не карточка харнесса: `PluginCard`/`ValueField` живут
 * внутри @deepseek-ai/dsh-client-ui-settings-plugins и значением не
 * экспортируются — слот на то и keyed, что карточку рисует сам плагин.
 * Геометрия и токены сняты с `PluginCard.module.css` (см. styles.ts): карточка
 * стоит в одном списке с соседними и обязана быть от них неотличимой.
 *
 * Полоса коннекторов с одной иконкой — не украшение: следующий источник данных
 * спринта встаёт рядом своей иконкой, а поля под полосой принадлежат выбранному.
 * Пока узел не отдаёт пространство `sprint-management`, карточка не рисует
 * ничего: полоса, которой нельзя пользоваться, хуже отсутствия полосы.
 */
// Type-only: даёт слияние SlotMap с записью 'settings.plugin.item'.
import type {} from '@deepseek-ai/dsh-client-ui-settings-plugins/client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { IconChevronDownOutline14 } from '@deepseek-ai/dsh-client-ui-primitives'
import type { InjectFace, PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type { RpcResult, TestReply } from '../channel.js'
import type { JiraField, SprintCardFace } from './sprint-card.js'
import type { SprintLocaleKey } from './locales.js'
import { classNames as css } from './styles.js'

export interface SprintCardInjected extends SprintCardFace {
  call: (endpoint: string, payload?: unknown) => Promise<RpcResult<unknown>>
}

export type SprintSettingsCardProps =
  PropsRuntime<'settings.plugin.item'> &
  PropsLocale<'sprint.management'> &
  InjectFace<SprintCardInjected>

type Translate = (key: SprintLocaleKey) => string

/** Состояние проверки подключения: одна строка под кнопками. */
interface TestState {
  tone: 'ok' | 'bad' | 'busy'
  text: string
  /** Подробности отчёта — JQL и сколько нашлось, либо предупреждение. */
  detail?: string
}

export function SprintSettingsCard(props: SprintSettingsCardProps) {
  // InjectFace кладёт грань прямо в props, а `hooks.sprintCard` становится `useSprintCard`.
  const face = props
  const t: Translate = props.t
  const { call } = props
  const state = props.useSprintCard((snapshot) => snapshot)
  const [open, setOpen] = useState(false)
  const [connector, setConnector] = useState<'jira' | null>(null)
  const [test, setTest] = useState<TestState | null>(null)
  const saveStarted = useRef(false)

  useEffect(() => {
    if (state.saving) { saveStarted.current = true; return }
    if (!saveStarted.current) return
    saveStarted.current = false
    if (!state.dirty && !state.failed) setOpen(false)
  }, [state.dirty, state.failed, state.saving])

  const runTest = useCallback(async () => {
    setTest({ tone: 'busy', text: t('testing') })
    const answer = await call('jira.test', { draft: face.draft() })
    if (answer.ok) {
      const reply = answer.value as TestReply
      setTest({
        tone: 'ok',
        text: reply.summary,
        ...(reply.report.stories === undefined ? {} : { detail: `JQL: ${reply.report.stories.jql}` }),
      })
      return
    }
    setTest({ tone: 'bad', text: `${t('testFailed')}: ${answer.error.message}` })
  }, [call, face, t])

  if (!state.available) return null
  const disabled = !state.writable
  const jira = state.values.jira
  const ready = jira.baseUrl.trim() !== '' && jira.token.trim() !== ''
  // Проверку включает один адрес: пустое поле токена — не обязательно «нет токена»,
  // он мог быть задан в окружении харнесса (JIRA_TOKEN). Пусть узел скажет, чего
  // не хватает, — это полезнее мёртвой кнопки.
  const canTest = jira.baseUrl.trim() !== ''

  const field = (
    name: JiraField,
    label: SprintLocaleKey,
    hint: SprintLocaleKey,
    kind: 'text' | 'password' | 'area' = 'text',
  ) => (
    <div className={css.field} key={name}>
      <label className={css.fieldLabel} htmlFor={`sprint-jira-${name}`}>
        {t(label)}<span className={css.fieldHint}>{t(hint)}</span>
      </label>
      {kind === 'area'
        ? (
          <textarea
            id={`sprint-jira-${name}`} value={jira[name]} disabled={disabled}
            onChange={(event) => { face.editJira(name, event.target.value) }}
          />
        )
        : (
          <input
            id={`sprint-jira-${name}`} value={jira[name]} disabled={disabled} autoComplete="off"
            type={kind === 'password' ? 'password' : 'text'}
            onChange={(event) => { face.editJira(name, event.target.value) }}
          />
        )}
    </div>
  )

  return (
    <li className={css.card} data-open={open || undefined}>
      <button
        type="button" className={css.cardHead} aria-expanded={open}
        aria-label={`${t(open ? 'collapse' : 'expand')}: ${t('cardTitle')}`}
        onClick={() => { setOpen(!open) }}
      >
        <span className={css.cardText}>
          <span className={css.cardName}>{t('cardTitle')}</span>
          <span className={css.cardDesc}>{t('cardDescription')}</span>
        </span>
        {state.dirty && <span className={css.cardPending}>{t('unsaved')}</span>}
        <IconChevronDownOutline14 className={css.cardChevron} />
      </button>
      {open && (
        <div className={css.cardBody}>
          {disabled && <p className={css.cardNote} role="status">{t('readOnly')}</p>}

          <p className={css.subhead}>{t('connectors')}</p>
          <div className={css.strip}>
            <button
              type="button" className={css.chip} data-active={connector === 'jira' || undefined}
              aria-pressed={connector === 'jira'} aria-label={t('jiraPick')} title={t('jiraPick')}
              onClick={() => { setConnector(connector === 'jira' ? null : 'jira') }}
            >
              <IconJira />
              <span className={css.chipName}>{t('jira')}</span>
              <span className={css.chipState} data-ready={ready || undefined}>
                {t(ready ? 'stateReady' : 'stateEmpty')}
              </span>
            </button>
          </div>

          {connector === 'jira' && (
            <>
              <div className={css.fields}>
                {field('baseUrl', 'baseUrl', 'baseUrlHint')}
                {field('token', 'token', 'tokenHint', 'password')}
                {field('prompt', 'prompt', 'promptHint', 'area')}
              </div>
              <p className={css.subhead}>{t('optional')}</p>
              <div className={css.fields}>
                {field('projectKey', 'projectKey', 'projectKeyHint')}
                {field('storiesJql', 'storiesJql', 'storiesJqlHint', 'area')}
                {field('email', 'email', 'emailHint')}
                {field('storyPointsField', 'storyPointsField', 'storyPointsFieldHint')}
              </div>
              <p className={css.cardNote}>{t('testHint')}</p>
              <p className={css.cardNote}>{t('tools')}</p>

              <div className={css.cardFoot}>
                {state.failed && <p className={css.cardFailed} role="status">{t('saveFailed')}</p>}
                {state.invalid !== null && <p className={css.cardFailed} role="status">{state.invalid}</p>}
                <button
                  type="button" className={css.btn} style={{ marginRight: 'auto' }}
                  disabled={test?.tone === 'busy' || !canTest}
                  onClick={() => { void runTest() }}
                >{t('test')}</button>
                <button
                  type="button" className={css.btn}
                  disabled={!state.dirty || state.saving} onClick={face.discard}
                >{t('discard')}</button>
                <button
                  type="button" className={`${css.btn} ${css.btnPrimary}`}
                  disabled={!state.dirty || state.invalid !== null || state.saving || disabled}
                  onClick={face.save}
                >{t(state.saving ? 'saving' : 'save')}</button>
                {test !== null && (
                  <div
                    className={css.status} role="status"
                    data-ok={test.tone === 'ok' || undefined} data-bad={test.tone === 'bad' || undefined}
                  >{test.text}</div>
                )}
              </div>
              {test?.detail !== undefined && <pre className={css.report}>{test.detail}</pre>}
            </>
          )}
        </div>
      )}
    </li>
  )
}

/**
 * Значок коннектора в наборе харнесса: контур 1.3px, `currentColor`, viewBox 16 —
 * как у соседних иконок. Две вложенные ромбовидные грани читаются как трекер
 * задач; фирменный знак Atlassian не воспроизводится намеренно.
 */
function IconJira({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <path d="M8 1.6 13.2 6.8 8 12 2.8 6.8 8 1.6Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M8 5.4 10.6 8 8 10.6 5.4 8 8 5.4Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M4.6 10.6 8 14l3.4-3.4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
