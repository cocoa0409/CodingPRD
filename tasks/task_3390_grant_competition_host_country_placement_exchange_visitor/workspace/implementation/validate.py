"""Request-payload validation helpers. Every failure here is ERR_VALIDATION
(400) unless a more specific helper is used."""

from flask import request

from errors import ApiError
from timeutil import parse_iso


def V(message):
    return ApiError("ERR_VALIDATION", 400, message)


def body():
    """Return the JSON request body as a dict. A missing/unparseable body is
    treated as an empty object; a non-object body is a validation error."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise V("Request body must be a JSON object")
    return data


def check_unknown(payload, allowed):
    extra = sorted(set(payload) - set(allowed))
    if extra:
        raise V("Unknown request field(s): " + ", ".join(extra))


def req(payload, field):
    if field not in payload or payload[field] is None:
        raise V("Missing required field: %s" % field)
    return payload[field]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise V("Field %s must be a non-empty string" % field)
    return value


def as_text(value, field):
    """Free-form text: any string (empty allowed)."""
    if not isinstance(value, str):
        raise V("Field %s must be a string" % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise V("Field %s must be an integer" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise V("Field %s must be a boolean" % field)
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise V("Field %s must be one of: %s" % (field, ", ".join(sorted(allowed))))
    return value


def as_score(value, field):
    """Review score: an integer 0-100 (floats with integral value accepted)."""
    if isinstance(value, bool):
        raise V("Field %s must be an integer between 0 and 100" % field)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or value < 0 or value > 100:
        raise V("Field %s must be an integer between 0 and 100" % field)
    return value


def as_dt(value, field):
    if not isinstance(value, str):
        raise V("Field %s must be an ISO8601 string" % field)
    try:
        return parse_iso(value)
    except Exception:
        raise V("Field %s must be a valid ISO8601 timestamp" % field)


def as_version(value, field="expected_application_version"):
    if isinstance(value, bool) or not isinstance(value, int):
        raise V("Field %s must be an integer" % field)
    return value


def pagination():
    """Parse limit/offset query params. Defaults 10/0; limit in [1, 100];
    offset >= 0. Out-of-range or non-integer values are ERR_VALIDATION."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    try:
        limit = int(limit_s) if limit_s is not None else 10
    except (TypeError, ValueError):
        raise V("Query parameter limit must be an integer")
    try:
        offset = int(offset_s) if offset_s is not None else 0
    except (TypeError, ValueError):
        raise V("Query parameter offset must be an integer")
    if limit < 1 or limit > 100:
        raise V("Query parameter limit must be between 1 and 100")
    if offset < 0:
        raise V("Query parameter offset must be >= 0")
    return limit, offset


def page_slice(items, limit, offset):
    """Sort by (created_at, insertion seq) ascending and slice a page."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total
