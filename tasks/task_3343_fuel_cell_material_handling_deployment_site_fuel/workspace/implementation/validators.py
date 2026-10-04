"""Input validation helpers.

Shape/type/enum/format failures raise ERR_INVALID_REQUEST (400). Date and
datetime parsers return None on failure so callers can raise the appropriate
error (400 for malformed formats, 422 for coherent-format but bad ordering).
"""

import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def _bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def parse_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_month(s):
    if not isinstance(s, str):
        return None
    m = MONTH_RE.match(s)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        return None
    return (year, month)


def parse_datetime(s):
    if not isinstance(s, str) or not DATETIME_RE.match(s):
        return None
    frac = re.search(r"\.(\d+)", s)
    if frac and len(frac.group(1)) > 6:
        s = s[: frac.start(1)] + frac.group(1)[:6] + s[frac.end(1):]
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        _bad("request body must be a JSON object")
    return data


def req(data, field):
    if field not in data or data[field] is None:
        _bad("missing required field: " + field)
    return data[field]


def str_value(val, field, min_len=None, max_len=None):
    if not isinstance(val, str):
        _bad("field '%s' must be a string" % field)
    if min_len is not None and len(val) < min_len:
        _bad("field '%s' must be at least %d characters" % (field, min_len))
    if max_len is not None and len(val) > max_len:
        _bad("field '%s' must be at most %d characters" % (field, max_len))
    return val


def enum_value(val, field, allowed):
    str_value(val, field)
    if val not in allowed:
        _bad("field '%s' must be one of %s" % (field, sorted(allowed)))
    return val


def number_value(val, field, gt=None, ge=None, lt=None, le=None):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _bad("field '%s' must be a number" % field)
    if gt is not None and not val > gt:
        _bad("field '%s' must be > %s" % (field, gt))
    if ge is not None and not val >= ge:
        _bad("field '%s' must be >= %s" % (field, ge))
    if lt is not None and not val < lt:
        _bad("field '%s' must be < %s" % (field, lt))
    if le is not None and not val <= le:
        _bad("field '%s' must be <= %s" % (field, le))
    return val


def int_value(val, field, gt=None, ge=None, lt=None, le=None):
    if isinstance(val, bool):
        _bad("field '%s' must be an integer" % field)
    if isinstance(val, int):
        n = val
    elif isinstance(val, float) and val.is_integer():
        n = int(val)
    else:
        _bad("field '%s' must be an integer" % field)
    if gt is not None and not n > gt:
        _bad("field '%s' must be > %s" % (field, gt))
    if ge is not None and not n >= ge:
        _bad("field '%s' must be >= %s" % (field, ge))
    if lt is not None and not n < lt:
        _bad("field '%s' must be < %s" % (field, lt))
    if le is not None and not n <= le:
        _bad("field '%s' must be <= %s" % (field, le))
    return n


def bool_value(val, field):
    if not isinstance(val, bool):
        _bad("field '%s' must be a boolean" % field)
    return val


def date_value(val, field):
    if parse_date(val) is None:
        _bad("field '%s' must be a valid YYYY-MM-DD date" % field)
    return val


def datetime_value(val, field):
    if parse_datetime(val) is None:
        _bad("field '%s' must be a valid ISO8601 datetime with timezone" % field)
    return val


def month_value(val, field):
    if parse_month(val) is None:
        _bad("field '%s' must be a valid YYYY-MM month" % field)
    return val
