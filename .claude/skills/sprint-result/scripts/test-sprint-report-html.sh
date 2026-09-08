#!/usr/bin/env bash
# Смоук экспортёра: эталон отчёта → страница, проверка доменных преобразований.
# Прогоняется руками и в CI; сторонних зависимостей не требует.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(dirname "$HERE")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
OUT="$TMP/report.html"
fails=0

check() { # описание, шаблон
  if grep -qF -- "$2" "$OUT"; then echo "ok   $1"; else echo "FAIL $1 (нет: $2)"; fails=$((fails+1)); fi
}
absent() {
  if grep -qF -- "$2" "$OUT"; then echo "FAIL $1 (найдено: $2)"; fails=$((fails+1)); else echo "ok   $1"; fi
}

python3 "$HERE/sprint-report-html.py" "$SKILL/examples/ideal_sprint_report.md" -o "$OUT" >/dev/null

check "шапка спринта"            '<h1>ФАКТ <span class="sep">|</span> 2026Q3-S8</h1>'
check "светофор спринта"         'class="tally-bar"'
check "плашка вердикта: частично" 'class="verdict v-part"'
check "плашка вердикта: достигнут" 'class="verdict v-ok"'
check "заливка 100%"             'class="res r-ok"'
check "заливка 50-99%"           'class="res r-half"'
check "серая заливка вне шкалы"  'class="res r-idle"'
check "ступень лестницы"         '<span class="step">в Production</span>'
check "метка причины"            'class="c c-why"'
check "метка блокатора"          'class="c c-block"'
check "метка обещания"           'class="c c-goal"'
check "роль исполнителя"         '<span class="role">[RELEASE] BE-1</span>'
check "тег внеплановой"          '<span class="tag">[BUG]</span>'
check "карточка изменения"       'class="change"'
check "маркер уточнения"         '<mark class="unc">[УТОЧНИТЬ ссылку]</mark>'
check "строка KR"                'class="krline"'
check "надзаголовок инициативы"  'инициатива 1 из 2'
check "имя документа в промте"   'ideal_sprint_report.md'
absent "аннотация эталона не в выводе" 'Аннотированный эталон'
absent "тире-разделитель не протёк в вердикт" '. ---'

# Гейт 5 в экспортёре: без вайтлиста внешняя ссылка остаётся текстом.
LINKED="$TMP/linked.md"
sed 's|Запись демонстрации — `\[УТОЧНИТЬ ссылку\]`|Запись — https://wiki.example.org/rec|' \
  "$SKILL/examples/ideal_sprint_report.md" > "$LINKED"

python3 "$HERE/sprint-report-html.py" "$LINKED" -o "$OUT" >/dev/null
absent "без вайтлиста ссылка не кликабельна" '<a href="https://wiki.example.org/rec"'

python3 "$HERE/sprint-report-html.py" "$LINKED" -o "$OUT" --link-whitelist wiki.example.org >/dev/null
check "с вайтлистом ссылка кликабельна" '<a href="https://wiki.example.org/rec"'

python3 "$HERE/sprint-report-html.py" "$LINKED" -o "$OUT" --link-whitelist other.example >/dev/null
absent "чужой хост в вайтлисте не открывает ссылку" '<a href="https://wiki.example.org/rec"'

echo "провалов: $fails"
[ "$fails" -eq 0 ]
