"""Payload shape validation (rejection-ladder rule 3)."""

from common import dec, parse_date, parse_instant
from errors import ApiError

_MISSING = object()


def _fail(message):
    raise ApiError("ERR_VALIDATION", message)


def _present(payload, name):
    return name in payload and payload[name] is not None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --------------------------------------------------------------------------
# Strings
# --------------------------------------------------------------------------

def opt_str(payload, name, default=None, min_len=1, max_len=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        _fail("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        _fail("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _fail("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def req_str(payload, name, min_len=1, max_len=None):
    if not _present(payload, name):
        _fail("Field '%s' is required." % name)
    return opt_str(payload, name, min_len=min_len, max_len=max_len)


# --------------------------------------------------------------------------
# Integers
# --------------------------------------------------------------------------

def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not _is_int(value):
        _fail("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _fail("Field '%s' must be at most %d." % (name, maximum))
    return value


def req_int(payload, name, minimum=None, maximum=None):
    if not _present(payload, name):
        _fail("Field '%s' is required." % name)
    return opt_int(payload, name, minimum=minimum, maximum=maximum)


# --------------------------------------------------------------------------
# Decimal quantities (percentages)
# --------------------------------------------------------------------------

def opt_num(payload, name, default=None, minimum=None, maximum=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not _is_num(value):
        _fail("Field '%s' must be a number." % name)
    number = dec(value)
    if minimum is not None and number < dec(minimum):
        _fail("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and number > dec(maximum):
        _fail("Field '%s' must be at most %s." % (name, maximum))
    return number


def req_num(payload, name, minimum=None, maximum=None):
    if not _present(payload, name):
        _fail("Field '%s' is required." % name)
    return opt_num(payload, name, minimum=minimum, maximum=maximum)


# --------------------------------------------------------------------------
# Enumerations, dates, instants, booleans
# --------------------------------------------------------------------------

def opt_enum(payload, name, allowed, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        _fail("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_enum(payload, name, allowed):
    if not _present(payload, name):
        _fail("Field '%s' is required." % name)
    return opt_enum(payload, name, allowed)


def opt_date(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None:
        _fail("Field '%s' must be a date formatted YYYY-MM-DD." % name)
    return parsed


def req_date(payload, name):
    if not _present(payload, name):
        _fail("Field '%s' is required." % name)
    return opt_date(payload, name)


def req_instant(payload, name):
    if not _present(payload, name):
        _fail("Field '%s' is required." % name)
    parsed = parse_instant(payload[name])
    if parsed is None:
        _fail("Field '%s' must be an ISO 8601 UTC instant." % name)
    return parsed


def opt_bool(payload, name, default=False):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        _fail("Field '%s' must be a boolean." % name)
    return value
