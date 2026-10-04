"""Request-body well-formedness checks (validation ladder tier 4, PRD §2.10).

Required fields must be present, types and enum members must be valid, and
unknown fields are rejected — all as ERR_INVALID_REQUEST (400).
"""

import copy

import clock
from errors import ApiError, ERR_INVALID_REQUEST


def field(kind, required=False, enum=None, default=None, nullable=False):
    return {
        "kind": kind,
        "required": required,
        "enum": enum,
        "default": default,
        "nullable": nullable,
    }


def get_body():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def validate_body(data, spec):
    """Validate `data` against `spec`; return (values, provided_field_names).

    values includes defaults for omitted optional fields; provided names the
    fields actually present in the request body (used by PATCH-like endpoints).
    """
    for key in data:
        if key not in spec:
            raise ApiError(ERR_INVALID_REQUEST, "Unknown field: %s" % key, 400)
    values = {}
    provided = set()
    for name, f in spec.items():
        if name in data:
            _check(name, data[name], f)
            values[name] = data[name]
            provided.add(name)
        elif f["required"]:
            raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % name, 400)
        else:
            values[name] = copy.deepcopy(f["default"])
    return values, provided


def _check(name, value, f):
    if value is None:
        if f["nullable"]:
            return
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must not be null" % name, 400)
    kind = f["kind"]
    ok = True
    if kind == "string":
        ok = isinstance(value, str)
    elif kind == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif kind == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif kind == "boolean":
        ok = isinstance(value, bool)
    elif kind == "array":
        ok = isinstance(value, list)
    elif kind == "object":
        ok = isinstance(value, dict)
    elif kind == "datetime":
        ok = isinstance(value, str)
        if ok:
            try:
                clock.parse_iso(value)
            except Exception:
                ok = False
    elif kind == "enum":
        ok = isinstance(value, str) and value in (f["enum"] or [])
    if not ok:
        raise ApiError(ERR_INVALID_REQUEST,
                       "Field '%s' has an invalid value" % name, 400)


def check_string_array(name, value):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ApiError(ERR_INVALID_REQUEST,
                       "Field '%s' must be an array of strings" % name, 400)
