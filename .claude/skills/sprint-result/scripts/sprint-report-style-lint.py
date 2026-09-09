#!/usr/bin/env python3
"""sprint-report-style-lint — лексический линтер отчёта на AI-слоп и длинноты.

Порт `bft-style-lint.py` из po-helper-org/poh-bft-writer (standalone-копия)
плюс проверки caveman ultra, которых там нет: длина заголовка, длина ячейки,
отглагольные конструкции.

Словарь — `resources/writing_register.md`, но источник правды по составу
паттернов здесь: правило живёт в коде, документ его объясняет.

    python3 sprint-report-style-lint.py ФАКТ-{sprint}.md [ещё.md ...]
    python3 sprint-report-style-lint.py --format json ФАКТ-{sprint}.md

Коды выхода: 0 — чисто; 1 — есть совпадения; 2 — файл не прочитан.
Формат: <путь>:<строка>: <УРОВЕНЬ> <КОД> <сообщение> — «<фрагмент>»
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Pattern:
    code: str
    regex: re.Pattern
    message: str


def _p(code: str, phrase: str, message: str) -> Pattern:
    return Pattern(code, re.compile(r"(?i)\b" + phrase + r"\b"), message)


# --- Стоп-слова (writing_style.md §1) ---------------------------------------

STOP_WORDS: list[Pattern] = [
    _p("SW001", r"позволя(ет|ют)", "стоп-слово «позволяет» — прямое сказуемое"),
    _p("SW002", r"обеспечива(ет|ют)", "стоп-слово «обеспечивает» — прямой глагол"),
    _p("SW003", r"осуществля(ет|ют)", "стоп-слово «осуществляет» — прямой глагол"),
    _p("SW004", r"производ(ит|ят)", "стоп-слово «производит» — прямой глагол"),
    _p("SW005", r"способствует", "стоп-слово «способствует» — убрать конструкцию"),
    _p("SW006", r"представляет собой", "стоп-фраза «представляет собой» — «есть»/«это»"),
    _p("SW007", r"важно отметить,?\s*что", "стоп-фраза «важно отметить, что» — убрать"),
    _p("SW008", r"следует отметить,?\s*что", "стоп-фраза «следует отметить, что» — убрать"),
    _p("SW009", r"необходимо учитывать,?\s*что", "стоп-фраза «необходимо учитывать, что» — убрать"),
    _p("SW010", r"в настоящее время", "стоп-фраза «в настоящее время» — «сейчас» или убрать"),
    _p("SW011", r"в случае возникновения", "стоп-фраза «в случае возникновения» — «при»"),
    _p("SW012", r"с целью обеспечения", "стоп-фраза «с целью обеспечения» — «для»"),
    _p("SW013", r"в связи с тем,?\s*что", "стоп-фраза «в связи с тем что» — «так как»"),
]

# --- Хеджи, мета-комментарии, интенсификаторы (§1a) -------------------------

HEDGES: list[Pattern] = [
    _p("HG001", r"может потенциально", "хедж «может потенциально» — утверждение или [УТОЧНИТЬ]"),
    _p("HG002", r"в некоторых случаях", "хедж «в некоторых случаях» без конкретики"),
    _p("HG003", r"как правило", "хедж «как правило» без конкретики"),
    _p("HG004", r"в определ[её]нной степени", "хедж «в определённой степени»"),
    _p("HG005", r"есть основания полагать", "хедж «есть основания полагать»"),
    _p("HG006", r"в целом (успешно|неплохо|хорошо)", "хедж «в целом успешно» — процент и ступень"),
]

META: list[Pattern] = [
    _p("MC001", r"в данном разделе рассматрива(ется|ются)", "мета-комментарий — сразу факт"),
    _p("MC002", r"важно понимать,?\s*что", "мета-комментарий «важно понимать, что»"),
    _p("MC003", r"начн[её]м с рассмотрения", "мета-комментарий «начнём с рассмотрения»"),
    _p("MC004", r"ниже описаны", "signposting «ниже описаны» — сразу содержимое"),
    _p("MC005", r"перейд[её]м к", "signposting «перейдём к»"),
    _p("MC006", r"стоит отметить", "мета-комментарий «стоит отметить»"),
]

QUALIFIERS: list[Pattern] = [
    _p("QF001", r"полностью завершить", "квалификатор «полностью завершить» → «завершить»"),
    _p("QF002", r"абсолютно необходимо", "квалификатор «абсолютно необходимо» → «необходимо»"),
    _p("QF003", r"крайне важно", "квалификатор «крайне важно» — дать приоритет, не оценку"),
    _p("QF004", r"совершенно уникальн\w*", "интенсификатор «совершенно уникальный»"),
    _p("QF005", r"очень значительн\w*", "интенсификатор «очень значительный» — число"),
    _p("QF006", r"действительно критичн\w*", "интенсификатор «действительно критичный»"),
    _p("QF007", r"успешно (выполнен|завершен|реализован)\w*", "«успешно выполнено» — процент и ступень"),
]

BUZZWORDS: list[Pattern] = [
    _p("BZ001", r"leverage", "buzzword «leverage» — «использовать»"),
    _p("BZ002", r"utilize", "buzzword «utilize» — «использовать»"),
    _p("BZ003", r"holistic", "buzzword «holistic» — конкретный охват"),
    _p("BZ004", r"synergistic|synergy", "buzzword «synergy»"),
    _p("BZ005", r"game[- ]changer", "buzzword «game-changer»"),
    _p("BZ006", r"next[- ]generation", "buzzword «next-generation» — версия или дата"),
    _p("BZ007", r"empower(s|ed|ing)?", "buzzword «empower» — прямой глагол"),
]

# --- Вода и плеоназмы (§11) -------------------------------------------------

WATER: list[Pattern] = [
    _p("TA002", r"в цел(ях|ях того)", "вода «в целях» — «чтобы»"),
    _p("TA002", r"с целью того,?\s+чтобы", "вода «с целью того чтобы» — «чтобы»"),
    _p("TA002", r"в период времени", "плеоназм «в период времени»"),
    _p("TA002", r"на текущий момент времени", "плеоназм «на текущий момент времени» — «сейчас»"),
    _p("TA002", r"в рамках данн(ого|ой|ых)", "вода «в рамках данного» — назвать объект"),
    _p("TA002", r"имеет место быть", "плеоназм «имеет место быть» — «есть»"),
    _p("TA002", r"более лучш(ий|ая|ее|ие|его)", "плеоназм «более лучший» — «лучше»"),
    _p("TA002", r"наиболее оптимальн(ый|ая|ое|ые)", "плеоназм «наиболее оптимальный»"),
    _p("TA002", r"перв(ый|оочередной) приоритет", "плеоназм «первый приоритет»"),
    _p("TA002", r"осуществля(ть|ется|ются)\s+процесс", "вода «осуществляется процесс» — глагол"),
    _p("TA002", r"производится\s+выполнение", "вода «производится выполнение» — глагол"),
    _p("TA002", r"в обязательном порядке", "вода «в обязательном порядке» — «обязательно»"),
    _p("TA002", r"был[аио]?\s+(произведен|выполнен|осуществлен)\w*",
       "отглагольный пассив «была произведена выкатка» — «выкатили» (caveman §5)"),
]

ALL_PATTERNS = STOP_WORDS + HEDGES + META + QUALIFIERS + BUZZWORDS + WATER

# --- Пороги caveman ---------------------------------------------------------

SENTENCE_WORD_LIMIT = 40      # длиннота: предложение не читается с первого раза
CELL_WORD_LIMIT = 45          # ячейка таблицы: дальше строка рвёт слайд 720px
HEADING_WORD_LIMIT = 6        # заголовок слайда: до трёх слов + служебный префикс

WORD_RE = re.compile(r"[А-Яа-яёЁA-Za-z0-9-]+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")
HEADING_RE = re.compile(r"^#{2,3}\s+(?:КОМАНДА|СТРИМ)\s*:\s*(.+)$")


@dataclass
class Finding:
    line: int
    level: str
    code: str
    message: str
    excerpt: str


def _units(raw: str) -> list[str]:
    """Строка таблицы — несколько независимых формулировок, не одно предложение."""
    if raw.strip().startswith("|"):
        return [c for c in raw.strip().strip("|").split("|")]
    return [raw]


def _skip_zones(lines: list[str]) -> set[int]:
    """Вне проверки: frontmatter, fenced-блоки, HTML-комментарии, цитата-аннотация."""
    skip: set[int] = set()
    if lines and lines[0].strip() == "---":
        skip.add(1)
        for zero_idx in range(1, len(lines)):
            skip.add(zero_idx + 1)
            if lines[zero_idx].strip() == "---":
                break
    in_fence = in_comment = False
    for idx, raw in enumerate(lines, start=1):
        stripped = raw.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            skip.add(idx)
            continue
        if in_fence or stripped.startswith("> "):
            skip.add(idx)
            continue
        opens, closes = "<!--" in raw, "-->" in raw
        if in_comment:
            skip.add(idx)
            if closes:
                in_comment = False
            continue
        if opens:
            skip.add(idx)
            if not closes:
                in_comment = True
    return skip


def lint(path: Path) -> list[Finding]:
    lines = path.read_text(encoding="utf-8").split("\n")
    skip = _skip_zones(lines)
    out: list[Finding] = []
    for idx, raw in enumerate(lines, start=1):
        if idx in skip:
            continue
        excerpt = raw.strip()
        if len(excerpt) > 100:
            excerpt = excerpt[:97] + "..."
        for pattern in ALL_PATTERNS:
            if pattern.regex.search(raw):
                out.append(Finding(idx, "ERROR", pattern.code, pattern.message, excerpt))

        heading = HEADING_RE.match(raw)
        if heading:
            words = len(WORD_RE.findall(heading.group(1)))
            if words > HEADING_WORD_LIMIT:
                out.append(Finding(idx, "ERROR", "CV001",
                                   f"заголовок из {words} слов при пороге {HEADING_WORD_LIMIT} — "
                                   "название стрима до трёх слов (caveman §3)", excerpt))
        if raw.lstrip().startswith("#"):
            continue                       # заголовок — не предложение

        for unit in _units(raw):
            words = len(WORD_RE.findall(unit))
            if raw.strip().startswith("|") and words > CELL_WORD_LIMIT:
                out.append(Finding(idx, "ERROR", "CV002",
                                   f"ячейка из {words} слов при пороге {CELL_WORD_LIMIT} — "
                                   "строка не влезет в слайд, разбить на буллеты", excerpt))
            for sentence in SENTENCE_SPLIT_RE.split(unit):
                count = len(WORD_RE.findall(sentence))
                if count > SENTENCE_WORD_LIMIT:
                    out.append(Finding(idx, "ERROR", "TA003",
                                       f"длинная формулировка: {count} слов при пороге "
                                       f"{SENTENCE_WORD_LIMIT} — разбить", excerpt))
    return sorted(out, key=lambda f: (f.line, f.code))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Линтер регистра отчёта: anti-slop + caveman ultra")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args(argv)

    report: dict[str, list[dict]] = {}
    total = 0
    for path in args.files:
        if not path.is_file():
            print(f"{path}: ERROR IO001 файл не найден", file=sys.stderr)
            return 2
        findings = lint(path)
        report[str(path)] = [asdict(f) for f in findings]
        total += len(findings)
        if args.format == "text":
            for f in findings:
                print(f"{path}:{f.line}: {f.level} {f.code} {f.message} — «{f.excerpt}»")
            if not findings:
                print(f"{path}: OK — регистр чист ({len(ALL_PATTERNS)} паттернов проверено)")
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
