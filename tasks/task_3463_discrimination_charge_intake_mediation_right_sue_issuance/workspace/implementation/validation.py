"""Request-body field validators (validation-pipeline step 3).

Every failure raises ApiError(ERR_VALIDATION_FAILED). These helpers only run
after authentication and role authorization, and before existence checks.
"""

from datetime import date, datetime, timezone

from errors import ApiError, ERR_VALIDATION_FAILED


def _fail(message):
    raise ApiError(ERR_VALIDATION_FAILED, message)


def get_body_dict(raw):
    """The parsed JSON body must be an object for endpoints that take input."""
    if raw is None:
        _fail("Request body must be a JSON object.")
    if not isinstance(raw, dict):
        _fail("Request body must be a JSON object.")
    return raw


def req_string(body, field):
    if field not in body:
        _fail("Missing required field: %s" % field)
    value = body[field]
    if not isinstance(value, str):
        _fail("Field %s must be a string." % field)
    return value


def opt_string(body, field):
    """Optional string; explicitly-null is a type failure."""
    if field not in body:
        return None, False
    value = body[field]
    if not isinstance(value, str):
        _fail("Field %s must be a string." % field)
    return value, True


def _is_int(value):
    # bool is an int subclass in Python; reject it explicitly.
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, field, minimum=None, choices=None):
    if field not in body:
        _fail("Missing required field: %s" % field)
    value = body[field]
    if not _is_int(value):
        _fail("Field %s must be an integer." % field)
    if minimum is not None and value < minimum:
        _fail("Field %s must be >= %d." % (field, minimum))
    if choices is not None and value not in choices:
        _fail("Field %s must be one of %s." % (field, list(choices)))
    return value


def opt_int(body, field, minimum=None):
    """Optional integer; explicitly-null is a type failure."""
    if field not in body:
        return None, False
    value = body[field]
    if not _is_int(value):
        _fail("Field %s must be an integer." % field)
    if minimum is not None and value < minimum:
        _fail("Field %s must be >= %d." % (field, minimum))
    return value, True


def req_bool(body, field):
    if field not in body:
        _fail("Missing required field: %s" % field)
    value = body[field]
    if not isinstance(value, bool):
        _fail("Field %s must be a boolean." % field)
    return value


def req_enum(body, field, choices):
    if field not in body:
        _fail("Missing required field: %s" % field)
    value = body[field]
    if not isinstance(value, str) or value not in choices:
        _fail("Field %s must be one of %s." % (field, list(choices)))
    return value


def req_enum_array(body, field, choices, min_length=1):
    if field not in body:
        _fail("Missing required field: %s" % field)
    value = body[field]
    if not isinstance(value, list):
        _fail("Field %s must be an array." % field)
    if len(value) < min_length:
        _fail("Field %s must be a non-empty array." % field)
    for item in value:
        if not isinstance(item, str) or item not in choices:
            _fail("Field %s contains an invalid member: %r" % (field, item))
    return list(value)


def opt_enum_array(body, field, choices, min_length=1):
    if field not in body:
        return None, False
    return req_enum_array(body, field, choices, min_length), True


def _parse_iso(value, field):
    if not isinstance(value, str):
        _fail("Field %s must be an ISO 8601 string." % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _fail("Field %s is not a valid ISO 8601 datetime." % field)
    return parsed


def req_datetime(body, field):
    """Full timestamp input; must be timezone-aware (normalized to UTC)."""
    if field not in body:
        _fail("Missing required field: %s" % field)
    parsed = _parse_iso(body[field], field)
    if parsed.tzinfo is None:
        _fail("Field %s must carry a timezone designator." % field)
    return parsed.astimezone(timezone.utc)


def req_date(body, field):
    """Date-precision input: 'YYYY-MM-DDT00:00:00Z' (time component must be
    exactly midnight UTC) or a bare 'YYYY-MM-DD'."""
    if field not in body:
        _fail("Missing required field: %s" % field)
    raw = body[field]
    if not isinstance(raw, str):
        _fail("Field %s must be an ISO 8601 date string." % field)
    text = raw.strip()
    if "T" not in text:
        try:
            return date.fromisoformat(text)
        except ValueError:
            _fail("Field %s is not a valid ISO 8601 date." % field)
    parsed = _parse_iso(raw, field)
    if parsed.tzinfo is None:
        _fail("Field %s must carry a timezone designator." % field)
    parsed = parsed.astimezone(timezone.utc)
    if (
        parsed.hour != 0
        or parsed.minute != 0
        or parsed.second != 0
        or parsed.microsecond != 0
    ):
        _fail("Field %s must carry date precision only (T00:00:00Z)." % field)
    return parsed.date()


def opt_date(body, field):
    if field not in body:
        return None, False
    return req_date(body, field), True


def present_non_null(body, field):
    return field in body and body[field] is not None
