#!/usr/bin/env bash
# Контракт плагина с харнессом. Проверяет то, на чём установка ломается в
# реальности: битый манифест, скилл без описания, триггер, который не совпадает
# с описанием скилла, профиль, который перестал быть валидным YAML, и повторная
# установка, дублирующая блок.
#
# Запуск из корня репозитория: bash dsh/test-contract.sh
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
fails=0
ok()   { echo "ok    $1"; }
bad()  { echo "FAIL  $1"; fails=$((fails + 1)); }

M="$REPO/dsh/plugin.json"

# ── 1. Манифест ──────────────────────────────────────────────────────────────
if python3 -c "import json,sys; json.load(open('$M'))" 2>/dev/null; then
  ok "манифест — валидный JSON"
else
  bad "манифест не разбирается как JSON"; echo "провалов: $fails"; exit 1
fi

python3 - "$M" "$REPO" <<'PY'
import json, pathlib, re, sys
m = json.load(open(sys.argv[1], encoding="utf-8")); repo = pathlib.Path(sys.argv[2])
fails = 0
def ok(s):  print("ok   ", s)
def bad(s):
    global fails; fails += 1; print("FAIL ", s)

for field in ("name", "version", "mode", "skillRoot", "skills", "triggers", "install", "verify"):
    if not m.get(field): bad(f"в манифесте нет поля {field}")
if fails == 0: ok("в манифесте есть все обязательные поля")

# Каждый заявленный скилл существует и несёт frontmatter name + description:
# без описания харнесс не сопоставит скилл фразе из чата.
for s in m["skills"]:
    entry = repo / s["entry"]
    if not entry.is_file():
        bad(f"нет файла скилла: {s['entry']}"); continue
    head = entry.read_text(encoding="utf-8")[:2000]
    if not re.search(r"^---\s*$", head, re.M): bad(f"{s['name']}: нет frontmatter")
    elif f"name: {s['name']}" not in head:     bad(f"{s['name']}: имя в frontmatter не совпадает с манифестом")
    elif "description:" not in head:           bad(f"{s['name']}: нет description — чат-триггер не сработает")
    else: ok(f"скилл {s['name']}: frontmatter на месте")

    for cmd in s.get("commands", []):
        f = repo / m["commandRoot"] / f"{cmd}.md"
        if not f.is_file(): bad(f"нет команды: {cmd}.md")
        elif "description:" not in f.read_text(encoding="utf-8")[:400]:
            bad(f"команда {cmd}: нет description во frontmatter")
if fails == 0: ok("все команды манифеста на месте и описаны")

# Триггер обязан находиться в описании скилла — иначе агент не поймёт, что
# запускать по фразе из чата. Проверяем без учёта ё/е и регистра.
def norm(s): return s.lower().replace("ё", "е")
descs = norm(" ".join((repo / s["entry"]).read_text(encoding="utf-8")[:2000]
                      for s in m["skills"] if (repo / s["entry"]).is_file()))
missing = [t for t in m["triggers"] if norm(t) not in descs]
if missing: bad("триггеры не встречаются в описаниях скиллов: " + ", ".join(missing))
else: ok(f"все {len(m['triggers'])} триггеров находятся в описаниях скиллов")

sys.exit(1 if fails else 0)
PY
[ $? -eq 0 ] || fails=$((fails + 1))

