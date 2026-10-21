#!/usr/bin/env bash
# Навык sprint-risk-notes и задача cron «комментарии к рискам спринта» в Hermes-профилях PO-агентов.
#
#   hermes/install-sprint-risk-notes.sh [--check | --remove | --replace] [профиль:команда:"cron" …]
#
# По умолчанию — po-gds:gds, po-live:live, po-mrs:mrs по будням в 09:40 / 09:45 / 09:50
# (после утреннего сбора спринта в 08:30 и рисков квартала по понедельникам; агенты идут по очереди —
# одновременная запись в sprint-risk-notes.json всё равно защищена замком business.py risk-put).
# Навык ставится копией (install -m 644) в ~/.hermes/profiles/<профиль>/skills/sprint-risk-notes/ с подставленными
# командой и путями; задача cron — `hermes -p <профиль> cron create` (уже есть — пропуск, --replace — пересоздать).
# Запись в Jira и сообщения людям навык не делает. Повторный запуск безопасен.
#
# Пути — переменными окружения:
#   AGENTS_DIR   клон poh-sprint-agents                 (по умолчанию ~/Projects/poh-sprint-agents)
#   REPORTS_DIR  reports снимка PO-Sprint-observe       (по умолчанию ~/Projects/poh-widget-sprint-observe/workspace/reports)
#   WIDGET_DIR   клон poh-widget-sprint-business       (по умолчанию ~/Projects/poh-widget-sprint-business)
#   PAGE_URL     адрес страницы для ответа агента       (по умолчанию /business/risks)
#   HERMES_HOME  каталог Hermes                         (по умолчанию ~/.hermes)
#   HERMES       команда hermes                         (по умолчанию hermes из PATH)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="${AGENTS_DIR:-$HOME/Projects/poh-sprint-agents}"
REPORTS_DIR="${REPORTS_DIR:-$HOME/Projects/poh-widget-sprint-observe/workspace/reports}"
WIDGET_DIR="${WIDGET_DIR:-$HOME/Projects/poh-widget-sprint-business}"
PAGE_URL="${PAGE_URL:-/sprints/}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES="${HERMES:-hermes}"
TEMPLATE="$HERE/sprint-risk-notes/SKILL.md"

MODE=install
case "${1:-}" in --check|--remove|--replace) MODE="${1#--}"; shift ;; esac
SPECS=("$@")
[ ${#SPECS[@]} -gt 0 ] || SPECS=("po-gds:gds:40 9 * * 1-5" "po-live:live:45 9 * * 1-5" "po-mrs:mrs:50 9 * * 1-5")

job_id() { # профиль имя → id задачи cron с этим именем (или пусто)
  python3 - "$HERMES_HOME/profiles/$1/cron/jobs.json" "$2" <<'PY'
import json, sys
try:
    doc = json.load(open(sys.argv[1], encoding='utf-8'))
except (OSError, ValueError):
    sys.exit(0)
jobs = doc.get('jobs', []) if isinstance(doc, dict) else doc
print(next((j.get('id') or '' for j in jobs if isinstance(j, dict) and j.get('name') == sys.argv[2]), ''))
PY
}

team_name() { # команда → имя из sprint-goals.json (или заглавными)
  python3 - "$REPORTS_DIR/sprint-goals.json" "$1" <<'PY'
import json, sys
try:
    t = json.load(open(sys.argv[1], encoding='utf-8'))['teams'][sys.argv[2]]
    print(t.get('name') or sys.argv[2].upper())
except (OSError, ValueError, KeyError):
    print(sys.argv[2].upper())
PY
}

prompt_for() { # профиль команда
  cat <<EOF
Комментарии к слайду «Риски и проблемы» отчёта спринта, команда $2. Навык sprint-risk-notes в профиле — пройди его шаги 1–6.
Коротко: business.py risk-todo --team $2 → сверка с Jira ТОЛЬКО ЧТЕНИЕМ → черновик {KEY: «почему стоим. что сделать.»} → business.py risk-put --team $2 --author $1 → python3 -m business fresh.
В Jira и людям не пиши. Ответ — 1–3 строки.
EOF
}

fail=0
for spec in "${SPECS[@]}"; do
  IFS=: read -r profile team schedule <<<"$spec"
  pdir="$HERMES_HOME/profiles/$profile"
  skill="$pdir/skills/sprint-risk-notes/SKILL.md"
  name="sprint-risk-notes-$team"
  if [ ! -d "$pdir" ]; then echo "✗ $profile: нет профиля $pdir"; fail=1; continue; fi
  id="$(job_id "$profile" "$name")"
  case "$MODE" in
    check)
      [ -f "$skill" ] && grep -q -- "--team $team " "$skill" && s="навык ✓" || { s="навыка нет"; fail=1; }
      [ -n "$id" ] && c="cron $name ✓ ($id)" || { c="cron $name нет"; fail=1; }
      echo "$profile: $s, $c"
      ;;
    remove)
      if [ -n "$id" ]; then "$HERMES" -p "$profile" cron remove "$id" >/dev/null; echo "$profile: cron $name снят"; fi
      if [ -f "$skill" ]; then rm -f "$skill"; rmdir "$(dirname "$skill")" 2>/dev/null || true; fi
      echo "$profile: навык снят"
      ;;
    install|replace)
      tmp="$(mktemp)"
      python3 - "$TEMPLATE" "$tmp" TEAM_NAME="$(team_name "$team")" TEAM="$team" PROFILE="$profile" \
        AGENTS="$AGENTS_DIR" REPORTS="$REPORTS_DIR" WIDGET="$WIDGET_DIR" PAGE_URL="$PAGE_URL" <<'PY'
import sys
text = open(sys.argv[1], encoding='utf-8').read()
for pair in sys.argv[3:]:
    k, v = pair.split('=', 1)
    text = text.replace('{{' + k + '}}', v)
assert '{{' not in text, 'в шаблоне осталась подстановка'
open(sys.argv[2], 'w', encoding='utf-8').write(text)
PY
      install -d -m 755 "$(dirname "$skill")"
      install -m 644 "$tmp" "$skill"; rm -f "$tmp"
      echo "$profile: навык → $skill"
      if [ -n "$id" ] && [ "$MODE" = install ]; then
        echo "$profile: cron $name уже есть ($id) — пропуск (--replace — пересоздать)"; continue
      fi
      if [ -n "$id" ]; then  # не снялся — set -e остановит до create: двух задач не будет
        "$HERMES" -p "$profile" cron remove "$id" >/dev/null; echo "$profile: старый cron $name снят"
      fi
      "$HERMES" -p "$profile" cron create "$schedule" "$(prompt_for "$profile" "$team")" \
        --name "$name" --skill sprint-risk-notes --deliver local \
        --workdir "$AGENTS_DIR/.claude/skills/sprint-business" >/dev/null
      id="$(job_id "$profile" "$name")"
      [ -n "$id" ] && echo "$profile: cron $name «$schedule» ✓ ($id)" || { echo "✗ $profile: cron $name не появился"; fail=1; }
      ;;
  esac
done
exit $fail
