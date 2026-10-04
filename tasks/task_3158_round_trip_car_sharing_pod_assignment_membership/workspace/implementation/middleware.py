"""Header authentication, role checking and request-input validation.

PRD §2.1 defines the two identity headers and the six declared roles; PRD §2.12
fixes the order in which the authentication, permission and ownership checks run
relative to everything else.
"""

from flask import request

from db import STORE, parse_ts  # noqa: F401  (STORE re-exported for handlers)
from errors import fail

ROLES = ("Anonymous", "Member", "PodOperator", "UniversityAccountAdmin",
         "FleetAdmin", "PlatformAdmin")

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"


def authenticate(allowed_roles):
    """Header presence + declared-role + role-permission checks (PRD §2.1/§2.12).

    Returns (identity, role). Raises ERR_UNAUTHENTICATED (401) when a header is
    missing or the role is not declared, and ERR_FORBIDDEN (403) when the
    declared role is not permitted for this operation.
    """
    role = request.headers.get(ROLE_HEADER)
    identity = request.headers.get(ID_HEADER)

    if (not role or not identity) and "Anonymous" in allowed_roles:
        # An Anonymous caller is an opaque, unauthenticated principal (PRD §2.1):
        # the application endpoint remains callable without an identity.
        return identity or "anonymous", "Anonymous"

    if not role or not identity or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")

    if role not in allowed_roles:
        fail("ERR_FORBIDDEN", "Role %s is not permitted for this operation." % role)
    return identity, role


def require_owner(identity, role, owner_member_id):
    """Member-scoped ownership test (PRD §2.1), refused with ERR_FORBIDDEN."""
    if role == "Member" and identity != owner_member_id:
        fail("ERR_FORBIDDEN", "A Member may only act on their own resources.")


def require_account_owner(identity, role, owner_account_id):
    """Account-scoped ownership test for UniversityAccountAdmin (PRD §2.1).

    A resource that references no Account at all (an individual, unsponsored
    membership carries account_id null) has no foreign key to compare.
    """
    if owner_account_id is None:
        return
    if role == "UniversityAccountAdmin" and identity != owner_account_id:
        fail("ERR_FORBIDDEN", "A UniversityAccountAdmin may only act on their own account.")


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def _type_ok(value, kind):
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    if kind == "datetime":
        try:
            parse_ts(value)
            return True
        except Exception:
            return False
    return True


def field(data, name, kind=None, required=False, default=None, enum=None,
          allow_null=False):
    """Field presence, declared-type and enum-membership check (PRD §2.12/§3.6)."""
    if name not in data or data.get(name) is None:
        if required and not allow_null:
            fail("ERR_INVALID_REQUEST", "Field %s is required." % name)
        return default
    value = data[name]
    if value is None:
        return None
    if kind and not _type_ok(value, kind):
        fail("ERR_INVALID_REQUEST", "Field %s has the wrong type." % name)
    if enum is not None and value not in enum:
        fail("ERR_INVALID_REQUEST", "Field %s carries a value outside its declared set." % name)
    return value


def pagination():
    """limit/offset per PRD §2.3: limit defaults to 10 and must be 1..100."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit must be an integer.")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100 inclusive.")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def query(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value