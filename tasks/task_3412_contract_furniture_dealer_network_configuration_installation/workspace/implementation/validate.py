# Body-shape and field validators (PRD 2.9 step 5; step 6 date windows).
import re
from datetime import date, datetime, timezone

import clock
import errors


def is_str(v):
    return isinstance(v, str)


def is_int(v):
    # JSON booleans must not pass as integers.
    return isinstance(v, int) and not isinstance(v, bool)


def is_bool(v):
    return isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def body_json(request):
    """Return the request JSON object; a missing/non-object body counts as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        errors.validation("Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        errors.validation(f"Missing required field: {field}")
    return body[field]


def optional(body, field, default=None):
    return body.get(field, default)


def req_str(body, field):
    v = require(body, field)
    if not is_str(v) or v == "":
        errors.validation(f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is None:
        return None
    if not is_str(v):
        errors.validation(f"Field {field} must be a string")
    return v


def req_int(body, field, minimum=None):
    v = require(body, field)
    if not is_int(v):
        errors.validation(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        errors.validation(f"Field {field} must be >= {minimum}")
    return v


def req_bool(body, field):
    v = require(body, field)
    if not is_bool(v):
        errors.validation(f"Field {field} must be a boolean")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field, default)
    if v is None:
        return None
    if not is_bool(v):
        errors.validation(f"Field {field} must be a boolean")
    return v


def req_enum(body, field, members):
    v = require(body, field)
    if not is_str(v) or v not in members:
        errors.validation(f"Field {field} must be one of {list(members)}")
    return v


def parse_iso_date(value, field):
    """Strict YYYY-MM-DD date parse -> datetime.date; bad input is ERR_VALIDATION."""
    if not is_str(value):
        errors.validation(f"Field {field} must be an ISO date string (YYYY-MM-DD)")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        errors.validation(f"Field {field} must be an ISO date string (YYYY-MM-DD)")
    return parsed


def req_date(body, field):
    return parse_iso_date(require(body, field), field)


def parse_iso_datetime(value, field):
    """ISO 8601 datetime parse -> aware UTC datetime; bad input is ERR_VALIDATION."""
    if not is_str(value):
        errors.validation(f"Field {field} must be an ISO 8601 datetime string")
    try:
        return clock._parse_iso_datetime(value)
    except (ValueError, TypeError):
        errors.validation(f"Field {field} must be an ISO 8601 datetime string")


def req_datetime(body, field):
    return parse_iso_datetime(require(body, field), field)


_TERRITORY_RE = re.compile(r"^[A-Z]{2}$")


def req_territory_codes(body, field):
    v = require(body, field)
    if not isinstance(v, list) or len(v) < 1:
        errors.validation(f"Field {field} must be a non-empty array")
    for code in v:
        if not is_str(code) or not _TERRITORY_RE.match(code):
            errors.validation(
                f"Field {field} entries must be 2-letter uppercase codes")
    return list(v)


def fraction_0_to_1(body, field):
    v = require(body, field)
    if not is_number(v):
        errors.validation(f"Field {field} must be a number")
    if not (0 <= v < 1):
        errors.validation(f"Field {field} must satisfy 0 <= x < 1")
    return v
