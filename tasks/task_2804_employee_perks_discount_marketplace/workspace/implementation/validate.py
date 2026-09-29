"""Schema band of PRD 2.9 (bands 3 and the pagination contract of PRD 2.3).

Two passes, because the band order inside schema is exact: every required
field / type / range fault reports ERR_VALIDATION, and only once no such fault
remains does an out-of-set enum value report ERR_INVALID_ENUM_VALUE.
"""
from flask import request

import clock
from errors import ApiError

CATEGORIES = ["DINING", "TRAVEL", "WELLNESS", "ELECTRONICS", "CHILDCARE",
              "EDUCATION", "HOME_SERVICES"]
REGIONS = ["CA", "TX", "NY", "WA", "IL"]
EMPLOYMENT_STATUSES = ["ACTIVE", "LEAVE", "TERMINATED"]

_MISSING = object()


def json_body():
    """The parsed request body. A malformed or absent body is an empty object."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def _bad(name, why):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (name, why))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def fields(body, specs):
    """Validate a declarative field list and return the coerced values."""
    out = {}
    pending_enums = []
    for spec in specs:
        name = spec["name"]
        kind = spec.get("type", "str")
        required = spec.get("required", False)
        raw = body.get(name, _MISSING)
        if raw is _MISSING or raw is None:
            if required:
                _bad(name, "is required")
            out[name] = spec.get("default", None)
            continue
        if kind == "str":
            if not isinstance(raw, str):
                _bad(name, "must be a string")
            if spec.get("allow_blank"):
                value = raw
            else:
                if raw.strip() == "":
                    _bad(name, "must not be blank")
                value = raw
            lo = spec.get("min_len")
            hi = spec.get("max_len")
            if lo is not None and len(value) < lo:
                _bad(name, "is shorter than %d characters" % lo)
            if hi is not None and len(value) > hi:
                _bad(name, "is longer than %d characters" % hi)
            if spec.get("contains") and spec["contains"] not in value:
                _bad(name, "must contain '%s'" % spec["contains"])
            out[name] = value
        elif kind == "int":
            if not _is_int(raw):
                _bad(name, "must be an integer")
            lo = spec.get("min")
            hi = spec.get("max")
            if lo is not None and raw < lo:
                _bad(name, "must be at least %d" % lo)
            if hi is not None and raw > hi:
                _bad(name, "must be at most %d" % hi)
            out[name] = raw
        elif kind == "bool":
            if not isinstance(raw, bool):
                _bad(name, "must be a boolean")
            out[name] = raw
        elif kind == "datetime":
            if not isinstance(raw, str):
                _bad(name, "must be an ISO 8601 string")
            parsed = clock.parse_iso(raw)
            if parsed is None:
                _bad(name, "must be a valid ISO 8601 instant")
            out[name] = parsed
        elif kind == "enum":
            if not isinstance(raw, str) or raw.strip() == "":
                _bad(name, "must be a non-empty string")
            pending_enums.append((name, [raw], spec["values"]))
            out[name] = raw
        elif kind == "enum_list":
            if not isinstance(raw, list):
                _bad(name, "must be an array")
            lo = spec.get("min_len")
            hi = spec.get("max_len")
            if lo is not None and len(raw) < lo:
                _bad(name, "must hold at least %d entries" % lo)
            if hi is not None and len(raw) > hi:
                _bad(name, "must hold at most %d entries" % hi)
            for element in raw:
                if not isinstance(element, str) or element.strip() == "":
                    _bad(name, "must hold non-empty strings")
            if spec.get("unique") and len(set(raw)) != len(raw):
                _bad(name, "must not repeat an entry")
            pending_enums.append((name, list(raw), spec["values"]))
            out[name] = list(raw)
        elif kind == "obj_list":
            if not isinstance(raw, list):
                _bad(name, "must be an array")
            lo = spec.get("min_len")
            hi = spec.get("max_len")
            if lo is not None and len(raw) < lo:
                _bad(name, "must hold at least %d entries" % lo)
            if hi is not None and len(raw) > hi:
                _bad(name, "must hold at most %d entries" % hi)
            for element in raw:
                if not isinstance(element, dict):
                    _bad(name, "must hold JSON objects")
            out[name] = raw
        else:
            out[name] = raw
    for name, values, allowed in pending_enums:
        for value in values:
            if value not in allowed:
                raise ApiError(
                    "ERR_INVALID_ENUM_VALUE",
                    "Field '%s' carries the unsupported value '%s'." % (name, value),
                )
    return out


def window(start, end):
    """PRD: an interval whose end is at or before its start is refused."""
    if start is not None and end is not None and end <= start:
        raise ApiError("ERR_INVALID_WINDOW", "The interval end must be after its start.")


def pagination():
    """PRD 2.3: limit defaults to 10 in 1..100, offset defaults to 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        limit = _pag_int(raw)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        offset = _pag_int(raw)
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must not be negative.")
    return limit, offset


def _pag_int(raw):
    if raw is None or raw.strip() == "":
        raise ApiError("ERR_INVALID_PAGINATION", "Pagination values must be integers.")
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if digits == "" or not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION", "Pagination values must be integers.")
    value = int(digits)
    return -value if negative else value


def query_instant(name):
    """A required ISO 8601 query parameter (report period bounds)."""
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' is required." % name)
    parsed = clock.parse_iso(raw)
    if parsed is None:
        raise ApiError(
            "ERR_VALIDATION",
            "Query parameter '%s' must be a valid ISO 8601 instant." % name,
        )
    return parsed


def query_flag(name):
    """A tri-state boolean filter: None when absent."""
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None