# ── 2. Исполняемость ─────────────────────────────────────────────────────────
if python3 -m py_compile "$REPO"/.claude/skills/sprint-result/scripts/*.py 2>/dev/null
then ok "python-скрипты навыка компилируются"; else bad "python-скрипты не компилируются"; fi
find "$REPO" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null

sh_fail=0
for f in "$REPO"/dsh/*.sh "$REPO"/.claude/skills/sprint-result/scripts/*.sh "$REPO/install.sh"; do
  bash -n "$f" 2>/dev/null || { bad "не разбирается: $f"; sh_fail=1; }
done
[ "$sh_fail" = "0" ] && ok "shell-скрипты разбираются"

# ── 3. Установка в чистый харнесс ────────────────────────────────────────────
H="$TMP/harness"; W="$TMP/ws"
mkdir -p "$H/.dsh-data/profiles/web" "$W"
PATCH="$H/.dsh-data/profiles/web/cordis.patch.yml"

bash "$REPO/dsh/install.sh" --harness "$H" --workspace "$W" --dry-run >/dev/null 2>&1 \
  && [ ! -f "$PATCH" ] \
  && ok "сухой прогон ничего не пишет" || bad "сухой прогон тронул профиль"

bash "$REPO/dsh/install.sh" --harness "$H" --workspace "$W" >/dev/null 2>&1 \
  && ok "установка отработала" || bad "установка упала"

[ -f "$PATCH" ] && ok "профиль создан" || bad "профиль не создан"
[ -f "$W/.claude/domain-profile.md" ] && ok "домен-профиль положен в воркспейс" \
  || bad "домен-профиль не положен"

python3 - "$PATCH" "$REPO" <<'PY'
import pathlib, sys, yaml
patch, repo = sys.argv[1], sys.argv[2]
d = yaml.safe_load(open(patch, encoding="utf-8"))
fails = 0
def ok(s):  print("ok   ", s)
def bad(s):
    global fails; fails += 1; print("FAIL ", s)

if not isinstance(d, list): bad("профиль не список записей")
else: ok("профиль — валидный YAML-список")

by_id = {e.get("id"): e for e in d if isinstance(e, dict)}
for pid in ("skill-filesystem", "tool-skill"):
    e = by_id.get(pid)
    if not e: bad(f"в профиле нет записи {pid}")
    elif e.get("disabled") is not False:
        bad(f"{pid}: без disabled: false инструмент skill не появится")
    else: ok(f"{pid} включён явно")

dirs = (by_id.get("skill-filesystem") or {}).get("config", {}).get("customSkillDirs", [])
want = str(pathlib.Path(repo) / ".claude/skills")
if want in dirs and pathlib.Path(want).is_dir(): ok("customSkillDirs указывает на существующий skill-root")
else: bad(f"customSkillDirs не указывает на {want}: {dirs}")
sys.exit(1 if fails else 0)
PY
[ $? -eq 0 ] || fails=$((fails + 1))

# ── 4. Идемпотентность и сохранность чужих записей ───────────────────────────
printf '\n- id: чужая-запись\n  name: someone-else\n' >> "$PATCH"
bash "$REPO/dsh/install.sh" --harness "$H" --workspace "$W" >/dev/null 2>&1
n=$(grep -cF '>>> poh-sprint-plugin >>>' "$PATCH")
[ "$n" = "1" ] && ok "повторная установка не дублирует блок" || bad "блоков плагина: $n"
grep -q 'чужая-запись' "$PATCH" && ok "чужие записи профиля сохранены" || bad "чужая запись затёрта"
python3 -c "import yaml,sys; yaml.safe_load(open('$PATCH',encoding='utf-8'))" 2>/dev/null \
  && ok "профиль остался валидным YAML после повторной установки" \
  || bad "профиль сломан после повторной установки"

bash "$REPO/dsh/install.sh" --harness "$H" --workspace "$W" --check >/dev/null 2>&1 \
  && ok "--check подтверждает установку" || bad "--check не подтверждает установку"

# ── 5. Сквозной прогон: скиллы работают из установленного воркспейса ─────────
# Не «файлы на месте», а «отчёт собирается»: валидаторы и экспортёр на эталоне.
cp "$REPO/.claude/skills/sprint-result/examples/ideal_sprint_report.md" "$W/ФАКТ-2026Q3-S8.md"
SK="$REPO/.claude/skills/sprint-result/scripts"
python3 "$SK/check_report_structure.py"   "$W/ФАКТ-2026Q3-S8.md" >/dev/null 2>&1 \
  && ok "структурный валидатор проходит на воркспейсе" || bad "структурный валидатор упал"
python3 "$SK/sprint-report-style-lint.py" "$W/ФАКТ-2026Q3-S8.md" >/dev/null 2>&1 \
  && ok "стилевой валидатор проходит" || bad "стилевой валидатор упал"
python3 "$SK/sprint-report-html.py" "$W/ФАКТ-2026Q3-S8.md" -o "$W/deck.html" >/dev/null 2>&1 \
  && [ -s "$W/deck.html" ] && ok "колода собирается в воркспейсе" || bad "колода не собралась"
grep -q 'class="slide title-slide"' "$W/deck.html" 2>/dev/null \
  && ok "колода содержит слайды" || bad "в колоде нет слайдов"

echo "провалов: $fails"
[ "$fails" -eq 0 ]
