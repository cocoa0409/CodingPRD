"""Request body parsing, shape validation, and pagination parsing.

Field spec format: { field_name: {"kind": ..., "required": bool, "enum": [...]} }
kind is one of: string, integer, number, boolean, array, object, date, any.
"""

from flask import request

from db import is_date_string
from errors import ApiError, ERR_INVALID_REQUEST


def get_body(allow_empty=True):
    """Parse the JSON request body.

    Returns {} when the body is absent/empty and allow_empty is True.
    Raises ERR_INVALID_REQUEST for unparseable JSON or non-object bodies.
    """
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        if allow_empty:
            return {}
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing request body")
    try:
        import json
        body = json.loads(raw)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Malformed JSON body")
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def _check_value(name, value, rule):
    kind = rule.get("kind", "any")
    if kind == "any":
        return
    if kind == "string":
        if not isinstance(value, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a string" % name)
    elif kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be an integer" % name)
    elif kind == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a number" % name)
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a boolean" % name)
    elif kind == "array":
        if not isinstance(value, list):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be an array" % name)
    elif kind == "object":
        if not isinstance(value, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be an object" % name)
    elif kind == "date":
        if not is_date_string(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a YYYY-MM-DD date" % name)
    enum = rule.get("enum")
    if enum is not None and value not in enum:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' has an invalid value" % name)


def check_shape(body, spec):
    """Reject unknown fields, missing required fields, bad types, bad enums."""
    for key in body:
        if key not in spec:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Unknown field: %s" % key)
    for name, rule in spec.items():
        if name not in body or body[name] is None:
            if rule.get("required"):
                raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)
            continue
        _check_value(name, body[name], rule)


def parse_pagination():
    """Parse limit/offset query params per scaffold pagination defaults."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset
