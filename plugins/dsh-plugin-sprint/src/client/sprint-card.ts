/**
 * Карточка раздела на вкладке «Плагины»: сторона состояния.
 *
 * Правки копятся черновиком и уезжают в документ настроек ОДНОЙ операцией по
 * «Сохранить», а не на каждую клавишу: документ общий, каждая запись — поход на
 * узел с проверкой ревизии. Своей копии значений нет: источник — снимок
 * `SettingsScope`, черновик лежит поверх него, поэтому правка из другой
 * поверхности видна сразу, а несохранённое не пропадает.
 *
 * Черновик отдаётся наружу целиком (`draft()`): кнопка «Протестировать» шлёт на
 * узел именно введённое, а не записанное, — иначе человек обязан сохранить
 * непроверенный токен, чтобы его проверить.
 */
import { createSnapshotStore, type SnapshotStore } from '@deepseek-ai/dsh-client-store'
import type { SettingsScope } from '@deepseek-ai/dsh-client-ui-settings/client'
import { problemOf, resolveSprintSettings, type JiraSettings, type SprintSettings } from '../settings.js'

/** Поля коннектора JIRA в порядке карточки. */
export const JIRA_FIELDS = [
  'baseUrl', 'token', 'prompt', 'projectKey', 'storiesJql', 'email', 'storyPointsField',
] as const
export type JiraField = (typeof JIRA_FIELDS)[number]

/** Поля, которые карточка отдаёт узлу как черновик проверки. */
export const DRAFT_FIELDS = ['baseUrl', 'token', 'email', 'projectKey', 'storiesJql', 'storyPointsField'] as const

export interface SprintCardState {
  /** Узел обслуживает пространство настроек раздела. */
  available: boolean
  writable: boolean
  dirty: boolean
  /** Настройки негодны — сохранение заблокировано; текст причины. */
  invalid: string | null
  saving: boolean
  failed: boolean
  values: SprintSettings
}

export interface SprintCardFace {
  hooks: { sprintCard: SnapshotStore<SprintCardState> }
  editJira: (field: JiraField, value: string) => void
  /** Текущие значения коннектора для проверки подключения (включая несохранённые). */
  draft: () => Partial<Record<(typeof DRAFT_FIELDS)[number], string>>
  discard: () => void
  save: () => void
}

type SettingsOp = { op: 'set'; path: string[]; value: string }

export class SprintCardController {
  private readonly store: SnapshotStore<SprintCardState>
  /** Черновик целиком; `null` — ничего не трогали. */
  private edited: SprintSettings | null = null
  private saving = false
  private failed = false
  private published: string

  constructor(private readonly scope: SettingsScope<SprintSettings>) {
    const initial = this.projection()
    this.published = JSON.stringify(initial)
    this.store = createSnapshotStore<SprintCardState>(initial)
    scope.subscribe(() => { this.publish() })
  }

  inject(): SprintCardFace {
    return {
      hooks: { sprintCard: this.store },
      editJira: (field, value) => { this.mutate((draft) => { draft.jira[field] = value }) },
      draft: () => {
        const jira = this.current().jira
        const draft: Partial<Record<(typeof DRAFT_FIELDS)[number], string>> = {}
        for (const field of DRAFT_FIELDS) draft[field] = jira[field].trim()
        return draft
      },
      discard: () => { this.edited = null; this.failed = false; this.publish() },
      save: () => { this.save() },
    }
  }

  private stored(): SprintSettings {
    return resolveSprintSettings(this.scope.getSnapshot().value)
  }

  private current(): SprintSettings {
    return this.edited ?? this.stored()
  }

  private mutate(change: (draft: SprintSettings) => void): void {
    this.edited ??= structuredClone(this.stored())
    change(this.edited)
    this.failed = false
    this.publish()
  }

  private publish(): void {
    const next = this.projection()
    const serialized = JSON.stringify(next)
    if (serialized === this.published) return
    this.published = serialized
    this.store.set(next)
  }

  private projection(): SprintCardState {
    const snapshot = this.scope.getSnapshot()
    const values = this.current()
    return {
      available: snapshot.status === 'ready',
      writable: snapshot.writable,
      dirty: this.edited !== null && JSON.stringify(this.edited) !== JSON.stringify(this.stored()),
      invalid: problemOf(values),
      saving: this.saving,
      failed: this.failed,
      values,
    }
  }

  private save(): void {
    if (this.saving || this.edited === null) return
    const stored = this.stored()
    const draft = this.edited
    const next: JiraSettings = { ...draft.jira }
    // Пробелы по краям адреса и токена — самая частая причина «не подключились»;
    // промт правится многострочно, и его края тоже незачем хранить.
    for (const field of JIRA_FIELDS) next[field] = next[field].trim()

    const ops: SettingsOp[] = []
    for (const field of JIRA_FIELDS) {
      if (next[field] !== stored.jira[field]) ops.push({ op: 'set', path: ['jira', field], value: next[field] })
    }
    if (ops.length === 0) { this.edited = null; this.publish(); return }

    this.saving = true
    this.failed = false
    this.publish()
    void this.scope.mutate(ops).then(
      () => { this.settle({ jira: next }) },
      () => { this.saving = false; this.failed = true; this.publish() },
    )
  }

  /**
   * Отказ узла (устаревшая ревизия, отвергнутое значение) не приходит
   * исключением: скоуп гасит его и перечитывает документ. Поэтому судим по
   * результату — совпало ли то, что в документе, с тем, что писали. Не
   * совпало — черновик остаётся, и человеку есть что повторить.
   */
  private settle(expected: SprintSettings): void {
    this.saving = false
    const applied = JSON.stringify(this.stored()) === JSON.stringify(expected)
    this.failed = !applied
    if (applied) this.edited = null
    this.publish()
  }
}
