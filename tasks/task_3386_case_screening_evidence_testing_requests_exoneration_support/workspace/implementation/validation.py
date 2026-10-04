"""Request-shape validation helpers (priority 3.8 in PRD 2.9) plus pagination.

Every shape violation raises ERR_INVALID_REQUEST (400). Event-vocabulary
violations on advance endpoints raise ERR_INVALID_TRANSITION_EVENT (400) and
are raised by the route modules themselves, after basic shape checks.
"""

from flask import request

from clock import parse_iso
from envelope import list_response
from errors import ERR_INVALID_REQUEST, raise_err


def body_json():
    """Parse the request body; it must be a JSON object."""
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def reject_unknown(body, allowed):
    extra = sorted(k for k in body.keys() if k not in allowed)
    if extra:
        raise_err(ERR_INVALID_REQUEST,
                  "Unknown field(s): %s" % ", ".join(extra))


def require_field(body, name):
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return body[name]


req_field = require_field


def as_string(value, name):
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a string" % name)
    return value


def as_boolean(value, name):
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a boolean" % name)
    return value


def as_integer(value, name, minimum=None, maximum=None):
    if not isinstance(value, int) or isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST,
                  "Field '%s' must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise_err(ERR_INVALID_REQUEST,
                  "Field '%s' must be <= %d" % (name, maximum))
    return value


def as_choice(value, name, choices):
    if not isinstance(value, str) or value not in choices:
        raise_err(ERR_INVALID_REQUEST,
                  "Field '%s' must be one of: %s" % (name, ", ".join(choices)))
    return value


def as_datetime(value, name):
    """Validate an ISO 8601 date/datetime; the raw string is kept verbatim."""
    if not isinstance(value, str) or parse_iso(value) is None:
        raise_err(ERR_INVALID_REQUEST,
                  "Field '%s' must be an ISO 8601 timestamp" % name)
    return value


def req_str(body, name):
    return as_string(require_field(body, name), name)


def req_bool(body, name):
    return as_boolean(require_field(body, name), name)


def req_int(body, name, minimum=None, maximum=None):
    return as_integer(require_field(body, name), name, minimum, maximum)


def req_choice(body, name, choices):
    return as_choice(require_field(body, name), name, choices)


def req_datetime(body, name):
    return as_datetime(require_field(body, name), name)


def opt_str(body, name):
    """Optional string field; present-and-null is a type error."""
    if name not in body:
        return None
    return as_string(body[name], name)


def opt_int(body, name, minimum=None, maximum=None):
    if name not in body:
        return None
    return as_integer(body[name], name, minimum, maximum)


def opt_nullable_int(body, name, minimum=None, maximum=None):
    """Optional integer field where an explicit JSON null is meaningful
    (stored as None)."""
    if name not in body or body[name] is None:
        return None
    return as_integer(body[name], name, minimum, maximum)


def opt_datetime(body, name):
    if name not in body:
        return None
    return as_datetime(body[name], name)


def pagination_args():
    """limit / offset query params: defaults 10 / 0, limit within 1..100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST,
                      "Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST,
                      "Query parameter 'offset' must be >= 0")
    return limit, offset


def paged_list(items, filters):
    """Apply exact-match filters, sort by created_at ascending (PRD 2.3),
    and render the paginated array envelope."""
    for key, val in filters.items():
        if val is not None:
            items = [i for i in items if str(i.get(key)) == val]
    items = sorted(items, key=lambda e: e["created_at"])
    limit, offset = pagination_args()
    return list_response(items, limit, offset)
