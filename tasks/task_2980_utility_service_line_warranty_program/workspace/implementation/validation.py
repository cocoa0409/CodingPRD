"""Request-shape validation: headers, roles, path ids, request bodies, filters.

These helpers cover tiers 1 to 4 of the refusal ladder (PRD 2.8): authentication,
role admission, body schema and pagination.  Everything after that is business
logic and lives in the route and service modules.
"""

import re

from flask import request

import config
import timeutil
from errors import ApiError

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

_MISSING = object()


def is_uuid(value):
    return isinstance(value, str) and bool(UUID_RE.match(value.strip()))


# ------------------------------------------------------------------ tier 1 & 2
def current_user_id():
    """The authenticated caller. Missing or empty identity is refused first."""
    raw = request.headers.get(config.HEADER_USER_ID)
    if raw is None or raw.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "A non-empty %s header is required" % config.HEADER_USER_ID)
    return raw.strip()


def current_role():
    raw = request.headers.get(config.HEADER_USER_ROLE)
    return raw.strip() if raw is not None else ""


def require_role(*allowed):
    """Admit only the roles this operation accepts; anything else is 403."""
    role = current_role()
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role %r may not perform this operation" % role)
    return role


def require_path_uuid(value):
    """A malformed identifier in a path segment is a schema failure, not a miss."""
    if not is_uuid(value):
        raise ApiError("ERR_INVALID_REQUEST", "Path identifier is not a well-formed UUID")
    return value


# ----------------------------------------------------------------- tier 3 body
class Field(object):
    def __init__(
        self,
        kind,
        required=False,
        enum=None,
        minimum=None,
        maximum=None,
        min_len=None,
        max_len=None,
        item_enum=None,
        distinct=False,
        nullable=False,
    ):
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.min_len = min_len
        self.max_len = max_len
        self.item_enum = item_enum
        self.distinct = distinct
        self.nullable = nullable


def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (name, why))


def raw_body():
    """The parsed JSON body as a dict; anything that is not an object is refused."""
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return parsed


def parse_body(specs):
    """Validate the body against a field spec map and return the parsed values."""
    body = raw_body()
    for key in body.keys():
        if key not in specs:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown field %r" % key)
    out = {}
    for name, spec in specs.items():
        if name not in body:
            if spec.required:
                _bad(name, "is required")
            out[name] = None
            continue
        value = body[name]
        if value is None:
            if spec.required or not spec.nullable:
                _bad(name, "may not be null")
            out[name] = None
            continue
        out[name] = _coerce(name, spec, value)
    return out


def _coerce(name, spec, value):
    kind = spec.kind
    if kind == "string":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        if spec.min_len is not None and len(value.strip()) < spec.min_len:
            _bad(name, "is shorter than the minimum length")
        if spec.min_len is not None and spec.min_len >= 1 and value.strip() == "":
            _bad(name, "may not be blank")
        if spec.max_len is not None and len(value) > spec.max_len:
            _bad(name, "is longer than the maximum length")
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "must be an integer")
        if spec.minimum is not None and value < spec.minimum:
            _bad(name, "is below the minimum accepted value")
        if spec.maximum is not None and value > spec.maximum:
            _bad(name, "is above the maximum accepted value")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec.enum:
            _bad(name, "is not one of %s" % ", ".join(spec.enum))
        return value
    if kind == "uuid":
        if not is_uuid(value):
            _bad(name, "must be a well-formed UUID")
        return value.strip()
    if kind == "date":
        parsed = timeutil.parse_date(value)
        if parsed is None:
            _bad(name, "must be a calendar date in YYYY-MM-DD form")
        return parsed
    if kind == "instant":
        parsed = timeutil.parse_instant(value)
        if parsed is None:
            _bad(name, "must be an ISO 8601 UTC instant")
        return parsed
    if kind == "enum_array":
        if not isinstance(value, list):
            _bad(name, "must be an array")
        if spec.min_len is not None and len(value) < spec.min_len:
            _bad(name, "may not be empty")
        for item in value:
            if not isinstance(item, str) or item not in spec.item_enum:
                _bad(name, "contains a value outside the permitted set")
        if spec.distinct and len(set(value)) != len(value):
            _bad(name, "must not repeat a value")
        return list(value)
    if kind == "state_code":
        if not isinstance(value, str) or not re.match(r"^[A-Z]{2}$", value):
            _bad(name, "must be exactly two uppercase letters")
        return value
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported field kind")


# -------------------------------------------------------------- list filters
def filter_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    value = raw.strip()
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s filter value %r is not recognised" % (name, value))
    return value


def filter_value(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw.strip()


def filter_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s filter must be true or false" % name)
