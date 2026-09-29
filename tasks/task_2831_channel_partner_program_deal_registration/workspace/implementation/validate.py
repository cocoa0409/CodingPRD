"""Request-shape validation (PRD 2.8 priority 5). Every failure is 422."""
from decimal import Decimal

from flask import request

from errors import ApiError
from store import parse_instant

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        raw = request.get_data(cache=True, as_text=True)
        if raw is not None and raw.strip() != "":
            _bad("The request body must be a JSON object.")
        return {}
    if not isinstance(payload, dict):
        _bad("The request body must be a JSON object.")
    return payload


def present(data, name):
    return name in data and data[name] is not None


def req_string(data, name, max_len=None, non_empty=True):
    if not present(data, name):
        _bad("'%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        _bad("'%s' must be a string." % name)
    if non_empty and value.strip() == "":
        _bad("'%s' must not be empty." % name)
    if max_len is not None and len(value) > max_len:
        _bad("'%s' must be at most %d characters." % (name, max_len))
    return value


def opt_string(data, name, max_len=None, non_empty=True, default=None):
    if not present(data, name):
        return default
    return req_string(data, name, max_len=max_len, non_empty=non_empty)


def req_enum(data, name, allowed):
    if not present(data, name):
        _bad("'%s' is required." % name)
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        _bad("'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, allowed)


def _as_int(name, value):
    if isinstance(value, bool):
        _bad("'%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            _bad("'%s' must be an integer number of cents." % name)
        return int(value)
    _bad("'%s' must be an integer." % name)


def req_int(data, name, minimum=0, maximum=None):
    if not present(data, name):
        _bad("'%s' is required." % name)
    value = _as_int(name, data[name])
    if minimum is not None and value < minimum:
        _bad("'%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("'%s' must be at most %d." % (name, maximum))
    return value


def opt_int(data, name, minimum=0, maximum=None, default=None):
    if not present(data, name):
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def _as_decimal(name, value):
    if isinstance(value, bool):
        _bad("'%s' must be a number." % name)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        _bad("'%s' must be a number." % name)
    _bad("'%s' must be a number." % name)


def req_fraction(data, name, low=Decimal("0"), high=Decimal("1"),
                 low_exclusive=False, high_exclusive=False):
    if not present(data, name):
        _bad("'%s' is required." % name)
    value = _as_decimal(name, data[name])
    if low_exclusive:
        if value <= low:
            _bad("'%s' must be greater than %s." % (name, low))
    elif value < low:
        _bad("'%s' must be at least %s." % (name, low))
    if high_exclusive:
        if value >= high:
            _bad("'%s' must be less than %s." % (name, high))
    elif value > high:
        _bad("'%s' must be at most %s." % (name, high))
    return value


def opt_fraction(data, name, **kwargs):
    if not present(data, name):
        return None
    return req_fraction(data, name, **kwargs)


def req_instant(data, name):
    if not present(data, name):
        _bad("'%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        _bad("'%s' must be an ISO 8601 UTC instant." % name)
    parsed = parse_instant(value)
    if parsed is None:
        _bad("'%s' must be an ISO 8601 UTC instant." % name)
    return parsed


def opt_instant(data, name):
    if not present(data, name):
        return None
    return req_instant(data, name)


def req_bool(data, name):
    if not present(data, name):
        _bad("'%s' is required." % name)
    if not isinstance(data[name], bool):
        _bad("'%s' must be a boolean." % name)
    return data[name]


def interval(start, end, start_name, end_name):
    """PRD 2.6: every declared interval must have end strictly after start."""
    if end <= start:
        _bad("'%s' must be strictly after '%s'." % (end_name, start_name))


def fk_candidate(data, name):
    """A body foreign key is resolved only when it is shape-plausible.

    PRD 2.8 puts existence (3) above request shape (5), so a present but
    unresolvable id must 404; an absent or structurally unusable one falls
    through to the shape check that will reject it with 422.
    """
    if not present(data, name):
        return None
    value = data[name]
    if not isinstance(value, str) or value.strip() == "":
        return None
    return value


def bool_query(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    return None
