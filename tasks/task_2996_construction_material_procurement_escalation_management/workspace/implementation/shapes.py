"""Request-shape validation (PRD 2.9 rung 3 -> ERR_INVALID_REQUEST 422).

Every failure in this module is ERR_INVALID_REQUEST with HTTP 422. The engine
rejects unknown fields, missing required fields, wrong JSON types, undeclared
enum members, out-of-range numbers, excess decimal places, blank required
strings, malformed ISO-8601 instants and malformed YYYY-MM periods.
"""

import re

from flask import request

from errors import ApiError
from util import D, PERIOD_RE, decimal_places, parse_instant

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


class Field(object):
    def __init__(self, name, kind, required=False, default=MISSING, minimum=None,
                 maximum=None, exclusive_minimum=None, max_dp=None, choices=None,
                 min_len=None, max_len=None, nullable=False, pattern=None,
                 allow_blank=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_minimum = exclusive_minimum
        self.max_dp = max_dp
        self.choices = choices
        self.min_len = min_len
        self.max_len = max_len
        self.nullable = nullable
        self.pattern = pattern
        self.allow_blank = allow_blank

    def coerce(self, value):
        name = self.name
        if value is None:
            if self.nullable:
                return None
            _bad("%s may not be null" % name)
        kind = self.kind
        if kind == "string" or kind == "enum":
            if not isinstance(value, str):
                _bad("%s must be a string" % name)
            if kind == "enum":
                if value not in self.choices:
                    _bad("%s must be one of %s" % (name, ", ".join(self.choices)))
                return value
            stripped = value.strip()
            if not self.allow_blank and not stripped:
                _bad("%s may not be blank" % name)
            if self.min_len is not None and len(value) < self.min_len:
                _bad("%s must be at least %d characters" % (name, self.min_len))
            if self.max_len is not None and len(value) > self.max_len:
                _bad("%s must be at most %d characters" % (name, self.max_len))
            if self.pattern is not None and not re.match(self.pattern, value):
                _bad("%s is malformed" % name)
            return value
        if kind == "bool":
            if not isinstance(value, bool):
                _bad("%s must be a boolean" % name)
            return value
        if kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                _bad("%s must be an integer" % name)
            return self._check_range(value)
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _bad("%s must be a number" % name)
            try:
                dec = D(value)
                places = decimal_places(value)
            except Exception:
                _bad("%s must be a number" % name)
            if self.max_dp is not None and places > self.max_dp:
                _bad("%s may carry at most %d decimal places" % (name, self.max_dp))
            self._check_range(dec)
            return dec
        if kind == "datetime":
            try:
                return parse_instant(value)
            except (ValueError, TypeError):
                _bad("%s must be an ISO-8601 UTC instant" % name)
        if kind == "period":
            if not isinstance(value, str) or not PERIOD_RE.match(value):
                _bad("%s must be a YYYY-MM period" % name)
            return value
        raise AssertionError("unknown field kind %s" % kind)

    def _check_range(self, value):
        name = self.name
        if self.exclusive_minimum is not None and value <= self.exclusive_minimum:
            _bad("%s must be greater than %s" % (name, self.exclusive_minimum))
        if self.minimum is not None and value < self.minimum:
            _bad("%s may not be lower than %s" % (name, self.minimum))
        if self.maximum is not None and value > self.maximum:
            _bad("%s may not exceed %s" % (name, self.maximum))
        return value


def raw_body():
    """The parsed JSON object of the request, or {} when no body was sent."""
    data = request.get_data(cache=True) or b""
    if not data.strip():
        return {}
    parsed = request.get_json(force=True, silent=True)
    if parsed is None or not isinstance(parsed, dict):
        _bad("the request body must be a JSON object")
    return parsed


def validate(fields):
    """Validate the request body against an ordered field list.

    Returns a dict of coerced values keyed by field name; optional fields that
    were omitted carry their declared default (and are absent when no default
    is declared).
    """
    body = raw_body()
    declared = set(f.name for f in fields)
    for key in body.keys():
        if key not in declared:
            _bad("unknown field: %s" % key)
    for field in fields:
        if field.required and field.name not in body:
            _bad("%s is required" % field.name)
    result = {}
    for field in fields:
        if field.name in body:
            result[field.name] = field.coerce(body[field.name])
        elif field.default is not MISSING:
            result[field.name] = field.default
    return result


def supplied(fields):
    """The set of field names actually present in the request body."""
    return set(raw_body().keys())
