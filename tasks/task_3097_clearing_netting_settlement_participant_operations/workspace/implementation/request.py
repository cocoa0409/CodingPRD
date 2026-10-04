"""Request-body validation helpers.

PRD 2.12 places structural request validation (missing field, mistyped value,
unknown field -> ERR_INVALID_REQUEST) after the state and business-safety gates.
Every endpoint therefore resolves path identifiers, state and business rules
before it calls into this module.
"""

from flask import request

from errors import api_error, ERR_INVALID_REQUEST, ERR_IMMUTABLE_FIELD


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise api_error(ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return data


def check_unknown(data, allowed):
    unknown = [key for key in data if key not in allowed]
    if unknown:
        raise api_error(
            ERR_INVALID_REQUEST,
            "Unknown field(s) supplied: %s." % ", ".join(sorted(unknown)),
        )


def require(data, field, *, type_=None, enum=None, min_value=None):
    if field not in data or data[field] is None:
        raise api_error(ERR_INVALID_REQUEST, "The required field '%s' is missing." % field)
    value = data[field]
    _check_type(field, value, type_)
    if enum is not None and value not in enum:
        raise api_error(
            ERR_INVALID_REQUEST,
            "'%s' must be one of %s." % (field, ", ".join(enum)),
        )
    if min_value is not None and isinstance(value, int) and value < min_value:
        raise api_error(ERR_INVALID_REQUEST, "'%s' must be at least %d." % (field, min_value))
    return value


def optional(data, field, *, type_=None, enum=None, min_value=None, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    _check_type(field, value, type_)
    if enum is not None and value not in enum:
        raise api_error(
            ERR_INVALID_REQUEST,
            "'%s' must be one of %s." % (field, ", ".join(enum)),
        )
    if min_value is not None and isinstance(value, int) and value < min_value:
        raise api_error(ERR_INVALID_REQUEST, "'%s' must be at least %d." % (field, min_value))
    return value


def _check_type(field, value, type_):
    if type_ is None:
        return
    if type_ is str and not isinstance(value, str):
        raise api_error(ERR_INVALID_REQUEST, "'%s' must be a string." % field)
    if type_ is bool and not isinstance(value, bool):
        raise api_error(ERR_INVALID_REQUEST, "'%s' must be a boolean." % field)
    if type_ is int and (isinstance(value, bool) or not isinstance(value, int)):
        raise api_error(ERR_INVALID_REQUEST, "'%s' must be an integer." % field)


def reject_immutable(data, immutable_fields):
    """PRD 2.10: an update supplying a frozen field is refused ERR_IMMUTABLE_FIELD."""
    supplied = [field for field in immutable_fields if field in data and data[field] is not None]
    if supplied:
        raise api_error(
            ERR_IMMUTABLE_FIELD,
            "Field(s) immutable after creation: %s." % ", ".join(sorted(supplied)),
        )


def pagination():
    """PRD 2.3: limit defaults to 10, must be 1..100; offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise api_error(ERR_INVALID_REQUEST, "'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise api_error(ERR_INVALID_REQUEST, "'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise api_error(ERR_INVALID_REQUEST, "'offset' must be an integer.")
        if offset < 0:
            raise api_error(ERR_INVALID_REQUEST, "'offset' must not be negative.")
    return limit, offset


def query_flag(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw