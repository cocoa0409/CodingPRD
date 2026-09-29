"""Request-shape validation (PRD 2.11 step 4) and pagination parsing."""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import fail

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def json_body():
    """The request body as a dict; a malformed body is ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def _bad(field, detail):
    fail("ERR_INVALID_REQUEST", "Field %s %s." % (field, detail))


def _check_range(field, value, spec):
    if "gt" in spec and not value > spec["gt"]:
        _bad(field, "must be greater than %s" % spec["gt"])
    if "ge" in spec and not value >= spec["ge"]:
        _bad(field, "must be at least %s" % spec["ge"])
    if "lt" in spec and not value < spec["lt"]:
        _bad(field, "must be less than %s" % spec["lt"])
    if "le" in spec and not value <= spec["le"]:
        _bad(field, "must be at most %s" % spec["le"])


def _coerce(field, raw, spec):
    kind = spec["type"]
    if kind == "string":
        if not isinstance(raw, str):
            _bad(field, "must be a string")
        return raw
    if kind == "enum":
        if not isinstance(raw, str):
            _bad(field, "must be a string")
        if raw not in spec["values"]:
            _bad(field, "must be one of %s" % ", ".join(spec["values"]))
        return raw
    if kind == "integer":
        if isinstance(raw, bool) or not isinstance(raw, int):
            _bad(field, "must be an integer")
        _check_range(field, raw, spec)
        return raw
    if kind == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            _bad(field, "must be a number")
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            _bad(field, "must be a number")
        _check_range(field, value, spec)
        return value
    if kind == "boolean":
        if not isinstance(raw, bool):
            _bad(field, "must be a boolean")
        return raw
    if kind == "date":
        value = clock.parse_date(raw)
        if value is None:
            _bad(field, "must be a date formatted YYYY-MM-DD")
        return value
    if kind == "datetime":
        value = clock.parse_datetime(raw)
        if value is None:
            _bad(field, "must be an ISO 8601 timestamp")
        return value
    raise AssertionError("unknown field type %s" % kind)


def validate(payload, spec):
    """Validate a body against a field spec, returning the coerced values.

    Unknown fields, missing required fields, wrong types, undeclared enum
    members and out-of-range numbers are all ERR_INVALID_REQUEST (400).
    """
    for field in payload:
        if field not in spec:
            _bad(field, "is not a recognised input")
    parsed = {}
    for field, rules in spec.items():
        if field not in payload or payload[field] is None:
            if rules.get("required") and field not in payload:
                _bad(field, "is required")
            if rules.get("required") and payload.get(field, "?") is None:
                _bad(field, "may not be null")
            continue
        parsed[field] = _coerce(field, payload[field], rules)
    return parsed


def _int_param(name, raw, minimum, maximum):
    text = raw.strip()
    if not text:
        _bad(name, "must be an integer")
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        _bad(name, "must be an integer")
    value = int(text)
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return value


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 and is not negative.

    A value outside those bounds is a malformed request (PRD 2.3).
    """
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _int_param("limit", raw_limit, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _int_param("offset", raw_offset, 0, None)
    return limit, offset


def paginate(records):
    limit, offset = pagination()
    total = len(records)
    window = records[offset:offset + limit]
    return window, total, limit, offset
