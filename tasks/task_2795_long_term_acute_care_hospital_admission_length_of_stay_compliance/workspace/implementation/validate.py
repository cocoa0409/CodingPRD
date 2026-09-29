"""Payload shape validation (PRD 2.8 rule 1) and query parameter parsing (PRD 2.3).

Every failure here raises ERR_VALIDATION with HTTP 400.
"""

from datetime import datetime, date, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

MISSING = object()


def _fail(message):
    raise ApiError("ERR_VALIDATION", message)


def get_body():
    """Parse the JSON request body; an absent body is treated as an empty object."""
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        _fail("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        _fail("Request body must be a JSON object.")
    return parsed


def present(body, name):
    return name in body and body[name] is not None


# --------------------------------------------------------------------------- #
# scalar readers
# --------------------------------------------------------------------------- #

def req_str(body, name, min_len=1, max_len=None):
    if name not in body or body[name] is None:
        _fail("Field '%s' is required." % name)
    return _as_str(body[name], name, min_len, max_len)


def opt_str(body, name, min_len=1, max_len=None, default=None):
    if name not in body or body[name] is None:
        return default
    return _as_str(body[name], name, min_len, max_len)


def _as_str(value, name, min_len, max_len):
    if not isinstance(value, str):
        _fail("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        _fail("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _fail("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def req_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        _fail("Field '%s' is required." % name)
    return _as_int(body[name], name, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if name not in body or body[name] is None:
        return default
    return _as_int(body[name], name, minimum, maximum)


def _as_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _fail("Field '%s' must be at most %s." % (name, maximum))
    return value


def req_num(body, name, minimum=None, maximum=None, max_decimals=None,
            strictly_positive=False):
    if name not in body or body[name] is None:
        _fail("Field '%s' is required." % name)
    return _as_num(body[name], name, minimum, maximum, max_decimals, strictly_positive)


def opt_num(body, name, minimum=None, maximum=None, max_decimals=None,
            strictly_positive=False, default=None):
    if name not in body or body[name] is None:
        return default
    return _as_num(body[name], name, minimum, maximum, max_decimals, strictly_positive)


def _as_num(value, name, minimum, maximum, max_decimals, strictly_positive):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _fail("Field '%s' must be a number." % name)
    if strictly_positive and dec <= 0:
        _fail("Field '%s' must be strictly greater than zero." % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        _fail("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        _fail("Field '%s' must be at most %s." % (name, maximum))
    if max_decimals is not None:
        exponent = dec.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -max_decimals:
            _fail("Field '%s' must have at most %d decimal places." % (name, max_decimals))
    return dec


def req_bool(body, name):
    if name not in body or body[name] is None:
        _fail("Field '%s' is required." % name)
    if not isinstance(body[name], bool):
        _fail("Field '%s' must be a boolean." % name)
    return body[name]


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        _fail("Field '%s' must be a boolean." % name)
    return body[name]


def req_enum(body, name, allowed):
    value = req_str(body, name, min_len=1, max_len=None)
    if value not in allowed:
        _fail("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, allowed)


def req_date(body, name):
    if name not in body or body[name] is None:
        _fail("Field '%s' is required." % name)
    return _as_date(body[name], name)


def opt_date(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return _as_date(body[name], name)


def _as_date(value, name):
    if not isinstance(value, str):
        _fail("Field '%s' must be a YYYY-MM-DD date string." % name)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        _fail("Field '%s' must be a YYYY-MM-DD date string." % name)
    return date(parsed.year, parsed.month, parsed.day)


def req_datetime(body, name):
    if name not in body or body[name] is None:
        _fail("Field '%s' is required." % name)
    return _as_datetime(body[name], name)


def opt_datetime(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return _as_datetime(body[name], name)


def _as_datetime(value, name):
    if not isinstance(value, str):
        _fail("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _fail("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def digits(value, name, length):
    if not isinstance(value, str) or len(value) != length or not value.isdigit():
        _fail("Field '%s' must be exactly %d digits." % (name, length))
    return value


# --------------------------------------------------------------------------- #
# query parameters
# --------------------------------------------------------------------------- #

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _fail("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            _fail("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _fail("Query parameter 'offset' must be an integer.")
        if offset < PAGINATION_DEFAULT_OFFSET:
            _fail("Query parameter 'offset' must be at least 0.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        _fail("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
