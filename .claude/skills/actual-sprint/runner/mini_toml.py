#!/usr/bin/env python3
"""Мини-парсер TOML-подмножества конфига отчёта + нормализация ISO-дат.

Зачем: конфиг — TOML, а tomllib появляется в stdlib только в Python 3.11.
Стенд пользователя должен работать на системном python3 (часто 3.10) без
установки зависимостей: плагин ставится копированием файлов. Поэтому здесь
свой разбор ОГРАНИЧЕННОГО TOML — ровно той формы, что допускает конфиг
sprint-report.config.toml (см. examples/). Всё вне подмножества отклоняется
понятной ошибкой с номером строки, а не молча игнорируется.

Подмножество:
  - ключ-значение: bare и «в кавычках» ключи
  - значения: basic-строки "…", целые, true/false, массивы (в одну строку
    и многострочные, с комментариями и висячей запятой)
  - таблицы [a.b.c] и массивы таблиц [[teams]] с вложенными таблицами

Не входит (и отвергается): float, datetime-литералы, multiline-строки,
inline-таблицы, dotted-ключи в ключ-значении. Расширять по мере надобности.

parse_iso: JIRA отдаёт '2026-09-15T17:00:00.000+0300' — без двоеточия в
смещении, что datetime.fromisoformat в 3.10 не понимает (в 3.11 научился).
Нормализуем смещение к '+03:00' и 'Z' к '+00:00' — тогда работает везде.
"""
import re
from datetime import datetime

__all__ = ['loads', 'parse_iso', 'MiniTomlError']


class MiniTomlError(ValueError):
    """TOML вне поддерживаемого подмножества. Текст готов к показу человеку."""


_INT_RE = re.compile(r'^[+-]?[0-9]+$')


def parse_iso(ts):
    """datetime.fromisoformat, толерантный к формату JIRA ('+0300', 'Z')."""
    if not isinstance(ts, str):
        raise ValueError(f'ожидалась строка времени, получено {type(ts).__name__}')
    text = ts.strip()
    # 'Z' → '+00:00'; делаем до смещений, чтобы не тронуть их двоеточия
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    # смещение без двоеточия в конце: +0300 / -0500 → +03:00 / -05:00
    m = re.search(r'([+-]\d{2})(\d{2})$', text)
    if m and ':' not in text[m.start():]:
        text = text[:m.start()] + m.group(1) + ':' + m.group(2)
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f'не разбирается как ISO-время: {ts!r} ({exc})') from exc


def _strip_comment(line):
    """Убирает '#'-комментарий вне кавычек. Возвращает (текст, в_кавычках?)."""
    out = []
    in_str = False
    for ch in line:
        if ch == '"':
            in_str = not in_str
            out.append(ch)
        elif ch == '#' and not in_str:
            break
        else:
            out.append(ch)
    return ''.join(out), in_str


class _Parser:
    def __init__(self, text):
        self.lines = text.splitlines()
        self.pos = 0

    # ------------------------------------------------------------- служебное

    def _err(self, msg):
        return MiniTomlError(f'{msg} (строка {self.pos})')

    def _peek_line(self):
        """Следующая содержательная строка без комментария, без переноса.
        Поднимает pos только при фактическом чтении значения."""
        while self.pos < len(self.lines):
            raw = self.lines[self.pos]
            text, in_str = _strip_comment(raw)
            if text.strip() == '' and not in_str:
                self.pos += 1
                continue
            return text
        return None

    def _next_line(self):
        text = self._peek_line()
        if text is None:
            raise self._err('кончился файл внутри значения')
        self.pos += 1
        return text

    # ------------------------------------------------------------- значения

    def _parse_value(self, text, indent):
        """Разбирает значение справа от '='. Многострочные массивы тянет сам."""
        text = text.strip()
        if text == '':
            raise self._err('пустое значение')
        if text.startswith('"'):
            value, rest = self._parse_string(text)
            rest = rest.strip()
            if rest:
                raise self._err(f'лишнее после строки: {rest!r}')
            return value
        if text.startswith('['):
            return self._parse_array(text, indent)
        if text in ('true', 'false'):
            return text == 'true'
        if _INT_RE.match(text):
            return int(text)
        raise self._err(f'значение вне поддерживаемого TOML-подмножества: {text!r}. '
                        f'Допустимы строки, целые, bool и массивы из них.')

    def _parse_string(self, text):
        """Basic-строка: возвращает (значение, остаток после закрывающей кавычки)."""
        out = []
        i = 1  # после открывающей кавычки
        while i < len(text):
            ch = text[i]
            if ch == '\\' and i + 1 < len(text):
                nxt = text[i + 1]
                escapes = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}
                if nxt not in escapes:
                    raise self._err(f'неизвестная escape-последовательность \\{nxt}')
                out.append(escapes[nxt])
                i += 2
                continue
            if ch == '"':
                return ''.join(out), text[i + 1:]
            out.append(ch)
            i += 1
        raise self._err('строка не закрыта кавычкой до конца строки')

    def _parse_array(self, text, indent):
        """Массив: однострочный или многострочный, с комментариями и висячей запятой."""
        items = []
        body = text[1:]  # после '['
        while True:
            body = body.lstrip()
            if body.startswith('#'):
                nl = body.find('\n')
                body = body[nl + 1:] if nl >= 0 else ''
                continue
            if body == '':
                # массив продолжается на следующей содержательной строке
                body = self._next_line().strip()
                continue
            if body.startswith(']'):
                return items
            if body.startswith(','):
                body = body[1:]
                continue
            if body.startswith('"'):
                value, body = self._parse_string(body)
                items.append(value)
                continue
            # скаляр до , ] или #
            m = re.match(r'[^,\]#]+', body)
            if not m or not m.group(0).strip():
                body = body[m.end():] if m else body[1:]
                continue
            items.append(self._scalar(m.group(0)))
            body = body[m.end():]

    def _parser_err_at_current(self, msg):
        return MiniTomlError(f'{msg} (строка {min(self.pos + 1, len(self.lines))})')

    def _scalar(self, text):
        text = text.strip()
        if text in ('true', 'false'):
            return text == 'true'
        if _INT_RE.match(text):
            return int(text)
        raise self._err(f'элемент массива вне подмножества: {text!r}')

    # --------------------------------------------------------------- таблицы

    def _walk(self, root, dotted):
        """Идёт по вложенным таблицам, создавая их. Последний элемент [[x]]-массива
        считается текущей таблицей — так [teams.params] после [[teams]] попадает
        в последнюю команду, как в настоящем TOML."""
        node = root
        for part in dotted[:-1]:
            nxt = node.get(part)
            if isinstance(nxt, list) and nxt and isinstance(nxt[-1], dict):
                node = nxt[-1]  # проваливаемся в последний [[x]]
            elif isinstance(nxt, dict):
                node = nxt
            elif nxt is None:
                node = node.setdefault(part, {})
            else:
                raise self._err(f'{part!r} уже занято значением, не таблицей')
        return node

    def _dotted(self, header):
        """'[teams.params]' → ['teams', 'params'], снимая кавычки с частей."""
        parts = []
        for part in re.split(r'\s*\.\s*', header.strip()):
            if part.startswith('"') and part.endswith('"') and len(part) >= 2:
                part = part[1:-1]
            parts.append(part)
        return parts


def loads(text):
    """Разбирает TOML-подмножество в dict, как tomllib.loads (насколько это здесь нужно)."""
    parser = _Parser(text)
    root = {}
    current = root
    while True:
        line = parser._peek_line()
        if line is None:
            return root
        parser.pos += 1
        stripped = line.strip()
        if stripped.startswith('[['):
            if not stripped.endswith(']]'):
                raise parser._err(f'заголовок массива таблиц не закрыт: {stripped!r}')
            parts = parser._dotted(stripped[2:-2])
            if not parts or any(p == '' for p in parts):
                raise parser._err(f'пустой сегмент в заголовке: {stripped!r}')
            parent = parser._walk(root, parts)
            last = parts[-1]
            bucket = parent.setdefault(last, [])
            if not isinstance(bucket, list):
                raise parser._err(f'{last!r} уже занято таблицей или значением')
            bucket.append({})
            current = bucket[-1]
            continue
        if stripped.startswith('['):
            if not stripped.endswith(']'):
                raise parser._err(f'заголовок таблицы не закрыт: {stripped!r}')
            parts = parser._dotted(stripped[1:-1])
            if not parts or any(p == '' for p in parts):
                raise parser._err(f'пустой сегмент в заголовке: {stripped!r}')
            parent = parser._walk(root, parts)
            last = parts[-1]
            node = parent.setdefault(last, {})
            if not isinstance(node, dict):
                raise parser._err(f'{last!r} уже занято списком или значением')
            current = node
            continue
        # ключевая строка: ключ = значение
        key, eq, rest = _split_key_eq(stripped)
        if eq is None:
            raise parser._err(f'ожидалось «ключ = значение», получено: {stripped!r}')
        indent = len(line) - len(line.lstrip())
        value = parser._parse_value(rest, indent)
        if key in current:
            raise parser._err(f'ключ {key!r} повторяется')
        current[key] = value


def _split_key_eq(text):
    """'slug = "a"' → ('slug', '=', ' "a"'). Ключ в кавычках допускается."""
    in_str = False
    for i, ch in enumerate(text):
        if ch == '"':
            in_str = not in_str
        elif ch == '=' and not in_str:
            key = text[:i].strip()
            if key.startswith('"') and key.endswith('"') and len(key) >= 2:
                key = key[1:-1]
            if not key:
                raise MiniTomlError(f'пустой ключ в: {text!r}')
            return key, '=', text[i + 1:]
    return text, None, ''
