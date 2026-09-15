/**
 * Схема пространства настроек для службы настроек харнесса. Отдельным модулем,
 * потому что нужна только узлу: браузерная половина читает те же значения через
 * `resolveSprintSettings`, и тащить schemastery в бандл карточки незачем.
 */
import Schema from '@deepseek-ai/schemastery'
import { DEFAULT_JIRA, type SprintSettings } from './settings.js'

export const SprintSettingsSchema: Schema<SprintSettings> = Schema.object({
  jira: Schema.object({
    baseUrl: Schema.string().default(''),
    token: Schema.string().default(''),
    email: Schema.string().default(''),
    projectKey: Schema.string().default(''),
    storiesJql: Schema.string().default(''),
    prompt: Schema.string().default(''),
    storyPointsField: Schema.string().default(''),
  }).default({ ...DEFAULT_JIRA }),
}) as unknown as Schema<SprintSettings>
