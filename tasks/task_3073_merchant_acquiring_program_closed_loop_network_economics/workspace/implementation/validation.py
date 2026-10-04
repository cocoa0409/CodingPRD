"""Request body parsing and validation helpers (PRD §2.3 / §5).

All request bodies are JSON objects.  Missing required fields, unknown fields,
enum violations and range violations are ERR_INVALID_REQUEST (HTTP 400).
Body *references* to entities that do not exist are ERR_NOT_FOUND, not a
malformed request — the two codes are not interchangeable.
"""

from clock import parse_iso
from errors import invalid_request


def body_object(body, allowed_fields):
    """Validate that the body is an object carrying only known fields."""
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise invalid_request("The request body must be a JSON object.")
    unknown = [key for key in body if key not in allowed_fields]
    if unknown:
        raise invalid_request("Unknown field(s): " + ", ".join(sorted(unknown)) + ".")
    return body


def require_string(body, field):
    if field not in body:
        raise invalid_request("Missing required field: %s." % field)
    value = body[field]
    if not isinstance(value, str) or not value.strip():
        raise invalid_request("Field %s must be a non-empty string." % field)
    return value.strip()


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str):
        raise invalid_request("Field %s must be a string." % field)
    return value


def require_int(body, field, minimum=None, maximum=None):
    if field not in body:
        raise invalid_request("Missing required field: %s." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("Field %s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise invalid_request("Field %s must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise invalid_request("Field %s must be <= %d." % (field, maximum))
    return value


def require_enum(body, field, allowed):
    value = require_string(body, field)
    if value not in allowed:
        raise invalid_request(
            "Field %s must be one of: %s." % (field, ", ".join(sorted(allowed)))
        )
    return value


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise invalid_request("Field %s must be a boolean." % field)
    return value


def optional_int(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("Field %s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise invalid_request("Field %s must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise invalid_request("Field %s must be <= %d." % (field, maximum))
    return value


def require_datetime(body, field):
    if field not in body:
        raise invalid_request("Missing required field: %s." % field)
    parsed = parse_iso(body[field])
    if parsed is None:
        raise invalid_request("Field %s must be an ISO 8601 UTC timestamp." % field)
    return parsed


def optional_datetime(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    parsed = parse_iso(body[field])
    if parsed is None:
        raise invalid_request("Field %s must be an ISO 8601 UTC timestamp." % field)
    return parsed