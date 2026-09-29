"""Body / query-string validation (PRD section 2.11 rung 5 -> ERR_INVALID_REQUEST)."""
import re

from flask import request

import clock
import response
from errors import ApiError

_MISSING = object()


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    """The JSON request body as a dict.  A malformed or non-object body is invalid."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        _bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def _present(data, key, optional, default):
    if key not in data or data[key] is _MISSING:
        if optional:
            return False, default
        _bad("Required field '%s' is missing." % key)
    return True, None


def opt_string(data, key, **kw):
    kw["optional"] = True
    return field_string(data, key, **kw)


def field_string(data, key, min_len=1, max_len=None, non_blank=True,
                 pattern=None, optional=False, default=None, nullable=False,
                 pattern_desc=None):
    ok, fallback = _present(data, key, optional, default)
    if not ok:
        return fallback
    value = data[key]
    if value is None:
        if nullable or optional:
            return None
        _bad("Field '%s' must be a string." % key)
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        _bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("Field '%s' must be at most %d characters." % (key, max_len))
    if non_blank and value.strip() == "":
        _bad("Field '%s' must not be blank." % key)
    if pattern is not None and not re.match(pattern, value):
        _bad("Field '%s' %s." % (key, pattern_desc or "has an invalid format"))
    return value


def field_text(data, key, optional=False, default=None, nullable=False):
    """Free-text field with no declared length constraint: type-checked only."""
    return field_string(data, key, min_len=None, max_len=None, non_blank=False,
                        optional=optional, default=default, nullable=nullable)


def field_int(data, key, minimum=None, maximum=None, optional=False, default=None,
              nullable=False):
    ok, fallback = _present(data, key, optional, default)
    if not ok:
        return fallback
    value = data[key]
    if value is None:
        if nullable or optional:
            return None
        _bad("Field '%s' must be an integer." % key)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %d." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %d." % (key, maximum))
    return value


def field_number(data, key, minimum=None, maximum=None, optional=False, default=None,
                 nullable=False):
    ok, fallback = _present(data, key, optional, default)
    if not ok:
        return fallback
    value = data[key]
    if value is None:
        if nullable or optional:
            return None
        _bad("Field '%s' must be a number." % key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % key)
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        _bad("Field '%s' must be a finite number." % key)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def field_bool(data, key, optional=False, default=None):
    ok, fallback = _present(data, key, optional, default)
    if not ok:
        return fallback
    value = data[key]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % key)
    return value


def field_enum(data, key, allowed, optional=False, default=None, nullable=False):
    ok, fallback = _present(data, key, optional, default)
    if not ok:
        return fallback
    value = data[key]
    if value is None:
        if nullable or optional:
            return None
        _bad("Field '%s' is required." % key)
    if not isinstance(value, str) or value not in allowed:
        _bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def field_instant(data, key, optional=False, default=None, nullable=False):
    """An ISO-8601 instant.  Returns an aware UTC datetime."""
    ok, fallback = _present(data, key, optional, default)
    if not ok:
        return fallback
    value = data[key]
    if value is None:
        if nullable or optional:
            return None
        _bad("Field '%s' must be an ISO-8601 timestamp." % key)
    parsed = clock.parse_instant(value)
    if parsed is None:
        _bad("Field '%s' must be a valid ISO-8601 timestamp." % key)
    return parsed


def field_id_list(data, key, optional=False, default=None):
    ok, fallback = _present(data, key, optional, default)
    if not ok:
        return list(fallback) if fallback is not None else []
    value = data[key]
    if value is None:
        return []
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % key)
    out = []
    for item in value:
        if not isinstance(item, str) or item == "":
            _bad("Field '%s' must contain non-empty string identifiers." % key)
        out.append(item)
    return out


def field_enum_list(data, key, allowed, optional=False, default=None):
    ok, fallback = _present(data, key, optional, default)
    if not ok:
        return list(fallback) if fallback is not None else []
    value = data[key]
    if value is None:
        return []
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % key)
    out = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _bad("Field '%s' entries must be one of %s." % (key, ", ".join(sorted(allowed))))
        out.append(item)
    return out


def field_date_list(data, key, optional=False, default=None):
    ok, fallback = _present(data, key, optional, default)
    if not ok:
        return list(fallback) if fallback is not None else []
    value = data[key]
    if value is None:
        return []
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % key)
    out = []
    for item in value:
        if clock.parse_date(item) is None:
            _bad("Field '%s' entries must be YYYY-MM-DD calendar dates." % key)
        out.append(item)
    return out


def require_end_after_start(start, end, start_key, end_key):
    if start is None or end is None:
        return
    if not end > start:
        _bad("Field '%s' must be strictly after '%s'." % (end_key, start_key))


# --------------------------------------------------------------------------
# Pagination + filters
# --------------------------------------------------------------------------
def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not re.match(r"^[+-]?\d+$", text):
        _bad("Query parameter '%s' must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        _bad("Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", response.PAGINATION_LIMIT_DEFAULT,
                       response.PAGINATION_LIMIT_MIN, response.PAGINATION_LIMIT_MAX)
    offset = _query_int("offset", response.PAGINATION_OFFSET_DEFAULT,
                        response.PAGINATION_OFFSET_MIN, None)
    return limit, offset


def apply_filters(rows, filter_fields):
    """Plain conjunctive equality matching on the named fields."""
    out = rows
    for name in filter_fields:
        raw = request.args.get(name)
        if raw is None:
            continue
        out = [r for r in out if r.get(name) == raw]
    return out
