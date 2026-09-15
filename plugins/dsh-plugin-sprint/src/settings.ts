/**
 * Пространство настроек раздела «Управление спринтами» — одно на раздел
 * (`sprint-management`), одна карточка в «Настройки → Плагины».
 *
 * Внутри — коннекторы источников данных спринта. Сейчас коннектор один (JIRA),
 * поэтому он лежит отдельным полем `jira`, а не элементом списка: список из
 * одного элемента усложняет и схему, и карточку, ничего не давая. Второй
 * коннектор добавляется соседним полем и своей иконкой в карточке.
 *
 * Токен хранится обычной строкой документа настроек, как и у соседнего раздела
 * «Управление коммуникацией»: харнесс локальный, документ лежит на машине
 * владельца, а `role('secret')` вырезает поле из ответа узла браузеру — карточка
 * перестала бы отличать «токен не задан» от «токен спрятан» и предлагала бы
 * проверку подключения без токена. Кому нужен токен вне документа — задаёт
 * `JIRA_TOKEN` в окружении процесса харнесса: поле настроек пусто, коннектор
 * берёт токен оттуда (см. `resolveToken`).
 *
 * Схема пространства вынесена в `settings-schema.ts`: она нужна только узлу, а
 * браузерная половина не должна тащить schemastery в бандл карточки.
 */
/** Идентификатор пространства настроек. Им же карточка ключуется в слоте. */
export const SPRINT_NAMESPACE = 'sprint-management'

/** Настройки коннектора к корпоративной JIRA. */
export interface JiraSettings {
  /** Адрес корпоративной JIRA: `https://jira.example.com` (допустим и контекстный путь). */
  baseUrl: string
  /** Персональный токен доступа. Пусто — берётся `JIRA_TOKEN` из окружения узла. */
  token: string
  /** Учётная запись для Jira Cloud (Basic). Пусто — Bearer, как на Server/DC. */
  email: string
  /** Ключ проекта команды: `SPRINT`. Из него строится запрос историй. */
  projectKey: string
  /** Свой JQL историй вместо построенного из `projectKey`. Пусто — построенный. */
  storiesJql: string
  /** Промт подключения: что модель должна знать про этот контур JIRA. */
  prompt: string
  /** Поле оценки в SP. Пусто — коннектор находит его сам по каталогу полей. */
  storyPointsField: string
}

/** Документ настроек раздела. */
export interface SprintSettings {
  jira: JiraSettings
}

/** Значения по умолчанию — они же форма, к которой приводится снимок документа. */
export const DEFAULT_JIRA: JiraSettings = {
  baseUrl: '',
  token: '',
  email: '',
  projectKey: '',
  storiesJql: '',
  prompt: '',
  storyPointsField: '',
}

/** Строка из произвольного значения: чего нет — умолчание. */
function text(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback
}

/**
 * Снимок документа в нашу форму. Одна функция на обе половины: узел читает ею
 * настройки перед походом в JIRA, браузер — перед отрисовкой карточки, и
 * разъехаться они не могут.
 */
export function resolveSprintSettings(section: unknown): SprintSettings {
  const raw = (typeof section === 'object' && section !== null ? section : {}) as { jira?: unknown }
  const jira = (typeof raw.jira === 'object' && raw.jira !== null ? raw.jira : {}) as Partial<JiraSettings>
  return {
    jira: {
      baseUrl: text(jira.baseUrl, DEFAULT_JIRA.baseUrl),
      token: text(jira.token, DEFAULT_JIRA.token),
      email: text(jira.email, DEFAULT_JIRA.email),
      projectKey: text(jira.projectKey, DEFAULT_JIRA.projectKey),
      storiesJql: text(jira.storiesJql, DEFAULT_JIRA.storiesJql),
      prompt: text(jira.prompt, DEFAULT_JIRA.prompt),
      storyPointsField: text(jira.storyPointsField, DEFAULT_JIRA.storyPointsField),
    },
  }
}

/**
 * Разбор адреса JIRA. Возвращает адрес без хвостовой косой черты либо причину
 * отказа — ту же, что увидит человек в карточке.
 */
export function normalizeBaseUrl(raw: string): { url: string } | { problem: string } {
  const trimmed = raw.trim()
  if (trimmed === '') return { problem: 'не задан адрес JIRA' }
  let parsed: URL
  try {
    parsed = new URL(trimmed)
  } catch {
    return { problem: `адрес JIRA не разбирается: ${trimmed} — нужен вид https://jira.example.com` }
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    return { problem: `адрес JIRA должен начинаться с https:// или http://, а не с ${parsed.protocol}//` }
  }
  return { url: `${parsed.origin}${parsed.pathname.replace(/\/+$/, '')}` }
}

/**
 * Проверка настроек перед записью. Та же, что на узле при сохранении, — чтобы
 * кнопка «Сохранить» гасла раньше отказа, а не после него.
 * @returns причину, по которой настройки негодны, либо `null`.
 */
export function problemOf(settings: SprintSettings): string | null {
  const { jira } = settings
  const filled = jira.baseUrl.trim() !== '' || jira.token.trim() !== ''
  if (!filled) return null // пустой коннектор — это «не настроен», а не ошибка
  const base = normalizeBaseUrl(jira.baseUrl)
  if ('problem' in base) return base.problem
  const key = jira.projectKey.trim()
  if (key !== '' && !/^[A-Za-z][A-Za-z0-9_]*$/.test(key)) {
    return `ключ проекта «${key}» не похож на ключ JIRA — буквы, цифры и подчёркивание, начиная с буквы`
  }
  return null
}

/** Токен, которым ходить в JIRA: поле настроек, иначе окружение узла. */
export function resolveToken(settings: JiraSettings, env: Record<string, string | undefined>): string {
  const own = settings.token.trim()
  if (own !== '') return own
  return env.JIRA_TOKEN?.trim() ?? ''
}

/** Настроен ли коннектор настолько, чтобы идти в JIRA. */
export function isConfigured(settings: JiraSettings, env: Record<string, string | undefined>): boolean {
  return 'url' in normalizeBaseUrl(settings.baseUrl) && resolveToken(settings, env) !== ''
}
