#!/usr/bin/env bash
# Навык quarter-risks и задача cron «тексты рисков квартала» в Hermes-профилях PO-агентов.
#
#   hermes/install-quarter-risks.sh [--check | --remove | --replace] [профиль:команда:"cron" …]
#
# По умолчанию — po-gds:gds, po-live:live, po-mrs:mrs по понедельникам в 09:00 / 09:15 / 09:30
# (после сбора эпиков квартала таймером виджета в 08:45, до синка с CPO; агенты идут по очереди —
# одновременная запись в quarter-risks.json всё равно защищена замком quarter.py put).
# Навык ставится копией (install -m 644) в ~/.hermes/profiles/<профиль>/skills/quarter-risks/ с подставленными
# командой и путями; задача cron — `hermes -p <профиль> cron create` (уже есть — пропуск, --replace — пересоздать).
# Запись в Jira, сообщения людям и ✅ PO навык не делает. Повторный запуск безопасен.
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
PAGE_URL="${PAGE_URL:-/business/risks}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES="${HERMES:-hermes}"
TEMPLATE="$HERE/quarter-risks/SKILL.md"

MODE=install
case "${1:-}" in --check|--remove|--replace) MODE="${1#--}"; shift ;; esac
SPECS=("$@")
[ ${#SPECS[@]} -gt 0 ] || SPECS=("po-gds:gds:0 9 * * 1" "po-live:live:15 9 * * 1" "po-mrs:mrs:30 9 * * 1")

job_id() { # профиль имя → id задачи cron с этим именем (или пусто)
  python3 - "$HERMES_HOME/profiles/$1/cron/jobs.json" "$2" <<'PY'
import json, sys
try:
    doc = json.load(open(sys.argv[1], encoding='utf-8'))
except (OSError, ValueError):
    sys.exit(0)
jobs = doc.get('jobs', []) if isinstance(doc, dict) else doc
print(next((j['id'] for j in jobs if j.get('name') == sys.argv[2]), ''))
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
Риски квартала для синка PO с CPO, команда $2. Навык quarter-risks в профиле — пройди его шаги 1–7 целиком.
Коротко: quarter.py facts --team $2 → по каждой 🔴/🟡 инициативе и кандидату сверка с Jira ТОЛЬКО ЧТЕНИЕМ (jira_get_issue/jira_search) → черновик → quarter.py put --team $2 --author $1 → python3 -m business risks --no-fetch.
Оценку PO (override) не ставь, ✅ не ставь, в Jira и людям не пиши. Ответ — 2–4 строки: что предлагаешь поднять CPO и ссылка на страницу.
EOF
}

fail=0
for spec in "${SPECS[@]}"; do
  IFS=: read -r profile team schedule <<<"$spec"
  pdir="$HERMES_HOME/profiles/$profile"
  skill="$pdir/skills/quarter-risks/SKILL.md"
  name="quarter-risks-$team"
  if [ ! -d "$pdir" ]; then echo "✗ $profile: нет профиля $pdir"; fail=1; continue; fi
  id="$(job_id "$profile" "$name")"
  case "$MODE" in
    check)
      [ -f "$skill" ] && grep -q -- "--team $team " "$skill" && s="навык ✓" || { s="навыка нет"; fail=1; }
      [ -n "$id" ] && c="cron $name ✓ ($id)" || { c="cron $name нет"; fail=1; }
      echo "$profile: $s, $c"
      ;;
    remove)
      [ -n "$id" ] && "$HERMES" -p "$profile" cron remove "$id" >/dev/null && echo "$profile: cron $name снят"
      [ -f "$skill" ] && rm -f "$skill" && rmdir "$(dirname "$skill")" 2>/dev/null; echo "$profile: навык снят"
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
      [ -n "$id" ] && "$HERMES" -p "$profile" cron remove "$id" >/dev/null && echo "$profile: старый cron $name снят"
      "$HERMES" -p "$profile" cron create "$schedule" "$(prompt_for "$profile" "$team")" \
        --name "$name" --skill quarter-risks --deliver local \
        --workdir "$AGENTS_DIR/.claude/skills/sprint-business" >/dev/null
      id="$(job_id "$profile" "$name")"
      [ -n "$id" ] && echo "$profile: cron $name «$schedule» ✓ ($id)" || { echo "✗ $profile: cron $name не появился"; fail=1; }
      ;;
  esac
done
exit $fail
