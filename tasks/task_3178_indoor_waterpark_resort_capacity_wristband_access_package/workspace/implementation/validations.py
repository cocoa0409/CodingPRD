"""Request shape validation.

PRD 2.4 places body-shape refusal at the head of the cascade: a request body
carrying a field the target endpoint does not declare among its inputs is
refused with ERR_INVALID_REQUEST at the same stage as authentication.
"""

from datetime import datetime

from flask import request

import errors

_MISSING = object()


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise errors.invalid_request("The request body must be a JSON object.")
    return payload


def reject_undeclared(payload, declared):
    for key in payload.keys():
        if key not in declared:
            raise errors.invalid_request(
                "Field '%s' is not declared among this operation's inputs." % key
            )


def optional_str(payload, key, default=None):
    if key not in payload or payload.get(key) is None:
        return default
    value = payload.get(key)
    if not isinstance(value, str):
        raise errors.invalid_request("Field '%s' must be a string." % key)
    return value


def required_str(payload, key):
    if key not in payload or payload.get(key) is None:
        raise errors.invalid_request("Field '%s' is required." % key)
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request("Field '%s' must be a non-empty string." % key)
    return value


def optional_int(payload, key, default=None):
    if key not in payload or payload.get(key) is None:
        return default
    return as_int(payload.get(key), key)


def required_int(payload, key):
    if key not in payload or payload.get(key) is None:
        raise errors.invalid_request("Field '%s' is required." % key)
    return as_int(payload.get(key), key)


def as_int(value, key):
    if isinstance(value, bool):
        raise errors.invalid_request("Field '%s' must be an integer." % key)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            raise errors.invalid_request("Field '%s' must be an integer." % key)
    raise errors.invalid_request("Field '%s' must be an integer." % key)


def as_number(value, key):
    if isinstance(value, bool):
        raise errors.invalid_request("Field '%s' must be a number." % key)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            raise errors.invalid_request("Field '%s' must be a number." % key)
    raise errors.invalid_request("Field '%s' must be a number." % key)


def optional_number(payload, key, default=None):
    if key not in payload or payload.get(key) is None:
        return default
    return as_number(payload.get(key), key)


def required_number(payload, key):
    if key not in payload or payload.get(key) is None:
        raise errors.invalid_request("Field '%s' is required." % key)
    return as_number(payload.get(key), key)


def optional_bool(payload, key, default=None):
    if key not in payload or payload.get(key) is None:
        return default
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    raise errors.invalid_request("Field '%s' must be a boolean." % key)


def in_range(value, key, low=None, high=None):
    if low is not None and value < low:
        raise errors.invalid_request("Field '%s' must be at least %s." % (key, low))
    if high is not None and value > high:
        raise errors.invalid_request("Field '%s' must be at most %s." % (key, high))
    return value


def in_enum(value, key, allowed):
    if value not in allowed:
        raise errors.invalid_request(
            "Field '%s' must be one of %s." % (key, ", ".join(allowed))
        )
    return value


_DATE_FORMATS = ("%Y-%m-%d",)


def as_service_date(value, key):
    if not isinstance(value, str):
        raise errors.invalid_request("Field '%s' must be a YYYY-MM-DD date." % key)
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
            return value
        except ValueError:
            continue
    raise errors.invalid_request("Field '%s' must be a YYYY-MM-DD date." % key)


def optional_service_date(payload, key, default=None):
    if key not in payload or payload.get(key) is None:
        return default
    return as_service_date(payload.get(key), key)


def required_service_date(payload, key):
    if key not in payload or payload.get(key) is None:
        raise errors.invalid_request("Field '%s' is required." % key)
    return as_service_date(payload.get(key), key)


def as_instant(value, key):
    if not isinstance(value, str):
        raise errors.invalid_request("Field '%s' must be an ISO 8601 instant." % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        raise errors.invalid_request("Field '%s' must be an ISO 8601 instant." % key)
    return value


def required_instant(payload, key):
    if key not in payload or payload.get(key) is None:
        raise errors.invalid_request("Field '%s' is required." % key)
    return as_instant(payload.get(key), key)


# --------------------------------------------------------------------------
# Query-string validation
# --------------------------------------------------------------------------

def query_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        limit = as_int(raw_limit, "limit")
        in_range(limit, "limit", low=1, high=100)
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        offset = as_int(raw_offset, "offset")
        in_range(offset, "offset", low=0)
    return limit, offset


def query_str(name):
    return request.args.get(name)


def query_present(name):
    return name in request.args


def require_query(name):
    value = request.args.get(name)
    if value is None or value == "":
        raise errors.invalid_request("Query parameter '%s' is required." % name)
    return value


def query_service_date(name="service_date"):
    return as_service_date(require_query(name), name)