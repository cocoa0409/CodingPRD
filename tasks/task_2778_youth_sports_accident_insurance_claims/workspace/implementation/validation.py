"""Request-shape validation (ladder priority 4). All failures are ERR_INVALID_REQUEST."""

import re

from flask import request

import util
from errors import ApiError

LEAGUE_CODE_RE = re.compile(r"^[A-Z0-9-]{3,16}$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
NPI_RE = re.compile(r"^[0-9]{10}$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """The request body as a dict. Absent body is treated as an empty object."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _present(body, field, required):
    if field not in body or body[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return False
    return True


def req_str(body, field, required=True, default=None, min_len=1, max_len=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if len(value) < min_len:
        bad("Field '%s' must not be empty." % field)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % field)
    return value


def req_enum(body, field, members, required=True, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def req_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %d." % (field, maximum))
    return value


def req_bool(body, field, required=True, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def req_date(body, field, required=True, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    parsed = util.parse_date(value)
    if parsed is None:
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % field)
    return parsed


def req_datetime(body, field, required=True, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    parsed = util.parse_datetime(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    return parsed


def req_id(body, field, required=True, default=None):
    if not _present(body, field, required):
        return default
    value = body[field]
    if not isinstance(value, str) or not value:
        bad("Field '%s' must be an identifier string." % field)
    return value


def req_league_code(body, field):
    value = req_str(body, field, max_len=16)
    if not LEAGUE_CODE_RE.match(value):
        bad("Field '%s' must be 3-16 uppercase letters, digits or hyphens." % field)
    return value


def req_state_code(body, field):
    value = req_str(body, field)
    if not STATE_CODE_RE.match(value):
        bad("Field '%s' must be exactly two uppercase letters." % field)
    return value


def req_npi(body, field):
    value = req_str(body, field)
    if not NPI_RE.match(value):
        bad("Field '%s' must be exactly ten digits." % field)
    return value


def req_cap_map(body, field, allowed_keys, required=True, default=None):
    """service_category_caps: keys a subset of the scheduled categories, int values >= 0."""
    if not _present(body, field, required):
        return dict(default) if default is not None else default
    value = body[field]
    if not isinstance(value, dict):
        bad("Field '%s' must be an object." % field)
    out = {}
    for key, amount in value.items():
        if key not in allowed_keys:
            bad("Field '%s' contains an unknown service category '%s'." % (field, key))
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            bad("Field '%s' values must be integers >= 0." % field)
        out[key] = amount
    return out


# ------------------------------------------------------------------ pagination

def pagination():
    limit = _query_int("limit", 10)
    offset = _query_int("offset", 0)
    if limit < 1 or limit > 100:
        bad("Query parameter 'limit' must be between 1 and 100.")
    if offset < 0:
        bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)


def query_enum(name, members):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_state_code(name):
    raw = query_str(name)
    if raw is None:
        return None
    if not STATE_CODE_RE.match(raw):
        bad("Query parameter '%s' must be exactly two uppercase letters." % name)
    return raw


def req_instant(body, field, required=True, default=None):
    """An ISO 8601 UTC instant. A bare YYYY-MM-DD is accepted as that day's midnight."""
    if not _present(body, field, required):
        return default
    value = body[field]
    parsed = util.parse_datetime(value)
    if parsed is None:
        day = util.parse_date(value)
        if day is not None:
            parsed = util.midnight(day)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    return parsed
