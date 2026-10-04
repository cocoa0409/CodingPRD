"""Auth middleware (validation priorities 1 and 2).

Priority 1: X-User-Role header present and one of the declared roles;
X-User-ID present. Otherwise ERR_UNAUTHENTICATED (401).

Priority 2: role permitted for the endpoint, plus entity-backed identity
checks — Counselor/Advisor roles must reference an existing Staff member
whose staff_type matches the role; otherwise ERR_FORBIDDEN (403).
"""

from flask import request

from errors import raise_err
from store import STORE

ROLES = {
    "SystemAdmin",
    "RegistrarAdmin",
    "ComplianceOfficer",
    "FinancialAidOfficer",
    "Counselor",
    "Advisor",
    "Applicant",
}

# Entity-backed roles: role -> required Staff.staff_type
ENTITY_BACKED = {
    "Counselor": "COUNSELOR",
    "Advisor": "ADVISOR",
}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "missing or invalid X-User-Role / X-User-ID headers")
    if role in ENTITY_BACKED:
        staff = STORE.staff.get(uid)
        if staff is None or staff["staff_type"] != ENTITY_BACKED[role]:
            raise_err(
                "ERR_FORBIDDEN",
                "role %s requires X-User-ID of a Staff member with matching staff_type" % role,
            )
    return uid, role


def require_roles(*roles):
    """Authenticate and require the caller's role to be in `roles`."""
    uid, role = authenticate()
    if role not in roles:
        raise_err("ERR_FORBIDDEN", "role %s is not permitted for this operation" % role)
    return uid, role
