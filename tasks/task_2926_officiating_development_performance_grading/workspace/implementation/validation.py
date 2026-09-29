"""Request-shape validation -- step 3 of the rejection precedence (PRD 2.9).

"The request body is well-formed: every required input field is present, no
unknown field is honored, every enum-valued field carries a declared value,
every score lies within the inclusive range 0.00 through 100.00, every
timestamp parses as an ISO 8601 UTC instant, integers are non-negative, and a
MODIFIED appeal decision carries a revised_grade_code that differs from the
grade's current grade_code. Otherwise ERR_INVALID_REQUEST (400)."

Unknown fields are simply not honored (PRD 2.10: "A request that attempts to
set one of them directly does not have that value honored") -- they are ignored
rather than rejected.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

import errors
from errors import fail

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100.00")

_TEAM_CODE = re.compile(r"^[A-Z]{3}$")


def q2(value):
    """Round half up to exactly 2 decimal places (PRD 2.7)."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return payload


def present(data, name):
    return name in data and data[name] is not None


def _bad(name, why):
    fail(errors.ERR_INVALID_REQUEST, "Field '%s' %s." % (name, why))


def req_str(data, name, min_len=1, max_len=None):
    if not present(data, name):
        _bad(name, "is required")
    return _check_str(data[name], name, min_len, max_len)


def opt_str(data, name, min_len=1, max_len=None, default=None):
    if not present(data, name):
        return default
    return _check_str(data[name], name, min_len, max_len)


def _check_str(value, name, min_len, max_len):
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and min_len >= 1 and value.strip() == "":
        _bad(name, "may not be blank")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def req_enum(data, name, allowed):
    if not present(data, name):
        _bad(name, "is required")
    return _check_enum(data[name], name, allowed)


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return _check_enum(data[name], name, allowed)


def _check_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def req_int(data, name, minimum=0, maximum=None):
    if not present(data, name):
        _bad(name, "is required")
    return _check_int(data[name], name, minimum, maximum)


def opt_int(data, name, minimum=0, maximum=None, default=None):
    if not present(data, name):
        return default
    return _check_int(data[name], name, minimum, maximum)


def _check_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %d" % maximum)
    return value


def req_score(data, name):
    """A score lies within the inclusive range 0.00 through 100.00 (PRD 2.7)."""
    if not present(data, name):
        _bad(name, "is required")
    return _check_score(data[name], name)


def opt_score(data, name, default=None):
    if not present(data, name):
        return default
    return _check_score(data[name], name)


def _check_score(value, name):
    return _check_decimal(value, name, ZERO, HUNDRED)


def _check_decimal(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        _bad(name, "must be a number")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(name, "must be a number")
        return None
    if not dec.is_finite():
        _bad(name, "must be a finite number")
    if minimum is not None and dec < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and dec > maximum:
        _bad(name, "must be at most %s" % maximum)
    return q2(dec)


def req_team_code(data, name):
    value = req_str(data, name, 3, 3)
    if not _TEAM_CODE.match(value):
        _bad(name, "must be exactly three uppercase letters")
    return value


def opt_team_code(data, name, default=None):
    if not present(data, name):
        return default
    value = _check_str(data[name], name, 3, 3)
    if not _TEAM_CODE.match(value):
        _bad(name, "must be exactly three uppercase letters")
    return value


def req_datetime(data, name):
    if not present(data, name):
        _bad(name, "is required")
    return parse_instant(data[name], name)


def parse_instant(value, name):
    """PRD 2.4: "An input timestamp that does not parse as an ISO 8601 UTC
    instant is rejected with ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or value.strip() == "":
        _bad(name, "must be an ISO 8601 UTC instant")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _bad(name, "must be an ISO 8601 UTC instant")
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_string_list(data, name, allowed):
    if not present(data, name):
        _bad(name, "is required")
    return _check_string_list(data[name], name, allowed)


def opt_string_list(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return _check_string_list(data[name], name, allowed)


def _check_string_list(value, name, allowed):
    if not isinstance(value, list) or len(value) == 0:
        _bad(name, "must be a non-empty array")
    out = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _bad(name, "must be a subset of %s" % ", ".join(allowed))
        if item not in out:
            out.append(item)
    return out


# --- pagination (PRD 2.3) --------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def pagination():
    """`limit` defaults to 10, may not be smaller than 1 and may not be larger
    than 100. `offset` defaults to 0 and may not be negative. A `limit` outside
    the permitted range, or a negative `offset`, is rejected with
    ERR_INVALID_REQUEST (PRD 2.3)."""
    limit = DEFAULT_LIMIT
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except ValueError:
            _bad("limit", "must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            _bad("limit", "must be between %d and %d" % (MIN_LIMIT, MAX_LIMIT))
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except ValueError:
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "may not be negative")
    return limit, offset


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
