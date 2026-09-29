"""Payload shape, pagination bounds and interval ordering -- PRD 2.3, 2.11.

Precedence item 3 (payload shape) covers a missing required field, a wrong JSON
type, an undeclared enum member, a number outside its declared range, a country
code that is not exactly two uppercase letters A-Z, and a datetime that is not a
valid ISO-8601 UTC instant.  Unknown extra fields are ignored rather than
rejected.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from util import is_country_code, parse_instant, round2, to_decimal

_MISSING = object()

# PRD 2.3 pagination defaults and bounds.
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _bad():
    raise ApiError("ERR_INVALID_REQUEST")


def body():
    """Parse the JSON request body; an absent body reads as an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(force=True, silent=True)
    if parsed is None:
        _bad()
    if not isinstance(parsed, dict):
        _bad()
    return parsed


def present(data, name):
    return name in data and data[name] is not None


def _get(data, name, required):
    if name not in data:
        if required:
            _bad()
        return _MISSING
    return data[name]


def string_field(data, name, required=True, min_len=None, max_len=None,
                 non_blank=False, default=None, nullable=False):
    raw = _get(data, name, required)
    if raw is _MISSING:
        return default
    if raw is None:
        if nullable or not required:
            return None
        _bad()
    if not isinstance(raw, str):
        _bad()
    if min_len is not None and len(raw) < min_len:
        _bad()
    if max_len is not None and len(raw) > max_len:
        _bad()
    if non_blank and raw.strip() == "":
        _bad()
    return raw


def enum_field(data, name, allowed, required=True, default=None):
    raw = _get(data, name, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, str) or raw not in allowed:
        _bad()
    return raw


def int_field(data, name, required=True, minimum=None, maximum=None, default=None):
    raw = _get(data, name, required)
    if raw is _MISSING:
        return default
    if raw is None:
        _bad()
    if isinstance(raw, bool) or not isinstance(raw, int):
        _bad()
    if minimum is not None and raw < minimum:
        _bad()
    if maximum is not None and raw > maximum:
        _bad()
    return raw


def score_field(data, name, required=True, default=None):
    """A number in the inclusive range 0.00 to 100.00 (PRD 2.7)."""
    raw = _get(data, name, required)
    if raw is _MISSING:
        return default
    if raw is None:
        _bad()
    if isinstance(raw, bool) or not isinstance(raw, (int, float, Decimal)):
        _bad()
    try:
        value = to_decimal(raw)
    except (ValueError, InvalidOperation):
        _bad()
    if value < Decimal("0") or value > Decimal("100"):
        _bad()
    return round2(value)


def instant_field(data, name, required=True, default=None, nullable=False):
    raw = _get(data, name, required)
    if raw is _MISSING:
        return default
    if raw is None:
        if nullable or not required:
            return None
        _bad()
    parsed = parse_instant(raw)
    if parsed is None:
        _bad()
    return parsed


def country_field(data, name, required=True, default=None):
    raw = _get(data, name, required)
    if raw is _MISSING:
        return default
    if raw is None:
        _bad()
    if not is_country_code(raw):
        _bad()
    return raw


def country_list_field(data, name, default=None):
    raw = _get(data, name, False)
    if raw is _MISSING or raw is None:
        return list(default or [])
    if not isinstance(raw, list):
        _bad()
    for item in raw:
        if not is_country_code(item):
            _bad()
    return list(raw)


def id_field(data, name, required=True, nullable=False, default=None):
    raw = _get(data, name, required)
    if raw is _MISSING:
        return default
    if raw is None:
        if nullable or not required:
            return None
        _bad()
    if not isinstance(raw, str) or raw.strip() == "":
        _bad()
    return raw


def require_interval(start, end):
    """PRD 2.11 item 5: every start/end pair must be strictly ordered."""
    if start is None or end is None:
        return
    if not end > start:
        raise ApiError("ERR_INTERVAL_INVALID")


def pagination():
    """PRD 2.3: limit and offset with their declared defaults and bounds."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit is None or limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset is None or offset < OFFSET_MIN:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def _as_int(text):
    stripped = text.strip()
    if stripped == "":
        return None
    negative = stripped.startswith("-")
    digits = stripped[1:] if negative or stripped.startswith("+") else stripped
    if not digits.isdigit():
        return None
    return int(stripped)


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, total, has_more
