"""Auth header extraction, role checking and acting-user resolution (PRD 2.1)."""
from flask import request

from constants import ROLES
from db import users
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

# Per-role identity headers. PRD 2.1 states that for the five entity-backed roles
# X-User-ID is the id of the acting User row; these headers are the explicit
# form of that same identity and are preferred when present.
ROLE_ID_HEADERS = {
    "Physician": "X-Physician-Id",
    "Nurse": "X-Nurse-Id",
    "Counselor": "X-Counselor-Id",
    "MedicalDirector": "X-Medical-Director-Id",
    "RegulatoryAuditor": "X-Regulatory-Auditor-Id",
}

ROLE_TO_STAFF_ROLE = {
    "Physician": "PHYSICIAN",
    "Nurse": "NURSE",
    "Counselor": "COUNSELOR",
    "MedicalDirector": "MEDICAL_DIRECTOR",
    "RegulatoryAuditor": "REGULATOR",
}


class Actor(object):
    def __init__(self, raw_id, role):
        self.raw_id = raw_id
        self.role = role
        self.user = users.get(raw_id)
        self.resolved = self.user is not None
        if self.resolved:
            self.program_id = self.user.get("program_id")
        else:
            self.program_id = request.headers.get("X-Program-Id") or None

    @property
    def user_id(self):
        if self.resolved:
            return self.user.get("id")
        return self.raw_id

    @property
    def is_admin(self):
        return self.role == "ProgramAdministrator"


def acting_actor():
    """Extract and validate the acting user context (priority 1)."""
    user_id = request.headers.get(USER_ID_HEADER) or request.headers.get("x-user-id")
    role = request.headers.get(ROLE_HEADER) or request.headers.get("x-user-role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", "Missing X-User-ID header")
    if not role or str(role).strip() not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "Missing or invalid X-User-Role header",
        )
    caller = str(user_id).strip()
    role = str(role).strip()
    explicit = request.headers.get(ROLE_ID_HEADERS.get(role, ""))
    if explicit and str(explicit).strip():
        return Actor(str(explicit).strip(), role)
    return Actor(caller, role)


def require_role(actor, allowed):
    """Priority 2: the acting role must be listed for the operation."""
    if actor.role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Role %s is not permitted for this operation" % actor.role,
        )