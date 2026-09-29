"""Request-shape validation (PRD section 2.9 ranks 5 and 6).

Rank 5 covers a required body field that is missing or null, a field of the
wrong JSON type, an enum value outside its declared set, a string violating its
length or pattern rule, an integer outside its declared range, a decimal with
more than two fractional digits, and any unknown field. Everything here raises
ERR_INVALID_REQUEST (400).
"""

import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from util import Q2, parse_dt, r2


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


class Field(object):
    def __init__(self, name, kind, required=True, default=None, values=None,
                 pattern=None, min_len=None, max_len=None, minimum=None,
                 maximum=None, items=None, min_items=None, max_items=None,
                 ignored=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.values = values
        self.pattern = re.compile(pattern) if pattern else None
        self.min_len = min_len
        self.max_len = max_len
        self.minimum = minimum
        self.maximum = maximum
        self.items = items
        self.min_items = min_items
        self.max_items = max_items
        self.ignored = ignored


class Body(dict):
    def __init__(self, values, present):
        dict.__init__(self, values)
        self.present = present

    def has(self, name):
        return name in self.present


def raw_body():
    """Parse the JSON body. Floats become Decimals so fractional digits count."""
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    try:
        parsed = json.loads(data.decode("utf-8"), parse_float=Decimal)
    except (ValueError, UnicodeDecodeError):
        _bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object.")
    return parsed


def peek(name):
    """Read one body field before rank-5 validation (used by rank-4 ownership)."""
    try:
        body = raw_body()
    except ApiError:
        return None
    value = body.get(name)
    if isinstance(value, str):
        return value
    return value


def _check_string(field, value):
    if not isinstance(value, str):
        _bad("Field %s must be a string." % field.name)
    if field.min_len is not None and len(value) < field.min_len:
        _bad("Field %s is shorter than %d characters." % (field.name, field.min_len))
    if field.max_len is not None and len(value) > field.max_len:
        _bad("Field %s is longer than %d characters." % (field.name, field.max_len))
    if field.pattern is not None and field.pattern.match(value) is None:
        _bad("Field %s does not match its required pattern." % field.name)
    return value


def _check_integer(field, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field %s must be an integer." % field.name)
    if field.minimum is not None and value < field.minimum:
        _bad("Field %s is below its minimum of %s." % (field.name, field.minimum))
    if field.maximum is not None and value > field.maximum:
        _bad("Field %s is above its maximum of %s." % (field.name, field.maximum))
    return value


def _check_number(field, value):
    if isinstance(value, bool):
        _bad("Field %s must be a number." % field.name)
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        pass
    else:
        _bad("Field %s must be a number." % field.name)
    try:
        if value != value.quantize(Q2):
            _bad("Field %s carries more than two fractional digits." % field.name)
    except InvalidOperation:
        _bad("Field %s is not a valid decimal." % field.name)
    value = r2(value)
    if field.minimum is not None and value < Decimal(str(field.minimum)):
        _bad("Field %s is below its minimum." % field.name)
    if field.maximum is not None and value > Decimal(str(field.maximum)):
        _bad("Field %s is above its maximum." % field.name)
    return value


def _check_one(field, value):
    kind = field.kind
    if kind == "string":
        return _check_string(field, value)
    if kind == "enum":
        if not isinstance(value, str) or value not in field.values:
            _bad("Field %s carries a value outside its declared set." % field.name)
        return value
    if kind == "integer":
        return _check_integer(field, value)
    if kind == "number":
        return _check_number(field, value)
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad("Field %s must be a boolean." % field.name)
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            _bad("Field %s must be an ISO 8601 UTC instant." % field.name)
        moment = parse_dt(value)
        if moment is None:
            _bad("Field %s is not a well-formed ISO 8601 UTC instant." % field.name)
        return moment
    if kind == "string_array":
        if not isinstance(value, list):
            _bad("Field %s must be an array." % field.name)
        if field.min_items is not None and len(value) < field.min_items:
            _bad("Field %s carries too few entries." % field.name)
        if field.max_items is not None and len(value) > field.max_items:
            _bad("Field %s carries too many entries." % field.name)
        for element in value:
            if not isinstance(element, str) or element == "":
                _bad("Field %s must be an array of strings." % field.name)
        return list(value)
    if kind == "object_array":
        if not isinstance(value, list):
            _bad("Field %s must be an array." % field.name)
        if field.min_items is not None and len(value) < field.min_items:
            _bad("Field %s carries too few entries." % field.name)
        if field.max_items is not None and len(value) > field.max_items:
            _bad("Field %s carries too many entries." % field.name)
        rows = []
        for element in value:
            if not isinstance(element, dict):
                _bad("Field %s must be an array of objects." % field.name)
            rows.append(validate(field.items, element, label=field.name))
        return rows
    raise AssertionError("unknown field kind " + kind)


def validate(fields, body=None, label=None):
    """Validate a JSON object against an ordered list of Field specs."""
    if body is None:
        body = raw_body()
    allowed = set()
    for field in fields:
        allowed.add(field.name)
    for key in body:
        if key not in allowed:
            _bad("Unknown field %s%s." % (key, " in " + label if label else ""))
    values = {}
    present = set()
    for field in fields:
        if field.name not in body or body[field.name] is None:
            if field.name in body and field.required:
                _bad("Required field %s must not be null." % field.name)
            if field.required:
                _bad("Required field %s is missing." % field.name)
            values[field.name] = field.default
            continue
        if field.ignored:
            continue
        values[field.name] = _check_one(field, body[field.name])
        present.add(field.name)
    return Body(values, present)


def query_enum(name, values, default):
    """Validate an optional enum query parameter -> ERR_INVALID_REQUEST."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if raw not in values:
        _bad("Query parameter %s carries a value outside its declared set." % name)
    return raw


def query_dt(name, default):
    """Validate an optional instant query parameter -> ERR_INVALID_REQUEST."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    moment = parse_dt(raw)
    if moment is None:
        _bad("Query parameter %s is not a well-formed ISO 8601 UTC instant." % name)
    return moment
