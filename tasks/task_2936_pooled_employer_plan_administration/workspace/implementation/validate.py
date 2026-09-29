"""Priority 7 of the ladder: request shape.

Required fields present, correct types, declared enum members, declared integer
ranges, ISO-8601 date and datetime formats and pagination bounds -- all
reported as ERR_VALIDATION. Unknown fields in a body are ignored rather than
rejected (PRD 2.11).
"""

from decimal import Decimal, InvalidOperation

from flask import request

import clockcal
from errors import fail

_MISSING = object()


def body():
    """Parse the JSON body. Never called before the caller is identified."""
    if not request.data:
        return {}
    payload = request.get_json(force=True, silent=True)
    if payload is None:
        fail("ERR_VALIDATION", "The request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_VALIDATION", "The request body must be a JSON object.")
    return payload


def _bad(name, why):
    fail("ERR_VALIDATION", "`%s` %s." % (name, why))


def present(b, name):
    return name in b and b[name] is not None


# --------------------------------------------------------------------------
# Strings
# --------------------------------------------------------------------------


def req_str(b, name, min_len=1, max_len=None):
    if name not in b or b[name] is None:
        _bad(name, "is required")
    value = b[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if len(value) < min_len:
        _bad(name, "must be at least %d character(s)" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "may not exceed %d characters" % max_len)
    return value


def opt_str(b, name, min_len=1, max_len=None, default=None):
    if name not in b or b[name] is None:
        return default
    return req_str(b, name, min_len, max_len)


def req_digits(b, name, count):
    value = req_str(b, name, 1, None)
    if len(value) != count or not value.isdigit():
        _bad(name, "must be exactly %d digits" % count)
    return value


# --------------------------------------------------------------------------
# Enums, integers, numbers, booleans
# --------------------------------------------------------------------------


def req_enum(b, name, members):
    value = req_str(b, name, 1, None)
    if value not in members:
        _bad(name, "must be one of %s" % ", ".join(members))
    return value


def opt_enum(b, name, members, default=None):
    if name not in b or b[name] is None:
        return default
    return req_enum(b, name, members)


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    return value


def req_int(b, name, minimum=None, maximum=None):
    if name not in b or b[name] is None:
        _bad(name, "is required")
    value = _as_int(name, b[name])
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "may not exceed %d" % maximum)
    return value


def opt_int(b, name, minimum=None, maximum=None, default=None):
    if name not in b or b[name] is None:
        return default
    return req_int(b, name, minimum, maximum)


def _as_decimal(name, value):
    if isinstance(value, bool):
        _bad(name, "must be a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    _bad(name, "must be a number")


def req_num(b, name, minimum=None, maximum=None, places=2):
    if name not in b or b[name] is None:
        _bad(name, "is required")
    value = _as_decimal(name, b[name])
    if minimum is not None and value < Decimal(str(minimum)):
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > Decimal(str(maximum)):
        _bad(name, "may not exceed %s" % maximum)
    return quantize(value, places)


def opt_num(b, name, minimum=None, maximum=None, places=2, default=None):
    if name not in b or b[name] is None:
        return default
    return req_num(b, name, minimum, maximum, places)


def quantize(value, places=2):
    from decimal import ROUND_HALF_UP

    exp = Decimal(1).scaleb(-places)
    try:
        return value.quantize(exp, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        fail("ERR_VALIDATION", "A numeric value is out of range.")


# --------------------------------------------------------------------------
# Calendar dates and instants (PRD 2.5). A value of the wrong shape is
# rejected with ERR_VALIDATION.
# --------------------------------------------------------------------------


def req_date(b, name):
    if name not in b or b[name] is None:
        _bad(name, "is required")
    value = b[name]
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    parsed = clockcal.parse_date(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    return parsed


def opt_date(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    return req_date(b, name)


def req_instant(b, name):
    if name not in b or b[name] is None:
        _bad(name, "is required")
    value = b[name]
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 UTC instant")
    parsed = clockcal.parse_instant(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC instant")
    return parsed


# --------------------------------------------------------------------------
# Body foreign keys (PRD 2.8)
#
# A body foreign key is resolved at priority 6 when it arrives as a string; if
# it is absent altogether or is not a string it is a shape defect and is left
# for priority 7 to report as ERR_VALIDATION.
# --------------------------------------------------------------------------


def fk_candidate(b, name):
    """The string value of a body foreign key, or None when it is a shape defect."""
    value = b.get(name, None)
    if isinstance(value, str):
        return value
    return None


def resolve_fk(b, name, collection, not_found_error, required=True):
    """Resolve a body foreign key, raising the entity's own not-found error."""
    import store

    candidate = fk_candidate(b, name)
    if candidate is None:
        if required:
            return None  # shape defect: reported later as ERR_VALIDATION
        if name in b and b[name] is not None:
            return None
        return None
    row = store.get(collection, candidate)
    if row is None:
        fail(not_found_error)
    return row


def require_fk_shape(b, name):
    """Priority 7 half of the foreign-key contract."""
    if name not in b or b[name] is None:
        _bad(name, "is required")
    if not isinstance(b[name], str):
        _bad(name, "must be a string identifier")
    return b[name]
