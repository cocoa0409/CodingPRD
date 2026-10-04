"""Authentication, authorization, request-body validation and lookups.

Authentication is absolute and evaluated first (PRD 3.7): a request missing
X-User-ID / X-User-Role, carrying a malformed value, or naming a role outside
the six declared roles is rejected with ERR_UNAUTHENTICATED (401) before
anything else is examined.  Authorization follows: a well-formed caller
attempting a peer role's exclusive operation is rejected with
ERR_UNAUTHORIZED (403).
"""

from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    fail,
)

# The six declared roles, spelled exactly (PRD 2.1).
FLEET_OPERATIONS = "FleetOperations"
DEPOT_TECHNICIAN = "DepotTechnician"
REMOTE_ASSISTANCE_OPERATOR = "RemoteAssistanceOperator"
TERRITORY_PLANNER = "TerritoryPlanner"
SAFETY_REVIEWER = "SafetyReviewer"
MAPPING_ENGINEER = "MappingEngineer"

ALL_ROLES = (
    FLEET_OPERATIONS,
    DEPOT_TECHNICIAN,
    REMOTE_ASSISTANCE_OPERATOR,
    TERRITORY_PLANNER,
    SAFETY_REVIEWER,
    MAPPING_ENGINEER,
)

ANY = "*"

_ROLE_SPELLINGS = {role.lower(): role for role in ALL_ROLES}


class Caller:
    """The authenticated principal of one request."""

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(headers):
    """Resolve the caller from the two mandatory headers.

    Raises ERR_UNAUTHENTICATED for an absent, empty or unknown role, or for
    an absent/empty identifier.
    """
    role_raw = headers.get("X-User-Role")
    user_raw = headers.get("X-User-ID")
    if role_raw is None or user_raw is None:
        raise fail("ERR_UNAUTHENTICATED")
    role_text = str(role_raw).strip()
    user_text = str(user_raw).strip()
    if not role_text or not user_text:
        raise fail("ERR_UNAUTHENTICATED")
    canonical = _ROLE_SPELLINGS.get(role_text.lower())
    if canonical is None:
        raise fail("ERR_UNAUTHENTICATED")
    return Caller(user_text, canonical)


def authorize(caller, allowed):
    """Deny a caller whose role is not in `allowed` (ANY admits every role)."""
    if ANY in allowed:
        return
    if caller.role not in allowed:
        raise fail("ERR_UNAUTHORIZED")


# ─── request-body validation (ERR_INVALID_REQUEST, HTTP 400) ──────────────


def body_object(payload):
    """The request body must be a JSON object when one is expected."""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise fail(ERR_INVALID_REQUEST)
    return payload


def require_str(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise fail(ERR_INVALID_REQUEST)
    return value


def require_int(body, field, minimum=None):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise fail(ERR_INVALID_REQUEST)
    if minimum is not None and value < minimum:
        raise fail(ERR_INVALID_REQUEST)
    return value


def require_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        raise fail(ERR_INVALID_REQUEST)
    return value


def optional_int(body, field, default, minimum=None):
    """An optional numeric field with a declared server-side default."""
    if field not in body or body.get(field) is None:
        return default
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise fail(ERR_INVALID_REQUEST)
    if minimum is not None and value < minimum:
        raise fail(ERR_INVALID_REQUEST)
    return value


def optional_bool(body, field, default):
    """An optional boolean field with a declared server-side default."""
    if field not in body or body.get(field) is None:
        return default
    value = body.get(field)
    if not isinstance(value, bool):
        raise fail(ERR_INVALID_REQUEST)
    return value


def require_enum(body, field, allowed):
    value = body.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise fail(ERR_INVALID_REQUEST)
    return value


def optional_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    value = body.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise fail(ERR_INVALID_REQUEST)
    return value


def optional_str(body, field, default=None):
    """An optional string field; a present value must be a string."""
    if field not in body or body.get(field) is None:
        return default
    value = body.get(field)
    if not isinstance(value, str):
        raise fail(ERR_INVALID_REQUEST)
    return value


def require_instant(body, field):
    """A datetime field; stored canonically as ISO 8601 UTC."""
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise fail(ERR_INVALID_REQUEST)
    from db import _parse_utc  # local import keeps the module import-free of cycles

    try:
        _parse_utc(value)
    except (ValueError, TypeError):
        raise fail(ERR_INVALID_REQUEST)
    return value


# ─── existence lookups (validated strictly left to right) ──────────────────


def get_or_404(collection, identifier):
    """Resolve a path identifier or answer ERR_NOT_FOUND."""
    row = collection.get(identifier)
    if row is None:
        raise fail(ERR_NOT_FOUND)
    return row


def find_by(collection, predicate):
    """First row in insertion order matching `predicate`, else None."""
    for row in collection.values():
        if predicate(row):
            return row
    return None


def find_all(collection, predicate):
    """All rows in insertion order matching `predicate`."""
    return [row for row in collection.values() if predicate(row)]