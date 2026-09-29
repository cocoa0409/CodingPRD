"""Validation ladder rungs 5-9 (PRD 2.5): request shape, enums, windows, numeric bounds."""
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import raise_error

_MISSING = object()


class F(object):
    """One declared input field."""

    def __init__(self, name, jtype, required=False, enum=None, default=_MISSING,
                 nullable=False):
        self.name = name
        self.jtype = jtype
        self.required = required
        self.enum = enum
        self.default = default
        self.nullable = nullable


def _type_ok(value, jtype):
    if jtype == "string" or jtype == "datetime":
        return isinstance(value, str)
    if jtype == "boolean":
        return isinstance(value, bool)
    if jtype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if jtype == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if jtype == "object":
        return isinstance(value, dict)
    if jtype == "array":
        return isinstance(value, list)
    return True


def raw_body():
    body = request.get_json(silent=True)
    if body is None:
        if request.get_data(as_text=True).strip():
            # A body was sent but it is not parseable JSON.
            raise_error("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        return {}
    if not isinstance(body, dict):
        raise_error("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def body(spec):
    """Rungs 5 and 6: shape then enum membership."""
    payload = raw_body()
    allowed = dict((f.name, f) for f in spec)

    for key in payload.keys():
        if key not in allowed:
            raise_error("ERR_INVALID_REQUEST", "Unknown field '%s'." % key)

    # rung 5: presence, non-null, declared JSON type
    for field in spec:
        if field.name not in payload:
            if field.required:
                raise_error("ERR_INVALID_REQUEST",
                            "Field '%s' is required." % field.name)
            continue
        value = payload[field.name]
        if value is None:
            if field.required and not field.nullable:
                raise_error("ERR_INVALID_REQUEST",
                            "Field '%s' may not be null." % field.name)
            continue
        if not _type_ok(value, field.jtype):
            raise_error("ERR_INVALID_REQUEST",
                        "Field '%s' must be of type %s." % (field.name, field.jtype))

    # rung 6: enum membership
    for field in spec:
        if field.enum is None:
            continue
        if field.name not in payload:
            continue
        value = payload[field.name]
        if value is None:
            continue
        if value not in field.enum:
            raise_error("ERR_INVALID_ENUM_VALUE",
                        "Field '%s' must be one of %s." % (field.name, ", ".join(field.enum)))

    result = {}
    for field in spec:
        if field.name in payload and payload[field.name] is not None:
            result[field.name] = payload[field.name]
        elif field.name in payload and field.nullable:
            result[field.name] = None
        elif field.default is not _MISSING:
            result[field.name] = field.default
        else:
            result[field.name] = None
    return result


def enum_filter(args, name, members):
    """Rung 6 for enum-valued query filters on list endpoints."""
    value = args.get(name)
    if value is None:
        return None
    if value not in members:
        raise_error("ERR_INVALID_ENUM_VALUE",
                    "Filter '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def window(data, start_key="window_start", end_key="window_end"):
    """Rung 8: both instants parse and the end is strictly after the start."""
    start = db.parse_iso(data.get(start_key))
    end = db.parse_iso(data.get(end_key))
    if start is None or end is None or end <= start:
        raise_error("ERR_INVALID_WINDOW")
    return start, end


def instant(value, message=None):
    """Rung 9: a non-window datetime input must still parse."""
    parsed = db.parse_iso(value)
    if parsed is None:
        raise_error("ERR_INVALID_REQUEST", message or "Value is not an ISO-8601 instant.")
    return parsed


def require(condition, message=None):
    if not condition:
        raise_error("ERR_INVALID_REQUEST", message)


def at_most_one_decimal(value):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return False
    exponent = parsed.normalize().as_tuple().exponent
    return exponent >= -1
