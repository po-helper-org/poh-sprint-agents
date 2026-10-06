#!/usr/bin/env bash
# poh-sprint-agents installer — копирует навыки sprint-planner + actual-sprint + sprint-status + sprint-insights в target-проект (Claude Code).
# Non-destructive: существующие файлы не перезаписываются. domain-profile.md не трогается.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$PWD}"
copy() { # src rel-path
  local dest="$TARGET/$1"
  if [ -e "$dest" ]; then echo "skip (exists): $1"; return; fi
  mkdir -p "$(dirname "$dest")"; cp -R "$SCRIPT_DIR/$1" "$dest"; echo "add: $1"
}
copy ".claude/skills/sprint-planner"
for c in sm-sync sm-goal sm-decompose sm-load sm-deliver sm-consensus; do
  copy ".claude/commands/$c.md"
done
copy ".claude/skills/actual-sprint"
for c in actual-sprint sprint-setup collector-new collector-validate; do
  copy ".claude/commands/$c.md"
done
# статус спринта в чат — читает снимок actual-sprint, отдельно не настраивается
copy ".claude/skills/sprint-status"
copy ".claude/commands/sprint-status.md"
# инсайды ИИ по графикам — отдельный конвейер поверх того же снимка
copy ".claude/skills/sprint-insights"
copy ".claude/commands/sprint-insights.md"
# образец конфига отчёта: рабочий конфиг пишет /sprint-setup, здесь только пример
if [ ! -e "$TARGET/sprint-report.config.toml" ] && [ ! -e "$TARGET/sprint-report.config.toml.example" ]; then
  cp "$SCRIPT_DIR/.claude/skills/actual-sprint/examples/sprint-report.config.toml" \
     "$TARGET/sprint-report.config.toml.example"
  echo "add: sprint-report.config.toml.example (заполнить через /sprint-setup)"
fi
# профиль — только если отсутствует
if [ ! -e "$TARGET/.claude/domain-profile.md" ]; then
  mkdir -p "$TARGET/.claude"; cp "$SCRIPT_DIR/domain-profile.template.md" "$TARGET/.claude/domain-profile.md"
  echo "add: .claude/domain-profile.md (из шаблона — заполнить)"
fi
echo "=== SPRINT-PLANNER-INSTALL: done → $TARGET ==="
