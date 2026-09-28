# Acceptance — actual-sprint: детерминированные сборщики (issue #4)

Прогон на фикстурах, без сети и без корпоративных данных. Воспроизвести:

```bash
python3 -m unittest discover tests
```

## Критерии приёмки

| # | Критерий | Чем закрыт | ☑ |
|---|---|---|---|
| 1 | Две команды: одна на `base` с `params`, вторая на своём сборщике. Один HTML с двумя вкладками, визуал как был | `test_runner.RunnerTest.test_two_teams_one_page`, `test_summary_names_every_team`; ручной прогон в headless Chromium: вкладки «Команда A»/«Команда B», таблица эпиков, панель эпика, 0 ошибок в консоли | ☑ |
| 2 | `base` без `params` на replay-фикстуре даёт тот же JSON, что прежний `collect.py`, кроме `_meta` и `statusMap` | `test_base_collector.LegacyParityTest` против золотого файла `fixtures/legacy_collect_team.json` (снят с `collect.py` до удаления) | ☑ |
| 3 | Изменение одного байта в своём сборщике: при `strict: true` runner отказывается и называет команду | `test_runner.test_changed_collector_refused_and_named` | ☑ |
| 4 | Удаление обязательного поля: validate называет команду и путь, HTML не пишется, прошлый файл цел | `test_runner.test_missing_field_stops_build_and_keeps_previous_page` | ☑ |
| 5 | Недоступная JIRA (код 3): сообщение про VPN/токен, без обходных путей | `test_runner.test_jira_unavailable_is_code_3`; в `SKILL.md` и `/actual-sprint` сбор данных моделью запрещён явно | ☑ |
| 6 | `tests/` проходят без сети на replay-фикстурах | 75 тестов, единственный сетевой путь закрыт `--replay` (`test_replay_never_touches_network`) | ☑ |
| 7 | Grep по выходным файлам на значение токена — 0 совпадений | `test_runner.test_token_never_reaches_output` (обходит все файлы проекта), `test_base_collector.TokenSafetyTest` (stdout, stderr, record-дампы) | ☑ |
| 8 | В кодовой базе нет отключения проверки TLS | `test_hygiene.TlsTest` по всем `.py/.js/.mjs/.go/.sh/.html` репозитория | ☑ |
| 9 | В `SKILL.md` нет инструкций ручного сбора | `test_hygiene.SkillTest.test_no_manual_collection_instructions` (`curl`, `jql`, `rest/api`, `customfield`) | ☑ |
| 10 | Новый статус в workflow даёт предупреждение, а не молча уезжает в «В работе» | `test_base_collector.StatusMapTest.test_workflow_drift_warning`; гасится строкой в `params.status_buckets` (`test_declaring_status_silences_drift`) | ☑ |

## Нефункциональные

| НФТ | Проверка | ☑ |
|---|---|---|
| НФТ-1 Детерминизм | `test_byte_identical_between_runs` — на replay stdout совпадает побайтово (длительность там не измеряется, иначе байты расходились бы), `test_now_comes_from_request_only` | ☑ |
| НФТ-2 Токен | см. критерий 7 | ☑ |
| НФТ-3 TLS | см. критерий 8; `ssl.create_default_context(cafile=…)` в базовом сборщике | ☑ |
| НФТ-4 Только чтение | у клиента сборщика есть единственный метод `api()` — GET; записи в JIRA нет ни в одном режиме | ☑ |
| НФТ-5 Независимость от языка | runner общается со сборщиком только по протоколу (stdin/stdout/коды выхода); свой сборщик в тестах — отдельный процесс | ☑ |
| НФТ-6 Нагрузка | пакетные запросы, 11 запросов на три спринта команды; число в `_meta.requests` | ☑ |
| НФТ-7 Обратная совместимость | `test_contract.SchemaTest.test_example_passes` — прежний `example_team.json` проходит схему после добавления `_meta`, без `statusMap` | ☑ |
| НФТ-8 Обезличивание | фикстуры синтетические (`tests/fake_jira.py`): `INIT-*`, «Участник А…», `jira.demo-workspace.local` | ☑ |
| НФТ-9 Понятные ошибки | `test_config_errors_name_team_and_field`, сообщения называют команду, этап и следующий шаг | ☑ |

## Что поправил двухосевой ревью (Standards + Spec)

- **Категории «выполнено» и «в работе» были строками в коде** `lead_cycle`/`in_progress_since` — четвёртая копия правила, до которой не доходил `params`. На англоязычном инстансе это дало бы нули во всех метриках при зелёных инвариантах. Теперь категории берутся из `contract/status_rules.json` и переопределяются `params.done_categories` / `params.progress_categories`. Регрессия: `test_contract.LocalisedWorkflowTest`.
- **Детектор дрейфа ругался на статус, который свой сборщик осознанно разложил** в своей `statusMap`. По ФТ-12.12 «покрыт картой» — это и есть карта команды; у базового сборщика карта выведена из тех же правил плагина, поэтому там проверка осталась. `test_contract.DriftDetectorTest`.
- **`validate --lock` обходил гейт PO** (ФТ-14) — флаг убран, хеш пишет только отдельная команда `lock`.
- Снята проверка порядка `logs.authors`: спек её не требует, а лишняя строгость валит корректный сборщик.
- Мелочи: `_schema_path()` (middle man), неиспользуемый аргумент `collector_env(cfg)`, no-op копия словаря в инварианте 11, `cats` переехал в состояние сборщика, `extra` → `with_comments`.

## Отклонения от исходного среза

- **Шаблоны сборщиков — только Python** (решение по О6 при согласовании). Протокол языконезависим, шаблоны на Node и Go — следующий шаг. Поэтому «второй сборщик не на Python» из критерия 1 закрыт вторым **процессом** со своим кодом и своим `statusMap`, но на Python.
- **Конфиг — TOML** (решение по О1): `tomllib` из stdlib, ноль зависимостей; примеры в issue были на YAML.
- **Срок жизни проверки — только хеш** (решение по О4). Дрейф workflow ловит предупреждение ФТ-12.12.
- О2, О3, О5 — как рекомендовано в issue: отдельный lock-файл, при падении любой команды HTML не пишется, сборщики живут в проекте пользователя.
