"""Request-shape validation helpers (validation cascade priority 5, PRD 2.9)."""

from datetime import date, datetime, timezone

from flask import request

from errors import raise_err


def get_body():
    """Return the JSON request body as a dict; anything else is a shape error
    deferred to field validators (missing body behaves like an empty body)."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise_err("ERR_INVALID_REQUEST", "request body must be valid JSON")
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise_err("ERR_INVALID_REQUEST", "field '%s' is required and must be a non-blank string" % field)
    return value


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str):
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be a string" % field)
    return value


def req_enum(body, field, domain):
    value = body.get(field)
    if not isinstance(value, str) or value not in domain:
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be one of %s" % (field, "/".join(domain)))
    return value


def opt_enum_query(field, domain):
    """Validate an optional query-string enum filter; bad values are shape errors."""
    value = request.args.get(field)
    if value is None:
        return None
    if value not in domain:
        raise_err("ERR_INVALID_REQUEST", "query parameter '%s' must be one of %s" % (field, "/".join(domain)))
    return value


def req_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        raise_err("ERR_INVALID_REQUEST", "field '%s' is required and must be a boolean" % field)
    return value


def req_int(body, field):
    value = body.get(field)
    if not _is_int(value):
        raise_err("ERR_INVALID_REQUEST", "field '%s' is required and must be an integer" % field)
    return value


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not _is_int(value):
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be an integer" % field)
    return value


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be a number" % field)
    return value


def parse_iso_date(value, field):
    """Parse a strict ISO calendar date (YYYY-MM-DD); anything else is a 400."""
    if not isinstance(value, str):
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be an ISO calendar date" % field)
    text = value.strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be a well-formed ISO calendar date" % field)
    if text != parsed.isoformat():
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be a well-formed ISO calendar date" % field)
    return parsed


def req_date(body, field):
    if field not in body or body[field] is None:
        raise_err("ERR_INVALID_REQUEST", "field '%s' is required" % field)
    return parse_iso_date(body[field], field)


def parse_instant(value, field="to_iso8601"):
    """Parse an ISO 8601 datetime instant for the logical-clock setter."""
    if not isinstance(value, str) or not value.strip():
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be an ISO 8601 timestamp" % field)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "field '%s' must be an ISO 8601 timestamp" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def day_start(d):
    """Start-of-day UTC datetime for an ISO calendar date."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
