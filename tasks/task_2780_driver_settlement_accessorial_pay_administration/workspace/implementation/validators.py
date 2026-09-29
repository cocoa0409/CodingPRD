"""Request-shape validation: rungs 4 and 5 of the precedence ladder."""
from datetime import datetime, timezone

from errors import ApiError

MISSING = "ERR_MISSING_REQUIRED_FIELD"
INVALID = "ERR_INVALID_FIELD_VALUE"


def body_of(request):
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError(INVALID, "The request body must be a JSON object.")
    return payload


def require(body, names):
    for name in names:
        if name not in body or body.get(name) is None:
            raise ApiError(MISSING, "Field '%s' is required." % name)


def must_be_null(body, names):
    for name in names:
        if name in body and body.get(name) is not None:
            raise ApiError(INVALID, "Field '%s' must be null for this request." % name)


def enum_value(body, name, allowed, required=False, default=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError(MISSING, "Field '%s' is required." % name)
        return default
    value = body.get(name)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(INVALID, "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def check_enum(value, name, allowed):
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(INVALID, "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def int_value(body, name, required=False, default=None, minimum=None, maximum=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError(MISSING, "Field '%s' is required." % name)
        return default
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(INVALID, "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError(INVALID, "Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError(INVALID, "Field '%s' must be at most %d." % (name, maximum))
    return value


def bool_value(body, name, required=False, default=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError(MISSING, "Field '%s' is required." % name)
        return default
    value = body.get(name)
    if not isinstance(value, bool):
        raise ApiError(INVALID, "Field '%s' must be a boolean." % name)
    return value


def string_value(body, name, required=False, default=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError(MISSING, "Field '%s' is required." % name)
        return default
    value = body.get(name)
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError(INVALID, "Field '%s' must be a non-empty string." % name)
    return value


def parse_timestamp(raw, name):
    if not isinstance(raw, str):
        raise ApiError(INVALID, "Field '%s' must be an ISO-8601 UTC timestamp." % name)
    text = raw.strip()
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise ApiError(INVALID, "Field '%s' must be an ISO-8601 UTC timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ts_value(body, name, required=False, default=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError(MISSING, "Field '%s' is required." % name)
        return default
    return parse_timestamp(body.get(name), name)


def id_value(body, name, required=False, default=None):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError(MISSING, "Field '%s' is required." % name)
        return default
    value = body.get(name)
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError(INVALID, "Field '%s' must be a non-empty string identifier." % name)
    return value
