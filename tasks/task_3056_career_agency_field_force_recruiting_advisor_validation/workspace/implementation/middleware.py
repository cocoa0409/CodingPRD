"""Auth, RBAC and pagination helpers.

PRD §2.1: every request carries X-User-ID and X-User-Role. A missing or blank
header, or an unrecognised role, yields ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
(400). A recognised role acting outside its grant yields ERR_INSUFFICIENT_PERMISSIONS
(403). Both are evaluated before any resource lookup (PRD §2.10).
"""

from flask import request

from errors import (
    err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_PAGINATION_PARAMETERS,
    ERR_INVALID_REQUEST,
)

# PRD §2.1: the recognised roles, spelled exactly as they must appear.
ROLES = {
    "PlatformAdmin",
    "ManagingDirector",
    "DistrictDirector",
    "FinancialRep",
    "RecruitingOfficer",
    "LicensingCoordinator",
    "Any",
}

# PRD §2.1: identity scheme. ManagingDirector / DistrictDirector / FinancialRep
# carry X-User-ID as an Advisor id; the remaining roles are opaque operators.
ENTITY_BACKED_ROLES = {"ManagingDirector", "DistrictDirector", "FinancialRep"}


def actor():
    """Return (user_id, role) or raise the context-header error."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role headers are required")
    if not user_id.strip() or not role.strip():
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role must not be blank")
    role = role.strip()
    if role not in ROLES:
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "unknown role: %s" % role)
    return user_id.strip(), role


def require(role, allowed):
    """RBAC check (priority 2). `allowed` is the set of roles that hold the op.

    PRD §2.1: `Any` is the read-only projection shared by every authenticated
    role, so an operation whose grant includes `Any` is held by every role.
    """
    if "Any" in allowed:
        return
    if role not in allowed:
        raise err(ERR_INSUFFICIENT_PERMISSIONS,
                  "role %s does not hold this operation" % role)


def owner(role, user_id, expected_advisor_id):
    """Ownership-scoped check for the entity-backed roles (PRD §2.1)."""
    if role in ENTITY_BACKED_ROLES:
        if user_id != expected_advisor_id:
            raise err(ERR_INSUFFICIENT_PERMISSIONS,
                      "acting advisor does not own this resource")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3). limit default 10, range [1,100]; offset default 0 and
# must not be negative.
# ---------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_PAGINATION_PARAMETERS, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_PAGINATION_PARAMETERS,
                      "limit must lie between 1 and 100 inclusive")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_PAGINATION_PARAMETERS, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_PAGINATION_PARAMETERS,
                      "offset must not be negative")
    return limit, offset


def page(items, limit, offset):
    ordered = sorted(items, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    return ordered[offset:offset + limit]


# ---------------------------------------------------------------------------
# Body field helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def required(data, key):
    if key not in data or data[key] is None:
        raise err(ERR_INVALID_REQUEST, "missing required field: %s" % key)
    return data[key]


def require_fields(data, names):
    """Structural payload validity. PRD §2.10 evaluates this AFTER existence, so
    every body foreign key must already have been resolved when this is called."""
    for name in names:
        if name not in data or data[name] is None:
            raise err(ERR_INVALID_REQUEST, "missing required field: %s" % name)


def as_int(data, key, required_field=False, default=None):
    if key not in data or data[key] is None:
        if required_field:
            raise err(ERR_INVALID_REQUEST, "missing required field: %s" % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, "%s must be an integer" % key)
    return value


def as_str(data, key, required_field=False, default=None):
    if key not in data or data[key] is None:
        if required_field:
            raise err(ERR_INVALID_REQUEST, "missing required field: %s" % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "%s must be a string" % key)
    return value


def as_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, "%s must be a boolean" % key)
    return value


def as_enum(data, key, allowed, required_field=True, default=None):
    value = as_str(data, key, required_field=required_field, default=default)
    if value is None:
        return value
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, "%s is not a legal member" % key)
    return value