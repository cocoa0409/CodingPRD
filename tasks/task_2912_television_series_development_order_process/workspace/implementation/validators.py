"""Request-shape validation (validation priority 9 -> ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_date, parse_instant

_MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """Return the parsed JSON object, or None when the payload is unusable.

    Returning None (rather than raising) lets higher-priority validations --
    committee/role matching, WAIVED authorisation, path existence -- run first,
    exactly as PRD 2.11 orders them.
    """
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        return None
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def require_body(body):
    if body is None or not isinstance(body, dict):
        _bad("A JSON object body is required.")
    return body


def peek(body, key):
    """Read a raw value without validating -- used by pre-existence checks."""
    if not isinstance(body, dict):
        return None
    return body.get(key)


# ---------------------------------------------------------------------------
# scalar validators
# ---------------------------------------------------------------------------

def v_string(body, key, required=True, max_len=None, default=None, allow_null=False):
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        if raw is None and allow_null:
            return None
        if required:
            _bad("%s is required." % key)
        return default
    if not isinstance(raw, str):
        _bad("%s must be a string." % key)
    if raw.strip() == "":
        _bad("%s must not be blank." % key)
    if max_len is not None and len(raw) > max_len:
        _bad("%s must be at most %d characters." % (key, max_len))
    return raw


def v_int(body, key, required=True, minimum=None, maximum=None, default=None):
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        if required:
            _bad("%s is required." % key)
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        _bad("%s must be an integer." % key)
    if minimum is not None and raw < minimum:
        _bad("%s must be at least %s." % (key, minimum))
    if maximum is not None and raw > maximum:
        _bad("%s must be at most %s." % (key, maximum))
    return raw


def v_bool(body, key, required=False, default=None):
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        if required:
            _bad("%s is required." % key)
        return default
    if not isinstance(raw, bool):
        _bad("%s must be a boolean." % key)
    return raw


def v_enum(body, key, allowed, required=True, default=None, allow_null=False):
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        if raw is None and allow_null:
            return None
        if required:
            _bad("%s is required." % key)
        return default
    if not isinstance(raw, str) or raw not in allowed:
        _bad("%s must be one of %s." % (key, ", ".join(sorted(allowed))))
    return raw


def _as_decimal(raw, key):
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        _bad("%s must be a number." % key)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        _bad("%s must be a number." % key)


def v_decimal(body, key, required=True, minimum=None, maximum=None,
              max_places=None, default=None, allow_null=False):
    """Validate a bounded decimal number and return it as a Decimal."""
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        if raw is None and allow_null:
            return None
        if required:
            _bad("%s is required." % key)
        return default
    value = _as_decimal(raw, key)
    if minimum is not None and value < Decimal(str(minimum)):
        _bad("%s must be at least %s." % (key, minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        _bad("%s must be at most %s." % (key, maximum))
    if max_places is not None:
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > max_places:
            _bad("%s must carry at most %d decimal place(s)." % (key, max_places))
    return value


def v_date(body, key, required=True, default=None):
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        if required:
            _bad("%s is required." % key)
        return default
    parsed = parse_date(raw)
    if parsed is None:
        _bad("%s must be an ISO-8601 date in YYYY-MM-DD form." % key)
    return parsed


def v_instant(body, key, required=True):
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        if required:
            _bad("%s is required." % key)
        return None
    parsed = parse_instant(raw)
    if parsed is None:
        _bad("%s must be an ISO-8601 instant." % key)
    return parsed


def v_string_array(body, key, max_entries=None, max_len=None, default=None):
    raw = body.get(key, _MISSING)
    if raw is _MISSING or raw is None:
        return list(default) if default is not None else []
    if not isinstance(raw, list):
        _bad("%s must be an array." % key)
    if max_entries is not None and len(raw) > max_entries:
        _bad("%s may hold at most %d entries." % (key, max_entries))
    for entry in raw:
        if not isinstance(entry, str) or entry.strip() == "":
            _bad("%s must hold non-blank strings." % key)
        if max_len is not None and len(entry) > max_len:
            _bad("%s entries must be at most %d characters." % (key, max_len))
    return list(raw)


def decimal_to_json(value):
    """Emit a Decimal as a JSON number without scientific notation."""
    if value is None:
        return None
    return float(value)


def number_to_json(value):
    """Echo a client-supplied number back preserving int/float-ness."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return float(value)
        return float(value)
    return value


def query_int(name, minimum=None):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit() or digits == "":
        _bad("%s must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        _bad("%s must be at least %s." % (name, minimum))
    return value
