"""Authentication headers, roles and YouthMember ownership (PRD 2.1, ladder 1-3)."""

from flask import request

from errors import fail

OUTREACH_WORKER = "OutreachWorker"
SHELTER_CASE_MANAGER = "ShelterCaseManager"
REUNIFICATION_SPECIALIST = "ReunificationSpecialist"
TLP_COORDINATOR = "TlpCoordinator"
PROGRAM_ADMIN = "ProgramAdmin"
YOUTH_MEMBER = "YouthMember"

ROLES = (
    OUTREACH_WORKER,
    SHELTER_CASE_MANAGER,
    REUNIFICATION_SPECIALIST,
    TLP_COORDINATOR,
    PROGRAM_ADMIN,
    YOUTH_MEMBER,
)

STAFF_READ_ALL = (
    PROGRAM_ADMIN,
    SHELTER_CASE_MANAGER,
    REUNIFICATION_SPECIALIST,
    TLP_COORDINATOR,
    OUTREACH_WORKER,
)


def identity():
    """Ladder rule 1 - both headers present, non-empty, role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_MISSING_AUTH_HEADERS")
    if user_id.strip() == "" or role.strip() == "":
        fail("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        fail("ERR_MISSING_AUTH_HEADERS")
    return user_id, role


def require(*allowed):
    """Ladder rules 1 then 2. Returns (user_id, role)."""
    user_id, role = identity()
    if role not in allowed:
        fail("ERR_UNAUTHORIZED_ROLE")
    return user_id, role


def own_youth(user_id, role, youth_id):
    """Ladder rule 3 - a YouthMember acts only on its own resources.

    PRD 2.1: 'Any attempt by a YouthMember to reach another youth's data or another
    youth's vote is rejected with ERR_NOT_VOTE_OWNER (HTTP 403).'
    """
    if role == YOUTH_MEMBER and youth_id != user_id:
        fail("ERR_NOT_VOTE_OWNER")
