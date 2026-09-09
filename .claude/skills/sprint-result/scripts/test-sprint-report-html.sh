#!/usr/bin/env bash
# Смоук экспортёра: эталон отчёта → колода, проверка доменных преобразований.
# Прогоняется руками и в CI; сторонних зависимостей не требует.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(dirname "$HERE")"
IDEAL="$SKILL/examples/ideal_sprint_report.md"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
OUT="$TMP/deck.html"
fails=0

check()  { if grep -qF -- "$2" "$OUT"; then echo "ok   $1"; else echo "FAIL $1 (нет: $2)"; fails=$((fails+1)); fi; }
absent() { if grep -qF -- "$2" "$OUT"; then echo "FAIL $1 (найдено: $2)"; fails=$((fails+1)); else echo "ok   $1"; fi; }
count()  { n=$(grep -oF -- "$2" "$OUT" | wc -l); if [ "$n" -eq "$3" ]; then echo "ok   $1 ($n)"; else echo "FAIL $1: $n, ожидалось $3"; fails=$((fails+1)); fi; }

python3 "$HERE/sprint-report-html.py" "$IDEAL" -o "$OUT" >/dev/null

check "титульный слайд"          'class="slide title-slide"'
check "HERO команды"             'class="slide hero-slide"'
check "название команды"         '<h1>ЯДРО</h1>'
check "подзаголовок команды"     'class="hero-sub">Шлюзы и перенос нагрузки'
check "заголовок стрима"         '<h1 class="slide-title">Перенос нагрузки</h1>'
check "подзаголовок стрима"      'стрим "Перенос нагрузки"'
check "вердикт в подзаголовке"   'Sprint Goal: достигнут частично'
check "доказательство в подсказке" 'title="Обещали весь внешний трафик'
check "легенда на слайде стрима" 'class="pill green"'
check "заливка строки: зелёная"  '<tr class="row stat-green">'
check "заливка строки: жёлтая"   '<tr class="row stat-yellow">'
check "заливка строки: красная"  '<tr class="row stat-red">'
check "список фактов в ячейке"   '<li>Переключено 100%, десять суток без сбоев</li>'
check "задача без префикса роли"  '<td class="task">Переключение B2B'
absent "эталон не несёт ролей"    '<span class="role">'
check "слайд метрик командный"   'Метрики ВИТРИНА команды'
check "три карточки метрик"      'class="metrics-grid tri"'
check "карточка без объяснения"  '<h3>Дашборд трекера</h3>'
check "слайд РИСКИ"              'class="slide-title">РИСКИ</h1>'
check "блок риска"               'class="risk-block"'
check "имена команд на итогах"   'ЯДРО + ВИТРИНА'
check "инициативы считают ACTIVITY" '16 инициатив по 4 стримам'
check "строка следующего шага"   'class="next">След. шаг: <span class="next-item">'
check "ступень ушла в подсказку" 'title="в Production"'
check "подпись о сортировке"     'Сортировка: по убыванию результата'
check "стоп-маркер внешний"      '🛑 0%'
check "стоп-маркер внутренний"   '🚫 0%'
check "карточка изменения"       'class="change"'
check "слайд демо"               'class="slide-title">Демо</h1>'
check "карточка метрики"         'class="metric-card"'
check "место под скриншот"       'class="noshot"'
check "счётчики итогов"          'class="kpi green"'
check "риски на итогах"          'Ключевые риски и блокеры'
check "перенос на итогах"        'Переносим в следующий спринт'
check "нумерация слайдов"        'class="slide-num"'
absent "аннотация эталона не в выводе" 'Аннотированный эталон'
absent "разделитель не протёк в метрику" 'растёт. ---'

# Сортировка по убыванию: в первом стриме сперва 100%, в конце 50%.
python3 - "$OUT" <<'PY'
import re, sys
html = open(sys.argv[1], encoding="utf-8").read()
slide = html.split('>Перенос нагрузки</h1>')[1].split('</section>')[0]
vals = [int(m) for m in re.findall(r'class="result"[^>]*>(\d+)%', slide)]
print("ok   сортировка по убыванию" if vals == sorted(vals, reverse=True)
      else f"FAIL сортировка: {vals}")
sys.exit(0 if vals == sorted(vals, reverse=True) else 1)
PY
[ $? -eq 0 ] || fails=$((fails+1))

# Слайд растёт под стрим: по умолчанию разреза нет, самый плотный стрим целиком.
absent "по умолчанию стрим не режется" '(продолжение)'
python3 "$HERE/sprint-report-html.py" "$IDEAL" -o "$OUT" --max-rows 2 >/dev/null
check "разрез по явному --max-rows" '(продолжение)'
python3 "$HERE/sprint-report-html.py" "$IDEAL" -o "$OUT" >/dev/null

# Префикс роли необязателен, но поддерживается, если PO его просит.
ROLED="$TMP/roled.md"
sed 's|Переключение B2B → новое ядро|[RELEASE] BE-1: Переключение B2B|' "$IDEAL" > "$ROLED"
python3 "$HERE/sprint-report-html.py" "$ROLED" -o "$OUT" >/dev/null
check "префикс роли выносится строкой" '<span class="role">[RELEASE] BE-1</span>'
python3 "$HERE/sprint-report-html.py" "$IDEAL" -o "$OUT" >/dev/null

# Гейт 5 в экспортёре: без вайтлиста внешняя ссылка остаётся текстом.
LINKED="$TMP/linked.md"
sed 's|- Дашборд переключения B2B — 2 минуты|- Запись — https://wiki.example.org/rec|' \
  "$IDEAL" > "$LINKED"

python3 "$HERE/sprint-report-html.py" "$LINKED" -o "$OUT" >/dev/null
absent "без вайтлиста ссылка не кликабельна" '<a href="https://wiki.example.org/rec"'
python3 "$HERE/sprint-report-html.py" "$LINKED" -o "$OUT" --link-whitelist wiki.example.org >/dev/null
check  "с вайтлистом ссылка кликабельна" '<a href="https://wiki.example.org/rec"'
python3 "$HERE/sprint-report-html.py" "$LINKED" -o "$OUT" --link-whitelist other.example >/dev/null
absent "чужой хост в вайтлисте не открывает ссылку" '<a href="https://wiki.example.org/rec"'

echo "провалов: $fails"
[ "$fails" -eq 0 ]
