---
description: "Свой сборщик под команду из шаблона — только если params базового не хватает. Runner в режиме run не запускает."
---
# /collector-new {slug} [--lang python]

Роль: автор сборщика (навык `.claude/skills/sprint-data/SKILL.md`). Перед кодом прочитай:
- `.claude/skills/actual-sprint/contract/PROTOCOL.md` — запуск, stdin/stdout, коды выхода;
- `.claude/skills/sprint-data/reference/fields.md` — каждое поле JSON: тип, откуда, на каком экране; форма — `contract/team.schema.json`;
- `.claude/skills/sprint-data/guides/jira.md` — сбор из JIRA по секциям (пример кода — базовый сборщик `templates/python/collector.py`), для другой системы — `guides/other-sources.md`.

**Сначала попробуй обойтись без кода.** Большинство различий между командами — это настройки, а не алгоритм. Спроси себя и человека: отличие правда в логике? Если различаются типы задач, имена статусов, поле эпика, глубина по спринтам или окна — это `params` базового сборщика, свой код не нужен:

```toml
[teams.params]
story_types = ["История", "Задача разработки"]
epic_link_field = "customfield_10101"
[teams.params.status_buckets]
"Ожидает релиза" = "review"
```

Своё нужно, когда меняется **алгоритм**: другой источник спринта, склейка нескольких досок, свои правила «что считать закрытым».

Тогда:

```bash
python3 .claude/skills/actual-sprint/runner/run.py new {slug} --lang python
```

Команда копирует шаблон в `collectors/{slug}/`. Дальше правишь точки `# TEAM RULE:` — в них живут правила команды. Держи контракт: вход из stdin, один JSON-объект в stdout, логи в stderr, коды выхода 0/1/2/3, время только из `now`, TLS включён, только GET. Секции, которые твой сборщик не отдаёт, выключают экраны: `run.py check <выход.json>` покажет какие — отдай всё, что есть в `reference/fields.md`, если источник это позволяет.

Эту команду заканчивай на `/collector-validate {slug}`. Сам `run.py run` здесь не запускай: непроверенный сборщик всё равно не пройдёт strict, а данные до сверки с JIRA доверия не заслуживают. **STOP.**
