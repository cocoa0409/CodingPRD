"""Request-shape validation in the refusal order of PRD §2.7.

Stage 1 -- unknown keys, required presence and declared scalar type (ERR_INVALID_REQUEST).
Stage 2 -- enum membership (ERR_INVALID_ENUM_VALUE).
Stage 3 -- every other field constraint (ERR_INVALID_REQUEST).
"""

import re

from flask import request

import clock
from errors import ApiError


class F(object):
    def __init__(
        self,
        name,
        kind,
        required=False,
        values=None,
        min_len=None,
        max_len=None,
        min_val=None,
        max_val=None,
        pattern=None,
        non_empty=False,
        unique=False,
        not_blank=False,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.values = values
        self.min_len = min_len
        self.max_len = max_len
        self.min_val = min_val
        self.max_val = max_val
        self.pattern = re.compile(pattern) if pattern else None
        self.non_empty = non_empty
        self.unique = unique
        self.not_blank = not_blank


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def raw_body():
    """The parsed JSON object of the request, or {} when no body was sent."""
    data = request.get_data()
    if data is None or len(data.strip()) == 0:
        return {}
    payload = request.get_json(force=True, silent=True)
    if payload is None:
        _bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def _type_ok(field, value):
    kind = field.kind
    if kind in ("string", "date", "instant", "enum"):
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind in ("array", "enum_array"):
        return isinstance(value, list) and all(isinstance(e, str) for e in value)
    return False


def body(fields, raw=None):
    """Validate a request body against the endpoint's declared input fields."""
    raw = raw_body() if raw is None else raw
    declared = set(f.name for f in fields)
    for key in raw:
        if key not in declared:
            _bad("Unknown field '%s' in request body." % key)

    vals = {}
    for f in fields:
        if f.name not in raw or raw[f.name] is None:
            if f.required:
                _bad("Field '%s' is required." % f.name)
            continue
        value = raw[f.name]
        if not _type_ok(f, value):
            _bad("Field '%s' has the wrong type." % f.name)
        vals[f.name] = value

    for f in fields:
        if f.name not in vals:
            continue
        value = vals[f.name]
        if f.kind == "enum" and value not in f.values:
            raise ApiError(
                "ERR_INVALID_ENUM_VALUE",
                "Field '%s' must be one of %s." % (f.name, ", ".join(f.values)),
            )
        if f.kind == "enum_array":
            for element in value:
                if element not in f.values:
                    raise ApiError(
                        "ERR_INVALID_ENUM_VALUE",
                        "Field '%s' must contain only %s." % (f.name, ", ".join(f.values)),
                    )

    for f in fields:
        if f.name not in vals:
            continue
        _constrain(f, vals[f.name])
    return vals


def _constrain(f, value):
    if f.kind in ("string", "enum", "date", "instant"):
        if f.not_blank and value.strip() == "":
            _bad("Field '%s' must not be blank." % f.name)
        if f.min_len is not None and len(value) < f.min_len:
            _bad("Field '%s' must be at least %d characters." % (f.name, f.min_len))
        if f.max_len is not None and len(value) > f.max_len:
            _bad("Field '%s' must be at most %d characters." % (f.name, f.max_len))
        if f.pattern is not None and not f.pattern.match(value):
            _bad("Field '%s' does not match its required format." % f.name)
        if f.kind == "date" and clock.parse_date(value) is None:
            _bad("Field '%s' must be a calendar date in year-month-day form." % f.name)
        if f.kind == "instant" and clock.parse_instant(value) is None:
            _bad("Field '%s' must be an ISO 8601 UTC instant." % f.name)
    elif f.kind in ("int", "number"):
        if f.min_val is not None and value < f.min_val:
            _bad("Field '%s' must be at least %s." % (f.name, f.min_val))
        if f.max_val is not None and value > f.max_val:
            _bad("Field '%s' must be at most %s." % (f.name, f.max_val))
    elif f.kind in ("array", "enum_array"):
        if f.non_empty and len(value) == 0:
            _bad("Field '%s' must not be empty." % f.name)
        if f.unique and len(set(value)) != len(value):
            _bad("Field '%s' must not contain duplicates." % f.name)


def query_enum(name, values):
    """Read an optional enum-valued query filter."""
    value = request.args.get(name)
    if value is None:
        return None
    if value not in values:
        raise ApiError(
            "ERR_INVALID_ENUM_VALUE",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(values)),
        )
    return value


def query_str(name):
    return request.args.get(name)
