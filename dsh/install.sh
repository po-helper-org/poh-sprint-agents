#!/usr/bin/env bash
# Установка плагина poh-sprint-plugin в DeepSeek Harness (режим skill-root).
#
# Плагин не поднимает UI-раздел: скиллы подключаются к харнессу как нативный
# skill-root и вызываются из чата. Поэтому установка — это правка одного файла
# профиля, сборка не нужна.
#
#   bash dsh/install.sh --harness /путь/к/harness --workspace /путь/к/воркспейсу
#                       [--profile web] [--dry-run] [--check]
#
# Идемпотентна: повторный прогон переписывает свой блок, чужие записи профиля
# не трогает.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARK_OPEN="# >>> poh-sprint-plugin >>>"
MARK_CLOSE="# <<< poh-sprint-plugin <<<"

HARNESS=""; WORKSPACE=""; PROFILE="web"; DRY=0; CHECK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --harness)   HARNESS="${2:-}"; shift 2 ;;
    --workspace) WORKSPACE="${2:-}"; shift 2 ;;
    --profile)   PROFILE="${2:-}"; shift 2 ;;
    --dry-run)   DRY=1; shift ;;
    --check)     CHECK=1; shift ;;
    -h|--help)   sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "неизвестный аргумент: $1" >&2; exit 2 ;;
  esac
done

die() { echo "ОШИБКА: $*" >&2; exit 1; }

[ -n "$HARNESS" ]   || die "нужен --harness /путь/к/harness"
[ -n "$WORKSPACE" ] || die "нужен --workspace /путь/к/воркспейсу"
[ -d "$HARNESS" ]   || die "каталога харнесса нет: $HARNESS"
[ -d "$REPO/.claude/skills/sprint-result" ] || die "в репозитории нет .claude/skills/sprint-result — не тот каталог?"

PROFILE_DIR="$HARNESS/.dsh-data/profiles/$PROFILE"
PATCH="$PROFILE_DIR/cordis.patch.yml"
SKILLS="$REPO/.claude/skills"

# ── режим проверки: ничего не пишет ──────────────────────────────────────────
if [ "$CHECK" = "1" ]; then
  fails=0
  [ -f "$PATCH" ] || { echo "FAIL  нет $PATCH"; fails=$((fails+1)); }
  if [ -f "$PATCH" ]; then
    grep -qF "$MARK_OPEN" "$PATCH" || { echo "FAIL  блок плагина в профиле не найден"; fails=$((fails+1)); }
    grep -qF "$SKILLS" "$PATCH"    || { echo "FAIL  customSkillDirs не указывает на $SKILLS"; fails=$((fails+1)); }
  fi
  [ -f "$WORKSPACE/.claude/domain-profile.md" ] || { echo "FAIL  нет $WORKSPACE/.claude/domain-profile.md"; fails=$((fails+1)); }
  [ "$fails" = "0" ] && echo "ok    плагин установлен в профиль $PROFILE"
  exit "$fails"
fi

# ── доменный профиль воркспейса ──────────────────────────────────────────────
# Скиллы читают пути и вайтлист отсюда. Существующий не трогаем.
DP="$WORKSPACE/.claude/domain-profile.md"
if [ -e "$DP" ]; then
  DP_ACTION="есть, не тронут"
else
  DP_ACTION="создан из шаблона (заполнить)"
  if [ "$DRY" = "0" ]; then
    mkdir -p "$WORKSPACE/.claude"
    cp "$REPO/domain-profile.template.md" "$DP"
  fi
fi

# ── блок профиля ─────────────────────────────────────────────────────────────
BLOCK="$MARK_OPEN
# Управляется dsh/install.sh репозитория poh-sprint-agents. Правки внутри блока
# перезапишутся при следующем прогоне.
- id: skill-filesystem
  name: '@deepseek-ai/dsh-skill-filesystem'
  disabled: false
  config:
    customSkillDirs:
      - '$SKILLS'
- id: tool-skill
  name: '@deepseek-ai/dsh-tool-skill'
  disabled: false
$MARK_CLOSE"

if [ "$DRY" = "1" ]; then
  echo "— сухой прогон, ничего не записано —"
  echo "профиль:          $PATCH"
  echo "skill-root:       $SKILLS"
  echo "домен-профиль:    $DP ($DP_ACTION)"
  echo "блок для профиля:"
  echo "$BLOCK" | sed 's/^/    /'
  exit 0
fi

mkdir -p "$PROFILE_DIR"
if [ -f "$PATCH" ] && grep -qF "$MARK_OPEN" "$PATCH"; then
  # Свой блок заменяем целиком, чужие записи профиля не трогаем.
  python3 - "$PATCH" "$MARK_OPEN" "$MARK_CLOSE" "$BLOCK" <<'PY'
import sys, pathlib
path, open_m, close_m, block = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
text = pathlib.Path(path).read_text(encoding="utf-8")
head, _, rest = text.partition(open_m)
_, _, tail = rest.partition(close_m)
pathlib.Path(path).write_text(head + block + tail, encoding="utf-8")
PY
  ACTION="блок обновлён"
else
  [ -f "$PATCH" ] || printf '# Профиль харнесса. Записи ниже добавляются плагинами.\n' > "$PATCH"
  printf '\n%s\n' "$BLOCK" >> "$PATCH"
  ACTION="блок добавлен"
fi

# Профиль обязан остаться валидным YAML: битый файл роняет харнесс целиком.
python3 -c "
import sys, yaml
d = yaml.safe_load(open('$PATCH', encoding='utf-8'))
if not isinstance(d, list): sys.exit('профиль должен быть списком записей')
" || die "после правки $PATCH перестал быть валидным YAML — файл не тронут дальше, разберите вручную"

cat <<EOF

Плагин установлен.

  профиль:        $PATCH ($ACTION)
  skill-root:     $SKILLS
  домен-профиль:  $DP ($DP_ACTION)

Дальше:
  1. Заполнить $DP — пути к спринтам, ростер, вайтлист ссылок.
  2. Перезапустить харнесс: на живую он плагин не подхватывает.
       cd $HARNESS && DSH_HOME="\$PWD/.dsh-data" pnpm dsh $PROFILE --no-open --port 3082
  3. В чате: «собери отчёт по спринту 2026Q3-S8».

Проверить установку: bash dsh/install.sh --harness $HARNESS --workspace $WORKSPACE --check
EOF
