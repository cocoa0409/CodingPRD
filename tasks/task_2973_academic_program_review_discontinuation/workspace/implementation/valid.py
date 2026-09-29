"""Check 9 of PRD 2.10: request bodies conform to the endpoint input schema.

Every failure in this module raises ERR_VALIDATION (HTTP 422).
"""

import re
from decimal import Decimal, InvalidOperation

from errors import ApiError
from store import parse_instant

PROGRAM_CODE_RE = re.compile(r"^[A-Z0-9-]{4,12}$")


def fail(message):
    raise ApiError("ERR_VALIDATION", message)


def _present(body, key):
    return isinstance(body, dict) and key in body and body[key] is not None


def req_present(body, key):
    if not _present(body, key):
        fail("%s is required." % key)


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------

def opt_str(body, key, minlen, maxlen, upper=False, pattern=None, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        fail("%s must be a string." % key)
    if len(value) < minlen or len(value) > maxlen:
        fail("%s must be %d to %d characters." % (key, minlen, maxlen))
    if upper and value != value.upper():
        fail("%s must be uppercase." % key)
    if pattern is not None and not pattern.match(value):
        fail("%s has an invalid format." % key)
    return value


def req_str(body, key, minlen, maxlen, upper=False, pattern=None):
    req_present(body, key)
    return opt_str(body, key, minlen, maxlen, upper=upper, pattern=pattern)


def req_nonblank_str(body, key, minlen, maxlen):
    value = req_str(body, key, minlen, maxlen)
    if value.strip() == "":
        fail("%s must not be blank." % key)
    return value


# --------------------------------------------------------------------------
# integers
# --------------------------------------------------------------------------

def opt_int(body, key, minimum=None, maximum=None, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("%s must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("%s must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("%s must be at most %d." % (key, maximum))
    return value


def req_int(body, key, minimum=None, maximum=None):
    req_present(body, key)
    return opt_int(body, key, minimum=minimum, maximum=maximum)


def req_term_index(body, key):
    return req_int(body, key, minimum=1)


def opt_term_index(body, key):
    return opt_int(body, key, minimum=1)


# --------------------------------------------------------------------------
# booleans, enums, instants, decimals
# --------------------------------------------------------------------------

def req_bool(body, key):
    req_present(body, key)
    value = body[key]
    if not isinstance(value, bool):
        fail("%s must be a boolean." % key)
    return value


def req_enum(body, key, allowed):
    req_present(body, key)
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        fail("%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(body, key, allowed, default=None):
    if not _present(body, key):
        return default
    return req_enum(body, key, allowed)


def req_instant(body, key):
    req_present(body, key)
    parsed = parse_instant(body[key])
    if parsed is None:
        fail("%s must be an ISO 8601 UTC instant." % key)
    return parsed


def req_decimal(body, key, low, high, low_exclusive=False, places=2):
    """A decimal carried to at most `places` decimal places."""
    req_present(body, key)
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail("%s must be a number." % key)
    if isinstance(value, str):
        fail("%s must be a number." % key)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("%s must be a number." % key)
    if number != number:  # NaN guard
        fail("%s must be a number." % key)
    exponent = number.as_tuple().exponent
    if not isinstance(exponent, int) or -exponent > places:
        fail("%s must carry at most %d decimal places." % (key, places))
    if low_exclusive:
        if number <= low:
            fail("%s must be above %s." % (key, low))
    elif number < low:
        fail("%s must be at least %s." % (key, low))
    if number > high:
        fail("%s must be at most %s." % (key, high))
    return number


# --------------------------------------------------------------------------
# arrays of codes
# --------------------------------------------------------------------------

def code_array(body, key, minlen, maxlen, allow_empty=True, required=False,
               default=None, pattern=None, upper=True):
    if not _present(body, key):
        if required:
            fail("%s is required." % key)
        return [] if default is None else list(default)
    value = body[key]
    if not isinstance(value, list):
        fail("%s must be an array." % key)
    if not allow_empty and len(value) == 0:
        fail("%s must not be empty." % key)
    out = []
    for item in value:
        if not isinstance(item, str):
            fail("%s must contain only strings." % key)
        if len(item) < minlen or len(item) > maxlen:
            fail("%s entries must be %d to %d characters." % (key, minlen, maxlen))
        if upper and item != item.upper():
            fail("%s entries must be uppercase." % key)
        if pattern is not None and not pattern.match(item):
            fail("%s entries have an invalid format." % key)
        out.append(item)
    return out


def text_array(body, key, minlen, maxlen, default=None):
    if not _present(body, key):
        return [] if default is None else list(default)
    value = body[key]
    if not isinstance(value, list):
        fail("%s must be an array." % key)
    out = []
    for item in value:
        if not isinstance(item, str):
            fail("%s must contain only strings." % key)
        if len(item) < minlen or len(item) > maxlen:
            fail("%s entries must be %d to %d characters." % (key, minlen, maxlen))
        out.append(item)
    return out


def forbid_present(body, key, message=None):
    if _present(body, key):
        fail(message or ("%s is not accepted here." % key))
