"""Authentication, role authorization and entity-backed identity."""
from errors import err
from db import db, find

ROLES = ("PlatformOperator", "FinanceController", "ShareAdmin", "DataEngineer")
ENTITY_BACKED = {"ShareAdmin": "Account"}


def authenticate(headers):
    """Return (role, user_id).  Raises ERR_UNAUTHENTICATED."""
    role = headers.get("X-User-Role")
    user_id = headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "X-User-Role is missing or names an undeclared role.")
    entity = ENTITY_BACKED.get(role)
    if entity is not None:
        if not user_id:
            raise err("ERR_UNAUTHENTICATED",
                      "X-User-ID is required for this role.")
        if role == "ShareAdmin" and find(db.accounts, user_id) is None:
            raise err("ERR_UNAUTHENTICATED",
                      "X-User-ID does not name an existing Account.")
    return role, user_id


def authorize(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE",
                  "The acting role is not authorized for this operation.")
