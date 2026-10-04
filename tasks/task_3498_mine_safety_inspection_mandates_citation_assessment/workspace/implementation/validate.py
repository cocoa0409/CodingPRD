"""Request validation: authentication, role gating, body shape (PRD 2.1/2.5).

Implements cascade tiers 1-3:
  tier 1 - both headers present and role is a declared role name -> 401
  tier 2 - role permitted on the endpoint                        -> 403
  tier 3 - body shape: required fields, no undeclared fields, enum
           membership, integer ranges                            -> 400
Also provides the tier-4 id resolver used by every route.
"""
from flask import g, request

import clock
from constants import ALL_ROLES
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)


def current_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return uid, role


def require_roles(*roles):
    """Tiers 1 and 2. Stashes the authenticated identity on flask.g."""
    uid, role = current_auth()
    if role not in roles:
        raise ApiError(
            ERR_UNAUTHORIZED,
            "role {} is not permitted on this endpoint".format(role),
        )
    g.uid = uid
    g.role = role
    return uid, role


def body_json():
    """Request JSON body as a dict; missing/empty body becomes {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def ensure_empty_body():
    """Endpoints declared with no inputs reject any supplied fields."""
    data = body_json()
    if data:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "this endpoint takes no request body fields",
        )


def _invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, message)


def parse_body(spec):
    """Validate the request body against a field spec.

    spec maps field name -> (kind, required[, extra]) where kind is one of
    "str", "int" (extra = inclusive minimum), "bool", "enum" (extra = allowed
    set), "datetime", "date", "str_list". Undeclared fields are rejected.
    Returns a dict of cleaned values (datetimes/dates parsed); absent optional
    fields map to None.
    """
    data = body_json()
    for key in data:
        if key not in spec:
            _invalid("undeclared field '{}'".format(key))
    out = {}
    for name, rule in spec.items():
        kind = rule[0]
        required = rule[1] if len(rule) > 1 else True
        extra = rule[2] if len(rule) > 2 else None
        present = name in data and data[name] is not None
        if not present:
            if required:
                _invalid("required field '{}' is missing".format(name))
            out[name] = None
            continue
        value = data[name]
        if kind == "str":
            if not isinstance(value, str):
                _invalid("field '{}' must be a string".format(name))
            out[name] = value
        elif kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                _invalid("field '{}' must be an integer".format(name))
            if extra is not None and value < extra:
                _invalid("field '{}' must be >= {}".format(name, extra))
            out[name] = value
        elif kind == "bool":
            if not isinstance(value, bool):
                _invalid("field '{}' must be a boolean".format(name))
            out[name] = value
        elif kind == "enum":
            if not isinstance(value, str) or value not in extra:
                _invalid("field '{}' must be one of {}".format(name, sorted(extra)))
            out[name] = value
        elif kind == "datetime":
            parsed = clock.parse_datetime(value)
            if parsed is None:
                _invalid("field '{}' must be an ISO 8601 datetime".format(name))
            out[name] = parsed
        elif kind == "date":
            parsed = clock.parse_date(value)
            if parsed is None:
                _invalid("field '{}' must be an ISO YYYY-MM-DD date".format(name))
            out[name] = parsed
        elif kind == "str_list":
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                _invalid("field '{}' must be an array of strings".format(name))
            out[name] = list(value)
        else:
            raise RuntimeError("unknown spec kind {}".format(kind))
    return out


def get_or_404(collection, entity_id, label="resource"):
    """Tier 4: resolve a path identifier or body foreign key."""
    entity = collection.get(entity_id)
    if entity is None:
        raise ApiError(ERR_NOT_FOUND, "{} '{}' was not found".format(label, entity_id))
    return entity
