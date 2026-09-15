/**
 * Раздел «Управление спринтами», браузерная половина.
 *
 * Поверхность одна — карточка в «Настройки → Плагины» (`settings.plugin.item`)
 * под тем же ключом, что пространство настроек узла (`sprint-management`):
 * вкладка сводит две ведомости — что обслуживает узел и какие карточки есть в
 * браузере — именно по нему.
 *
 * Своей кнопки в сайдбаре у раздела нет намеренно: рабочая поверхность
 * коннектора — чат, где модель зовёт инструменты. Карточка нужна только для
 * доступов и проверки подключения.
 */
// Type-only: дают декларации служб и слияние SlotMap.
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-settings-plugins/client'
import type { Context as ClientContext } from '@deepseek-ai/cordis'
import type { RpcResult } from '../channel.js'
import { SPRINT_NAMESPACE, type SprintSettings } from '../settings.js'
import { SprintCardController } from './sprint-card.js'
import { SprintSettingsCard, type SprintCardInjected } from './SprintSettingsCard.js'
import { ru, type SprintLocaleKey } from './locales.js'
import { styleText } from './styles.js'

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap { 'sprint.management': SprintLocaleKey }
}

const NS = 'sprint.management'

/**
 * Имя канала RPC узла (`src/channel.ts`, `SPRINT_CHANNEL`). Продублировано
 * строкой, а не импортировано значением: `channel.ts` — общий модуль с узловой
 * половиной, и его код браузеру не нужен.
 */
const CHANNEL = '/sprint'

/**
 * Слоты дают место регистрации, локаль — копию, соединение — канал проверки.
 * Служба настроек берётся отложенной инъекцией: без неё карточки просто нет,
 * и это честнее, чем полоса, которой нельзя пользоваться.
 */
export const inject = ['slots', 'connection', 'locale']

export function apply(ctx: ClientContext): void {
  ctx.effect(() => ctx.locale.register(NS, { zh: ru, en: ru }), 'dsh-plugin-sprint: словарь копии (ru)')

  ctx.effect(() => {
    const style = document.createElement('style')
    style.setAttribute('data-plugin', 'dsh-plugin-sprint')
    style.textContent = styleText
    document.head.appendChild(style)
    return () => { style.remove() }
  }, 'dsh-plugin-sprint: стили карточки')

  const connection = ctx.get('connection') as unknown as {
    rpc: {
      call(channel: string, endpoint: string, payload: unknown, signal?: AbortSignal): Promise<RpcResult<unknown>>
    }
  }
  const call = (endpoint: string, payload: unknown = {}): Promise<RpcResult<unknown>> =>
    connection.rpc.call(CHANNEL, endpoint, payload)

  ctx.inject(['settingsScope'], (scoped: ClientContext) => {
    const scope = scoped.settingsScope.bind<SprintSettings>({ namespace: SPRINT_NAMESPACE })
    const card = new SprintCardController(scope)
    scoped.slots.inject('settings.plugin.item', () => scoped.slots.register(
      {
        name: 'settings.plugin.item',
        key: SPRINT_NAMESPACE,
        locale: NS,
        inject: (): SprintCardInjected => ({ ...card.inject(), call }),
      },
      SprintSettingsCard,
    ))
  })
}
