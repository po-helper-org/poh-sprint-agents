/**
 * Точка входа пакета. Харнесс грузит плагин по имени пакета, то есть через этот
 * модуль: без `apply` и `name` здесь композиция его просто не найдёт.
 */
export type { JiraSettings, SprintSettings } from './settings.js'
export {
  DEFAULT_JIRA, SPRINT_NAMESPACE, isConfigured, normalizeBaseUrl,
  problemOf, resolveSprintSettings, resolveToken,
} from './settings.js'
export { SprintSettingsSchema } from './settings-schema.js'
export { JiraError, asJiraError, type JiraFailureKind } from './errors.js'
export { fetchPort, deadline, type HttpPort, type HttpRequest, type HttpResponse } from './ports.js'
export { JiraClient, authorizationOf, failureOf, type JiraTarget, type JiraClientOptions } from './jira/client.js'
export { buildStoriesJql, quoteJql, splitOrderBy, type StoriesQuery } from './jira/jql.js'
export type { JiraIdentity, JiraIssue, JiraSearchResult } from './jira/model.js'
export { LIST_FIELDS, descriptionOf, normalizeIssue, sprintNameOf, storyPointsOf } from './jira/normalize.js'
export { SprintConnector, type ConnectionReport, type ConnectorDeps, type JiraDraft } from './connector.js'
export { renderConnection, renderIssue, renderSearch } from './render.js'
export { DEFAULT_PROMPT_ORDER, PROMPT_SECTION, jiraPromptText } from './prompt.js'
export { SPRINT_CHANNEL, dispatch, draftOf, type RpcResult, type TestReply } from './channel.js'
export { sprintTools, type ToolOptions } from './tools.js'
export { Config, type PluginConfig } from './plugin-config.js'
export { name, apply } from './plugin.js'
