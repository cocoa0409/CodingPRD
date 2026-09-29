"""Ladder band 8 of PRD §2.8: request-schema validation.

Field types, enum membership, string lengths and character sets, numeric
ranges and the required-field set all funnel into ERR_INVALID_REQUEST (400).
"""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from clockcal import parse_instant
from errors import fail

CUSTOMER_CODE_RE = re.compile(r"^[A-Z0-9-]{1,16}$")
AGREEMENT_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def body():
    """The parsed JSON object, or {} when the caller sent nothing."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def present(data, name):
    return name in data and data[name] is not None


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------

def opt_str(data, name, minlen=1, maxlen=None, pattern=None, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if minlen is not None and len(value) < minlen:
        _bad(name, "must be at least %d characters" % minlen)
    if maxlen is not None and len(value) > maxlen:
        _bad(name, "must be at most %d characters" % maxlen)
    if pattern is not None and not pattern.match(value):
        _bad(name, "does not match the required format")
    return value


def req_str(data, name, minlen=1, maxlen=None, pattern=None):
    if not present(data, name):
        _bad(name, "is required")
    return opt_str(data, name, minlen, maxlen, pattern)


# --------------------------------------------------------------------------
# integers
# --------------------------------------------------------------------------

def opt_int(data, name, lo=None, hi=None, multiple_of=None, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if lo is not None and value < lo:
        _bad(name, "must be >= %d" % lo)
    if hi is not None and value > hi:
        _bad(name, "must be <= %d" % hi)
    if multiple_of is not None and value % multiple_of != 0:
        _bad(name, "must be a multiple of %d" % multiple_of)
    return value


def req_int(data, name, lo=None, hi=None, multiple_of=None):
    if not present(data, name):
        _bad(name, "is required")
    return opt_int(data, name, lo, hi, multiple_of)


# --------------------------------------------------------------------------
# booleans, enums, numbers, instants
# --------------------------------------------------------------------------

def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def req_bool(data, name):
    if not present(data, name):
        _bad(name, "is required")
    return opt_bool(data, name)


def opt_enum(data, name, members, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in members:
        _bad(name, "must be one of %s" % ", ".join(sorted(members)))
    return value


def req_enum(data, name, members):
    if not present(data, name):
        _bad(name, "is required")
    return opt_enum(data, name, members)


def opt_number(data, name, default=None, lo=None, hi=None,
               lo_exclusive=False, max_decimals=None):
    if not present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        _bad(name, "must be a number")
    if lo is not None:
        if lo_exclusive and dec <= Decimal(str(lo)):
            _bad(name, "must be greater than %s" % lo)
        if not lo_exclusive and dec < Decimal(str(lo)):
            _bad(name, "must be >= %s" % lo)
    if hi is not None and dec > Decimal(str(hi)):
        _bad(name, "must be <= %s" % hi)
    if max_decimals is not None:
        exponent = dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_decimals:
            _bad(name, "must carry at most %d decimal places" % max_decimals)
    return value


def req_number(data, name, lo=None, hi=None, lo_exclusive=False,
               max_decimals=None):
    if not present(data, name):
        _bad(name, "is required")
    return opt_number(data, name, None, lo, hi, lo_exclusive, max_decimals)


def opt_instant(data, name, default=None):
    """Every instant accepted in a request body must carry an explicit Z UTC
    designator (PRD §2.4)."""
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 UTC instant string")
    parsed = parse_instant(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 instant with an explicit Z designator")
    return parsed


def req_instant(data, name):
    if not present(data, name):
        _bad(name, "is required")
    return opt_instant(data, name)


def opt_ref(data, name):
    """A foreign reference read for ladder band 7.  Non-string values fall
    through to band 8."""
    if not present(data, name):
        return None
    value = data[name]
    if not isinstance(value, str):
        _bad(name, "must be a string identifier")
    return value


def req_ref(data, name):
    if not present(data, name):
        _bad(name, "is required")
    return opt_ref(data, name)


def unique_or_fail(collection, field, value):
    for row in collection.values():
        if row.get(field) == value:
            _bad(field, "must be unique across existing records")
