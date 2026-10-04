"""Identity extraction, role checking and RBAC (PRD §2.1, SCAFFOLD §1.4/§1.7)."""

from flask import request

from errors import fail

ROLES = (
    "Merchandiser",
    "Vendor",
    "InventoryPlanner",
    "CrossDockOperator",
    "CustomerService",
    "Customer",
    "Any",
)

# Every role except `Any` may act through a role list that contains it; `Any`
# in a role list means "any authenticated caller".
ANY = "Any"


def user_id():
    return request.headers.get("X-User-ID")


def user_role():
    return request.headers.get("X-User-Role")


def ensure_context():
    """Validations priority 1 — both headers present and the role recognised."""
    uid = user_id()
    role = user_role()
    if not uid or not role or role not in ROLES:
        fail("ERR_MISSING_USER_CONTEXT")


def current():
    """Return (uid, role) after the priority-1 check."""
    ensure_context()
    return user_id(), user_role()


def require_role(allowed):
    """Validations priority 2 — the role must be listed on the endpoint."""
    uid, role = current()
    if ANY in allowed:
        return uid, role
    if role not in allowed:
        fail("ERR_FORBIDDEN_FOR_ROLE")
    return uid, role


def require_owner(uid, role, expected_id, error_id="ERR_FORBIDDEN_FOR_ROLE"):
    """Validations priority 3 — entity-backed roles act only as themselves."""
    if role in ("Customer", "Vendor"):
        if expected_id is not None and uid != expected_id:
            fail(error_id)
        if expected_id is None:
            fail(error_id)