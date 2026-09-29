"""Body field validation.  Every failure here is ERR_VALIDATION (PRD ladder rung 5)."""

from decimal import Decimal, InvalidOperation

from core import fail, parse_date, parse_instant

_MISSING = object()


def _present(body, name):
    if name not in body:
        return False
    return body[name] is not None


def req_string(body, name, min_len=1, max_len=None, non_blank=True):
    if not _present(body, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % name)
    return _check_string(name, value, min_len, max_len, non_blank)


def opt_string(body, name, min_len=1, max_len=None, non_blank=True, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % name)
    return _check_string(name, value, min_len, max_len, non_blank)


def _check_string(name, value, min_len, max_len, non_blank):
    if min_len is not None and len(value) < min_len:
        fail("ERR_VALIDATION", "%s is too short" % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "%s is too long" % name)
    if non_blank and value.strip() == "":
        fail("ERR_VALIDATION", "%s must not be blank" % name)
    return value


def req_enum(body, name, domain):
    if not _present(body, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = body[name]
    if not isinstance(value, str) or value not in domain:
        fail("ERR_VALIDATION", "%s must be one of %s" % (name, ", ".join(domain)))
    return value


def opt_enum(body, name, domain, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in domain:
        fail("ERR_VALIDATION", "%s must be one of %s" % (name, ", ".join(domain)))
    return value


def _as_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "%s is below the permitted minimum" % name)
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "%s is above the permitted maximum" % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    return _as_int(name, body[name], minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    return _as_int(name, body[name], minimum, maximum)


def req_bool(body, name):
    if not _present(body, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "%s must be a boolean" % name)
    return value


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "%s must be a boolean" % name)
    return value


def _as_decimal(name, value, minimum, maximum, exclusive_min, places):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_VALIDATION", "%s must be a number" % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_VALIDATION", "%s must be a number" % name)
    if dec != dec.to_integral_value() and -dec.as_tuple().exponent > places:
        fail("ERR_VALIDATION", "%s allows at most %d decimal places" % (name, places))
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        fail("ERR_VALIDATION", "%s must be greater than %s" % (name, exclusive_min))
    if minimum is not None and dec < Decimal(str(minimum)):
        fail("ERR_VALIDATION", "%s is below the permitted minimum" % name)
    if maximum is not None and dec > Decimal(str(maximum)):
        fail("ERR_VALIDATION", "%s is above the permitted maximum" % name)
    return dec


def req_decimal(body, name, minimum=None, maximum=None, exclusive_min=None, places=2):
    if not _present(body, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    return _as_decimal(name, body[name], minimum, maximum, exclusive_min, places)


def opt_decimal(body, name, minimum=None, maximum=None, exclusive_min=None,
                places=2, default=None):
    if not _present(body, name):
        return default
    return _as_decimal(name, body[name], minimum, maximum, exclusive_min, places)


def req_date(body, name):
    if not _present(body, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = parse_date(body[name])
    if value is None:
        fail("ERR_VALIDATION", "%s must be a YYYY-MM-DD calendar date" % name)
    return value


def opt_date(body, name, default=None):
    if not _present(body, name):
        return default
    value = parse_date(body[name])
    if value is None:
        fail("ERR_VALIDATION", "%s must be a YYYY-MM-DD calendar date" % name)
    return value


def req_instant(body, name):
    if not _present(body, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = parse_instant(body[name])
    if value is None:
        fail("ERR_VALIDATION", "%s must be an ISO 8601 UTC instant" % name)
    return value


def opt_instant(body, name, default=None):
    if not _present(body, name):
        return default
    value = parse_instant(body[name])
    if value is None:
        fail("ERR_VALIDATION", "%s must be an ISO 8601 UTC instant" % name)
    return value


def req_enum_list(body, name, domain, min_len=1, max_len=None, distinct=True):
    if not _present(body, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = body[name]
    if not isinstance(value, list):
        fail("ERR_VALIDATION", "%s must be an array" % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_VALIDATION", "%s must hold at least %d entries" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "%s may hold at most %d entries" % (name, max_len))
    for entry in value:
        if not isinstance(entry, str) or entry not in domain:
            fail("ERR_VALIDATION", "%s entries must be one of %s" % (name, ", ".join(domain)))
    if distinct and len(set(value)) != len(value):
        fail("ERR_VALIDATION", "%s entries must be distinct" % name)
    return list(value)


def req_id(body, name):
    """A foreign key reference supplied in a request body."""
    if not _present(body, name):
        fail("ERR_VALIDATION", "%s is required" % name)
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_VALIDATION", "%s must be a non-empty string identifier" % name)
    return value


def peek_id(body, name):
    """Best-effort read of a body foreign key for the ownership-scope rung."""
    value = body.get(name)
    if isinstance(value, str) and value.strip() != "":
        return value
    return None
