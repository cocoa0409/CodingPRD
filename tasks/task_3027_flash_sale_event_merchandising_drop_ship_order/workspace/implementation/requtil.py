"""Request parsing helpers shared by every route module."""

from flask import request

from errors import invalid_request
from store import parse_time

# response_envelope.pagination_defaults { limit: 10, min: 1, max: 100, offset: 0 }
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid_request("The request body must be a JSON object.")
    return data


def pagination():
    """Validate limit / offset; outside the range is a shape failure (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = LIMIT_DEFAULT if limit_raw in (None, "") else int(limit_raw)
    except (TypeError, ValueError):
        invalid_request("limit must be an integer.")
    try:
        offset = OFFSET_DEFAULT if offset_raw in (None, "") else int(offset_raw)
    except (TypeError, ValueError):
        invalid_request("offset must be an integer.")
    if limit < LIMIT_MIN or limit > LIMIT_MAX or offset < 0:
        invalid_request("limit or offset falls outside its permitted range.")
    return limit, offset


def q(name):
    value = request.args.get(name)
    if value in (None, ""):
        return None
    return value


def qint(name):
    value = q(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        invalid_request("%s must be an integer." % name)
    return None


def qbool(name):
    value = q(name)
    if value is None:
        return None
    return value.lower() in ("true", "1", "yes")


def bbool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def bstr(data, name, required=True):
    value = data.get(name)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        if required:
            invalid_request("Field %s is required." % name)
        return None
    if not isinstance(value, str):
        invalid_request("Field %s must be a string." % name)
    return value


def bint(data, name, required=True, minimum=None, maximum=None):
    value = data.get(name)
    if value is None:
        if required:
            invalid_request("Field %s is required." % name)
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        else:
            invalid_request("Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid_request("Field %s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid_request("Field %s must be at most %d." % (name, maximum))
    return value


def btime(data, name, required=True):
    value = data.get(name)
    if value is None:
        if required:
            invalid_request("Field %s is required." % name)
        return None
    parsed = parse_time(value)
    if parsed is None:
        invalid_request("Field %s must be an ISO 8601 instant." % name)
    return parsed


def benum(data, name, allowed, required=True):
    value = data.get(name)
    if value is None:
        if required:
            invalid_request("Field %s is required." % name)
        return None
    if value not in allowed:
        invalid_request("Field %s carries an undeclared enum member." % name)
    return value