"""Authentication, role authorization, ownership and request-body validation.

Validation ordering (PRD 2.10 / scaffold Table 4) is enforced by the order in
which each resource module calls into this module.
"""

from flask import request

import store
from errors import ApiError

ROLES = {
    "CapacityPlanner": "opaque",
    "SupportAgent": "opaque",
    "FulfillmentOperator": "opaque",
    "PlatformAdmin": "opaque",
    "Subscriber": "entity_backed:Subscriber",
    "RetailPartner": "entity_backed:RetailPartner",
}

ROLE_TABLE = {
    "Subscriber": store.SUBSCRIBERS,
    "RetailPartner": store.PARTNERS,
}


def actor():
    """Priority 1: X-User-ID and X-User-Role present and resolvable."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role does not name a recognised role")
    identity = ROLES[role]
    if identity.startswith("entity_backed:"):
        table = ROLE_TABLE[identity.split(":", 1)[1]]
        if uid not in table:
            raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID does not name an existing instance")
    return uid, role


def require_role(uid, role, allowed):
    """Priority 2: the acting role is listed in the endpoint's roles."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role %s may not call this operation" % role)


def require_owner(uid, role, owner_id, label="resource"):
    """Priority 3: entity-backed roles must own the row they act on."""
    if role == "Subscriber":
        if owner_id != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "subscriber does not own this %s" % label)
    elif role == "RetailPartner":
        if owner_id != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "retail partner does not own this %s" % label)


def get_or_404(table_key, ident, error_id):
    """Priority 4: path identifiers resolve, left to right."""
    row = store.DB[table_key].get(ident)
    if row is None:
        raise ApiError(error_id)
    return row


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def check_fields(data, required, optional=None):
    """ERR_INVALID_REQUEST for a missing required or an unknown supplied field."""
    optional = list(optional or [])
    allowed = set(required) | set(optional)
    for name in required:
        if name not in data:
            raise ApiError("ERR_INVALID_REQUEST", "missing required field %s" % name)
    for name in data:
        if name not in allowed:
            raise ApiError("ERR_INVALID_REQUEST", "unknown field %s" % name)


def integer(data, name, error_id=None, required=True, default=None):
    if name not in data:
        if required:
            raise ApiError(error_id or "ERR_INVALID_REQUEST", "missing required field %s" % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(error_id or "ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return value


def string(data, name, error_id=None, required=True, default=None):
    if name not in data:
        if required:
            raise ApiError(error_id or "ERR_INVALID_REQUEST", "missing required field %s" % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        raise ApiError(error_id or "ERR_INVALID_REQUEST", "%s must be a string" % name)
    return value


def version_check(row, expected, error_id="ERR_STALE_VERSION"):
    """OCC: an omitted expectation skips the check entirely (PRD 2.7)."""
    if expected is None:
        return
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", "a version expectation must be an integer")
    if int(expected) != int(row.get("version", 1)):
        raise ApiError(error_id, "row version has advanced since it was observed")


def expected_field(data, name):
    """Read an optional *_version expectation; absent means None (skip)."""
    return data.get(name)