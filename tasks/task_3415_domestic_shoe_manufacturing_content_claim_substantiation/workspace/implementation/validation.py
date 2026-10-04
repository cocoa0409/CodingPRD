"""Request payload and query validation helpers (validation family 5).

All violations raise ERR_INVALID_REQUEST (400) unless a more specific error
is mandated. Type checks reject JSON booleans where integers are required.
"""
import re
from datetime import datetime

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_WEEK_RE = re.compile(r"^\d{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$")


def body():
    """The JSON request body as a dict; {} when absent, 400 when not an object."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _present(b, name):
    return name in b and b[name] is not None


def _invalid(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def req_str(b, name):
    if not _present(b, name) or not isinstance(b[name], str) or b[name] == "":
        _invalid("field '%s' is required and must be a non-empty string" % name)
    return b[name]


def opt_str(b, name):
    if _present(b, name):
        if not isinstance(b[name], str):
            _invalid("field '%s' must be a string" % name)
        return b[name]
    return None


def req_bool(b, name):
    if not _present(b, name) or not isinstance(b[name], bool):
        _invalid("field '%s' is required and must be a boolean" % name)
    return b[name]


def opt_bool(b, name, default=None):
    if _present(b, name):
        if not isinstance(b[name], bool):
            _invalid("field '%s' must be a boolean" % name)
        return b[name]
    return default


def req_int(b, name, min_v=None, max_v=None):
    if not _present(b, name) or isinstance(b[name], bool) or not isinstance(b[name], int):
        _invalid("field '%s' is required and must be an integer" % name)
    v = b[name]
    if min_v is not None and v < min_v:
        _invalid("field '%s' must be >= %d" % (name, min_v))
    if max_v is not None and v > max_v:
        _invalid("field '%s' must be <= %d" % (name, max_v))
    return v


def req_number(b, name, gt=None):
    """A JSON number (int or float); `gt` enforces strictly-greater-than."""
    if not _present(b, name) or isinstance(b[name], bool) or not isinstance(b[name], (int, float)):
        _invalid("field '%s' is required and must be a number" % name)
    v = b[name]
    if gt is not None and not v > gt:
        _invalid("field '%s' must be > %s" % (name, gt))
    return v


def req_enum(b, name, values):
    if not _present(b, name) or b[name] not in values:
        _invalid("field '%s' must be one of %s" % (name, ", ".join(values)))
    return b[name]


def req_date(b, name):
    """An ISO YYYY-MM-DD calendar date, returned as the validated string."""
    v = req_str(b, name)
    if not _DATE_RE.match(v):
        _invalid("field '%s' must be an ISO date YYYY-MM-DD" % name)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        _invalid("field '%s' is not a valid calendar date" % name)
    return v


def req_iso_week(b, name):
    v = req_str(b, name)
    if not _ISO_WEEK_RE.match(v):
        _invalid("field '%s' must be an ISO week in YYYY-Www form" % name)
    return v


def opt_query_bool(name):
    """Parse a boolean list-filter query param; None when absent or unparsable."""
    raw = request.args.get(name)
    if raw is None:
        return None
    lv = raw.lower()
    if lv == "true":
        return True
    if lv == "false":
        return False
    return None
