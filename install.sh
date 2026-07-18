#!/usr/bin/env bash
# poh-sprint-agents installer — копирует навык sprint-planner в target-проект (Claude Code).
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
# профиль — только если отсутствует
if [ ! -e "$TARGET/.claude/domain-profile.md" ]; then
  mkdir -p "$TARGET/.claude"; cp "$SCRIPT_DIR/domain-profile.template.md" "$TARGET/.claude/domain-profile.md"
  echo "add: .claude/domain-profile.md (из шаблона — заполнить)"
fi
echo "=== SPRINT-PLANNER-INSTALL: done → $TARGET ==="
