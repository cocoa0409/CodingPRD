"""Authentication and role authorization (validation priorities 1 and 2).

Every request carries X-User-ID and X-User-Role (PRD 2.1). Missing headers or
an undeclared role name -> ERR_UNAUTHENTICATED (401), evaluated before any
other check. A role not authorized for the endpoint (or for the field group
the request attempts to write) -> ERR_FORBIDDEN_ROLE (403).

ManufacturerRep is entity-backed: X-User-ID is the acting
ContractManufacturer's id and is compared against a resource's
contract_manufacturer_id for ownership.
"""
from flask import request

from core.constants import ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE
from core.errors import err


def authenticate():
    """Return (user_id, role); raise ERR_UNAUTHENTICATED otherwise."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ALL_ROLES:
        raise err(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must "
            "be a declared role",
        )
    return user_id, role


def require_role(role, *allowed):
    if role not in allowed:
        raise err(
            "ERR_FORBIDDEN_ROLE",
            "role %s is not authorized for this endpoint" % role,
        )


def forbid(message):
    raise err("ERR_FORBIDDEN_ROLE", message)
