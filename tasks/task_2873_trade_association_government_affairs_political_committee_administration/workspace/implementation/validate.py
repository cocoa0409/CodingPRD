"""Request-body shape validation (PRD 2.11 rank 6 -> ERR_INVALID_REQUEST / 400)."""
import re
from decimal import Decimal, InvalidOperation

from constants import round_half_up
from core import fail, parse_date

_MISSING = object()
_ABSENT = object()
DISTRICT_RE = re.compile(r"^[A-Z]{2,}-[0-9]+$")


def _bad(name, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def _fetch(payload, name, required):
    """Missing or explicit-null: required -> 400, optional -> _ABSENT."""
    if name not in payload or payload[name] is None:
        if required:
            _bad(name, "is required")
        return _ABSENT
    return payload[name]


def _fallback(default):
    return None if default is _MISSING else default


def get_str(payload, name, required=True, default=_MISSING, max_len=None, min_len=1, allow_blank=False):
    value = _fetch(payload, name, required)
    if value is _ABSENT:
        return _fallback(default)
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_blank and len(value.strip()) < min_len:
        _bad(name, "must be a non-empty string")
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def get_enum(payload, name, allowed, required=True, default=_MISSING):
    value = _fetch(payload, name, required)
    if value is _ABSENT:
        return _fallback(default)
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def get_int(payload, name, required=True, default=_MISSING, minimum=None, maximum=None):
    value = _fetch(payload, name, required)
    if value is _ABSENT:
        return _fallback(default)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %d" % maximum)
    return value


def get_bool(payload, name, required=True, default=_MISSING):
    value = _fetch(payload, name, required)
    if value is _ABSENT:
        return _fallback(default)
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def _decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(name, "must be a number")


def get_pct(payload, name, required=True, default=_MISSING):
    """Percentage in 0.00..100.00 inclusive, held to two decimals (PRD 2.6)."""
    value = _fetch(payload, name, required)
    if value is _ABSENT:
        return _fallback(default)
    dec = _decimal(name, value)
    if dec < 0 or dec > 100:
        _bad(name, "must be between 0.00 and 100.00 inclusive")
    return round_half_up(dec, 2)


def get_hours(payload, name, required=True, default=_MISSING):
    """Hours: >= 0, <= 999.999, at most three decimals (PRD 3.5)."""
    value = _fetch(payload, name, required)
    if value is _ABSENT:
        return _fallback(default)
    dec = _decimal(name, value)
    if dec < 0 or dec > Decimal("999.999"):
        _bad(name, "must be between 0 and 999.999")
    if -dec.as_tuple().exponent > 3:
        _bad(name, "must carry at most three decimals")
    return dec


def get_date(payload, name, required=True, default=_MISSING):
    """Strict ISO YYYY-MM-DD calendar date -> datetime.date."""
    value = _fetch(payload, name, required)
    if value is _ABSENT:
        return _fallback(default)
    if not isinstance(value, str):
        _bad(name, "must be an ISO YYYY-MM-DD date string")
    parsed = parse_date(value)
    if parsed is None:
        _bad(name, "must be an ISO YYYY-MM-DD calendar date")
    return parsed


def get_district(payload, name, required=True):
    value = get_str(payload, name, required=required, max_len=50)
    if value is None:
        return None
    if value != value.upper() or not DISTRICT_RE.match(value):
        _bad(name, "must be an uppercase '<STATE>-<NUMBER>' district label")
    return value
