#!/usr/bin/env bash
# Статус спринта в PDF по расписанию для Hermes Agent: cron в режиме --no-agent
# берёт stdout этого скрипта как есть, по метке MEDIA:<путь> прикладывает PDF
# и отправляет в чат. Модель в цепочке не участвует.
#
# Установка:
#   cp sprint-status.sh "$HERMES_HOME/scripts/" && chmod +x "$HERMES_HOME/scripts/sprint-status.sh"
#   hermes cron create "45 9 * * 1-5" --no-agent --script sprint-status.sh \
#     --name sprint-status --deliver telegram
#
# SPRINT_REPORT_PROJECT — каталог с sprint-report.config.toml (по умолчанию ниже).
# SPRINT_STATUS_CHROME  — путь к Chrome/Chromium, если он не найден сам.
# JIRA_URL и JIRA_PERSONAL_TOKEN берутся из окружения Hermes: в файлы их не пишем.
# Без VPN или токена скрипт не падает, а присылает PDF по последнему снимку с пометкой ⚠.
set -uo pipefail

PROJECT="${SPRINT_REPORT_PROJECT:-$HOME/sprint-report}"
if ! cd "$PROJECT" 2>/dev/null; then
  echo "Статус спринта не собран: нет каталога проекта $PROJECT (задайте SPRINT_REPORT_PROJECT)"
  exit 2
fi

# лог runner и печати уходит в stderr и в чат не попадает; в чат — подпись и MEDIA:
exec python3 .claude/skills/sprint-status/status.py --refresh "$@"
