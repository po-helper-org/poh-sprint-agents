#!/usr/bin/env bash
# Навык sprint-blockers для PO-агента Hermes: рабочий каталог отчёта + навык в профиле.
#
#   bash install.sh <профиль> <slug> <имя команды> <рабочий каталог> [каталог навыков]
#
# Рабочий каталог — отдельный от репозитория: конфиг команды и отчёты живут там,
# навыки — ссылкой на .claude/skills репозитория (обновляются вместе с ним).
# Конфиг не перезаписывается: команду в нём настраивает человек (jql, mcp, skip).
# Идемпотентно: повторный запуск обновляет только навык в профиле.
set -euo pipefail
PROFILE="${1:?профиль Hermes}"; TEAM="${2:?slug команды}"; NAME="${3:?имя команды}"; WS="${4:?рабочий каталог}"
SKILLS="${5:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
DEST="$HERMES_HOME/profiles/$PROFILE/skills/sprint-blockers"
[ -d "$HERMES_HOME/profiles/$PROFILE" ] || { echo "нет профиля Hermes: $PROFILE" >&2; exit 1; }
[ -f "$SKILLS/sprint-blockers/blockers.py" ] || { echo "не найден навык в $SKILLS" >&2; exit 1; }

mkdir -p "$WS/.claude" "$WS/reports"
if [ ! -e "$WS/.claude/skills" ]; then ln -s "$SKILLS" "$WS/.claude/skills"; echo "add: $WS/.claude/skills → $SKILLS"; fi
if [ ! -e "$WS/sprint-report.config.toml" ]; then
  echo "нет $WS/sprint-report.config.toml — создайте с командой «$TEAM» и [teams.params.blockers] (SKILL.md, «Настройка команды»)" >&2
elif ! grep -q "slug *= *\"$TEAM\"" "$WS/sprint-report.config.toml"; then
  echo "в $WS/sprint-report.config.toml нет команды «$TEAM»" >&2
fi

mkdir -p "$DEST"
sed -e "s|{{TEAM}}|$TEAM|g" -e "s|{{TEAM_NAME}}|$NAME|g" -e "s|{{WORKSPACE}}|$WS|g" \
  "$(dirname "${BASH_SOURCE[0]}")/SKILL.md.tmpl" > "$DEST/SKILL.md.new"
mv "$DEST/SKILL.md.new" "$DEST/SKILL.md"
echo "навык → $DEST/SKILL.md (профиль $PROFILE, команда $TEAM)"
