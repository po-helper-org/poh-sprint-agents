import z from '@deepseek-ai/schemastery'

/**
 * Конфигурация из строки профиля харнесса: только то, что не должен трогать
 * человек из браузера. Адрес, токен, проект и промт подключения живут в
 * настройках раздела (карточка «Настройки → Плагины»), а не здесь: строка
 * профиля лежит файлом рядом с репозиторием, и секретам там не место.
 */
export interface PluginConfig {
  /** Бюджет ожидания одного запроса к JIRA. */
  timeoutMs: number
  /** Бюджет одного вызова инструмента: поиск плюс разовый поход за каталогом полей. */
  toolTimeoutMs: number
  /** Потолок числа задач в одной выдаче. */
  maxIssues: number
  /** Порядок секции системного промта. */
  promptOrder: number
}

export const Config = z.object({
  timeoutMs: z.number().default(15_000),
  toolTimeoutMs: z.number().default(45_000),
  maxIssues: z.number().default(50),
  promptOrder: z.number().default(1200),
})
