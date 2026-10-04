"""Request-body field validation helpers (ERR_VALIDATION, HTTP 400)."""

import datetime
import re

from errors import ApiError

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body_json(request):
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return data


def req_string(data, field):
    value = data.get(field)
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a non-empty string." % field)
    return value


def opt_string(data, field):
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)
    return value


def req_int(data, field, minimum=None, maximum=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "Field '%s' must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "Field '%s' may not exceed %d." % (field, maximum))
    return value


def req_number(data, field, minimum_exclusive=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a number." % field)
    if minimum_exclusive is not None and not value > minimum_exclusive:
        raise ApiError("ERR_VALIDATION", "Field '%s' must be greater than %s." % (field, minimum_exclusive))
    return value


def req_bool(data, field):
    value = data.get(field)
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a boolean." % field)
    return value


def req_enum(data, field, allowed):
    value = data.get(field)
    if value not in allowed:
        raise ApiError("ERR_VALIDATION",
                       "Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def req_date(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date." % field)
    try:
        datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Field '%s' must be a valid YYYY-MM-DD date." % field)
    return value


def req_hhmm(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not _HHMM_RE.match(value):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be an HH:MM time." % field)
    return value


def parse_instant(value, field):
    """Parse an ISO 8601 instant into a naive UTC datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be an ISO 8601 timestamp." % field)
    text = value.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "Field '%s' must be an ISO 8601 timestamp." % field)
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt


def req_instant(data, field):
    return parse_instant(data.get(field), field)


def hhmm_to_minutes(value):
    return int(value[0:2]) * 60 + int(value[3:5])
