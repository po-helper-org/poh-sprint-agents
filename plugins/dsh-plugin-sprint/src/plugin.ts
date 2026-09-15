/**
 * Раздел «Управление спринтами», узловая половина.
 *
 * Четыре службы, и каждая берётся ОТЛОЖЕННОЙ инъекцией: композиция без
 * веб-интерфейса, без службы настроек или без реестра инструментов обязана
 * подниматься — раздел тогда просто отдаёт меньше, а не роняет харнесс.
 *
 * - `settings` — пространство настроек раздела (карточка в «Настройки → Плагины»);
 * - `tools` — три инструмента модели: это и есть коннектор для чата;
 * - `systemPrompt` — секция «когда ходить в JIRA» с промтом подключения;
 * - `connection` — канал `/sprint` для кнопки «Протестировать».
 *
 * Настройки нигде не копируются в поля: и инструменты, и канал читают снимок
 * документа на каждый вызов, поэтому правка в карточке действует сразу, без
 * перезапуска харнесса.
 */
import type { Context } from '@deepseek-ai/cordis'
// Type-only: дают декларации служб `settings`, `tools`, `systemPrompt` на контексте.
import type {} from '@deepseek-ai/dsh-settings'
import type {} from '@deepseek-ai/dsh-system-prompt'
import type {} from '@deepseek-ai/dsh-tools'
import { SPRINT_CHANNEL, dispatch, type RpcResult } from './channel.js'
import { SprintConnector } from './connector.js'
import { Config, type PluginConfig } from './plugin-config.js'
import { fetchPort } from './ports.js'
import { DEFAULT_PROMPT_ORDER, PROMPT_SECTION, jiraPromptText } from './prompt.js'
import { SprintSettingsSchema } from './settings-schema.js'
import {
  SPRINT_NAMESPACE, problemOf, resolveSprintSettings, type SprintSettings,
} from './settings.js'
import { sprintTools } from './tools.js'

export const name = 'dsh-plugin-sprint'
export { Config }

/** Форма службы соединения, которой нам достаточно. */
interface ConnectionLike {
  rpc: {
    handle: (
      channel: string,
      handler: (endpoint: string, payload: unknown, signal: AbortSignal) => Promise<RpcResult<unknown>>,
      options?: { authority?: string },
    ) => () => Promise<void> | void
  }
}

/** Область настроек раздела, пока служба настроек жива. */
type Scope = { get(): SprintSettings } | null

export function apply(ctx: Context, config: PluginConfig): void {
  let scope: Scope = null
  const settings = (): SprintSettings => resolveSprintSettings(scope?.get())

  const connector = new SprintConnector({
    settings,
    env: process.env,
    http: fetchPort,
    timeoutMs: config.timeoutMs,
    maxIssues: config.maxIssues,
  })

  // ——— Настройки раздела ———
  // Без службы настроек карточки в «Настройки → Плагины» не будет, и это видно:
  // вкладка показывает только обслуживаемые узлом пространства.
  ctx.inject(['settings'], (scoped: Context) => {
    const registered = scoped.settings.register(SPRINT_NAMESPACE, SprintSettingsSchema, {
      // Та же проверка, что гасит «Сохранить» в карточке: негодный адрес или ключ
      // проекта обязан отказывать при записи, а не оставлять коннектор молча
      // нерабочим до первого вопроса модели.
      validate: (value: SprintSettings) => {
        const problem = problemOf(resolveSprintSettings(value))
        if (problem !== null) throw new Error(problem)
      },
    })
    scoped.effect(() => {
      scope = registered
      return () => { scope = null }
    }, 'dsh-plugin-sprint: пространство настроек раздела')
  })

  // ——— Инструменты модели ———
  ctx.inject(['tools'], (scoped: Context) => {
    scoped.effect(() => {
      const disposers = sprintTools(connector, { timeoutMs: config.toolTimeoutMs })
        .map((tool) => scoped.tools.register(tool))
      return () => { for (const dispose of disposers) dispose() }
    }, 'dsh-plugin-sprint: инструменты JIRA')
  })

  // ——— Секция системного промта ———
  // Текст — провайдер, а не строка: он пересчитывается на каждую сборку промта,
  // поэтому правка промта подключения в карточке действует со следующего запроса.
  ctx.inject(['systemPrompt'], (scoped: Context) => {
    scoped.effect(() => scoped.systemPrompt.section({
      name: PROMPT_SECTION,
      order: config.promptOrder ?? DEFAULT_PROMPT_ORDER,
      text: () => jiraPromptText(settings(), process.env),
    }), 'dsh-plugin-sprint: секция промта про JIRA')
  })

  // ——— Канал карточки настроек ———
  ctx.inject(['connection'], (scoped: Context) => {
    const connection = scoped.get('connection') as unknown as ConnectionLike
    scoped.effect(
      () => connection.rpc.handle(
        SPRINT_CHANNEL,
        (endpoint, payload, signal) => dispatch(connector, endpoint, payload, signal),
        { authority: 'loopback' },
      ),
      'dsh-plugin-sprint: канал /sprint',
    )
  })
}
