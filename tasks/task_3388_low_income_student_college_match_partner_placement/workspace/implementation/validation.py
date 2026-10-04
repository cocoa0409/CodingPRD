"""Request well-formedness validation -- global priority 1
(ERR_INVALID_REQUEST, HTTP 400): required fields present, correct types,
enum fields carrying a declared member, integer fields are integers.
"""
from flask import request

import clock
from errors import ApiError, ERR_INVALID_REQUEST

KIND_INT = "int"
KIND_STR = "str"
KIND_BOOL = "bool"
KIND_ENUM = "enum"
KIND_DATETIME = "datetime"


def _fail(message):
    raise ApiError(ERR_INVALID_REQUEST, message)


def get_body():
    """Return the JSON request body as a dict. Missing body is treated as an
    empty object (required-field checks then fire); a present body that is not
    a JSON object is malformed."""
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _fail("request body must be a JSON object")
    return data


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def parse_datetime_field(name, value):
    if not isinstance(value, str):
        _fail("field '%s' must be an ISO 8601 datetime string" % name)
    try:
        return clock.parse(value)
    except (ValueError, TypeError):
        _fail("field '%s' must be an ISO 8601 datetime string" % name)


def validate(body, spec):
    """Validate a request body against a field spec.

    spec: list of (name, kind, required, default, choices). A field present
    with a JSON null value is treated as absent. Returns a dict of validated
    values (datetimes parsed to aware UTC datetimes).
    """
    out = {}
    for name, kind, required, default, choices in spec:
        raw = body.get(name, None)
        if raw is None:
            if required:
                _fail("missing required field: '%s'" % name)
            out[name] = default
            continue
        if kind == KIND_INT:
            if not is_int(raw):
                _fail("field '%s' must be an integer" % name)
            out[name] = raw
        elif kind == KIND_STR:
            if not isinstance(raw, str):
                _fail("field '%s' must be a string" % name)
            out[name] = raw
        elif kind == KIND_BOOL:
            if not isinstance(raw, bool):
                _fail("field '%s' must be a boolean" % name)
            out[name] = raw
        elif kind == KIND_ENUM:
            if not isinstance(raw, str) or raw not in choices:
                _fail("field '%s' must be one of %s" % (name, sorted(choices)))
            out[name] = raw
        elif kind == KIND_DATETIME:
            out[name] = parse_datetime_field(name, raw)
        else:
            out[name] = raw
    return out


def pagination_params():
    """limit/offset query params (PRD section 2.3): default 10/0, limit
    clamped to [1, 100], offset clamped to >= 0. Non-integer values are
    malformed."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            _fail("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            _fail("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset
