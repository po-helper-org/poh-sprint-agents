#!/usr/bin/env python3
"""Минимальный валидатор JSON Schema на stdlib.

Зачем свой, а не jsonschema: плагин ставится копированием файлов, без pip и venv.
Поддерживается подмножество draft-07, которого достаточно для contract/team.schema.json:

    $ref (только внутри документа), type, enum, const, required, properties,
    additionalProperties, items, pattern, minLength, minimum, maximum,
    minItems, maxItems

Неизвестные ключевые слова игнорируются молча — валидатор не притворяется полным.
Ошибка — пара (json_path, сообщение), чтобы runner мог назвать команду и поле (ФТ-11).
"""
import json
import re

__all__ = ['validate', 'load_schema', 'Error']


class Error(tuple):
    """(path, message) — с человекочитаемым repr для сообщений runner."""

    def __new__(cls, path, message):
        return super().__new__(cls, (path or '$', message))

    @property
    def path(self):
        return self[0]

    @property
    def message(self):
        return self[1]

    def __str__(self):
        return f'{self.path}: {self.message}'


def load_schema(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


TYPE_CHECKS = {
    'object': lambda v: isinstance(v, dict),
    'array': lambda v: isinstance(v, list),
    'string': lambda v: isinstance(v, str),
    'boolean': lambda v: isinstance(v, bool),
    'null': lambda v: v is None,
    # bool — подтип int в Python, но JSON-число это не bool
    'integer': lambda v: isinstance(v, int) and not isinstance(v, bool),
    'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}

TYPE_NAMES = {
    'object': 'объект', 'array': 'массив', 'string': 'строка', 'boolean': 'boolean',
    'null': 'null', 'integer': 'целое число', 'number': 'число',
}


def _resolve(ref, root):
    if not ref.startswith('#/'):
        raise ValueError(f'поддерживаются только локальные $ref, получен {ref!r}')
    node = root
    for part in ref[2:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        node = node[part]
    return node


def _join(path, part):
    return f'{path}{part}' if path else part.lstrip('.')


def validate(instance, schema, root=None, path=''):
    """Список ошибок Error. Пустой список — данные валидны."""
    root = root if root is not None else schema
    errors = []
    _validate(instance, schema, root, path, errors)
    return errors


def _validate(value, schema, root, path, errors):
    if '$ref' in schema:
        schema = _resolve(schema['$ref'], root)

    types = schema.get('type')
    if types is not None:
        allowed = [types] if isinstance(types, str) else list(types)
        if not any(TYPE_CHECKS[t](value) for t in allowed if t in TYPE_CHECKS):
            want = ' или '.join(TYPE_NAMES.get(t, t) for t in allowed)
            errors.append(Error(path, f'ожидается {want}, получено {_shape(value)}'))
            return
        # null — терминальное значение: остальные ключевые слова к нему не применяются
        if value is None:
            return

    if 'enum' in schema and value not in schema['enum']:
        allowed = ', '.join(json.dumps(v, ensure_ascii=False) for v in schema['enum'])
        errors.append(Error(path, f'значение {json.dumps(value, ensure_ascii=False)} не входит в набор: {allowed}'))
    if 'const' in schema and value != schema['const']:
        errors.append(Error(path, f'ожидается {json.dumps(schema["const"], ensure_ascii=False)}'))

    if isinstance(value, str):
        _string_rules(value, schema, path, errors)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _number_rules(value, schema, path, errors)
    elif isinstance(value, dict):
        _object_rules(value, schema, root, path, errors)
    elif isinstance(value, list):
        _array_rules(value, schema, root, path, errors)


def _shape(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, dict):
        return 'объект'
    if isinstance(value, list):
        return 'массив'
    if isinstance(value, str):
        return 'строка'
    if isinstance(value, int):
        return 'целое число'
    return 'число'


def _string_rules(value, schema, path, errors):
    if 'minLength' in schema and len(value) < schema['minLength']:
        errors.append(Error(path, f'строка короче {schema["minLength"]} символов (получено {len(value)!r})'))
    if 'pattern' in schema and not re.search(schema['pattern'], value):
        errors.append(Error(path, f'строка {value!r} не соответствует шаблону {schema["pattern"]}'))


def _number_rules(value, schema, path, errors):
    if 'minimum' in schema and value < schema['minimum']:
        errors.append(Error(path, f'{value} меньше минимума {schema["minimum"]}'))
    if 'maximum' in schema and value > schema['maximum']:
        errors.append(Error(path, f'{value} больше максимума {schema["maximum"]}'))


def _object_rules(value, schema, root, path, errors):
    for key in schema.get('required', []):
        if key not in value:
            errors.append(Error(_join(path, f'.{key}'), 'обязательное поле отсутствует'))
    props = schema.get('properties', {})
    for key in sorted(value):
        sub = _join(path, f'.{key}')
        if key in props:
            _validate(value[key], props[key], root, sub, errors)
            continue
        extra = schema.get('additionalProperties')
        if extra is False:
            errors.append(Error(sub, 'неизвестное поле'))
        elif isinstance(extra, dict):
            _validate(value[key], extra, root, sub, errors)


def _array_rules(value, schema, root, path, errors):
    if 'minItems' in schema and len(value) < schema['minItems']:
        errors.append(Error(path, f'элементов {len(value)}, нужно не меньше {schema["minItems"]}'))
    if 'maxItems' in schema and len(value) > schema['maxItems']:
        errors.append(Error(path, f'элементов {len(value)}, нужно не больше {schema["maxItems"]}'))
    items = schema.get('items')
    if isinstance(items, dict):
        for i, item in enumerate(value):
            _validate(item, items, root, f'{path}[{i}]', errors)
