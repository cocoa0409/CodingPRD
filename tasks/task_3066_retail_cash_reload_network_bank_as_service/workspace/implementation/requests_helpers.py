"""Request payload helpers and pagination parsing."""

from flask import request

import errors
import response
import timeutil


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("The request body must be a JSON object.")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise errors.invalid_request("Field %r is required." % (field,))
    return data[field]


def optional(data, field, default=None):
    value = data.get(field)
    return default if value is None else value


def require_str(data, field):
    value = require(data, field)
    if not isinstance(value, str) or not value.strip():
        raise errors.invalid_request("Field %r must be a non-empty string." % (field,))
    return value


def require_int(data, field):
    value = require(data, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("Field %r must be an integer." % (field,))
    return value


def require_enum(data, field, allowed):
    value = require_str(data, field)
    if value not in allowed:
        raise errors.invalid_request(
            "Field %r must be one of %s." % (field, ", ".join(allowed))
        )
    return value


def optional_bool(data, field, default):
    value = data.get(field)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise errors.invalid_request("Field %r must be a boolean." % (field,))
    return value


def optional_int(data, field, default):
    value = data.get(field)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("Field %r must be an integer." % (field,))
    return value


def require_datetime(data, field):
    value = require(data, field)
    try:
        parsed = timeutil.parse(value)
    except (ValueError, TypeError):
        raise errors.invalid_request("Field %r must be an ISO 8601 instant." % (field,))
    if parsed is None:
        raise errors.invalid_request("Field %r must be an ISO 8601 instant." % (field,))
    return parsed


def require_array(data, field):
    value = require(data, field)
    if not isinstance(value, list):
        raise errors.invalid_request("Field %r must be an array." % (field,))
    return value


def pagination():
    """Parse limit/offset, which must fall inside the declared bounds."""
    raw_limit = request.args.get("limit", response.LIMIT_DEFAULT)
    raw_offset = request.args.get("offset", response.OFFSET_DEFAULT)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer.")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer.")
    if limit < response.LIMIT_MIN or limit > response.LIMIT_MAX:
        raise errors.invalid_request(
            "limit must be between %d and %d." % (response.LIMIT_MIN, response.LIMIT_MAX)
        )
    if offset < 0:
        raise errors.invalid_request("offset must be zero or greater.")
    return limit, offset


def page(rows, limit, offset):
    return rows[offset : offset + limit]