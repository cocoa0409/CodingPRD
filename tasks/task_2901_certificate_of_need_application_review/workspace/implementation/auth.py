"""Header authentication and role admissibility (PRD §2.1, order-of-evaluation ranks 1-2)."""

from flask import request

from errors import ApiError

ROLES = (
    "Applicant",
    "PublicParticipant",
    "IntakeAnalyst",
    "ReviewAnalyst",
    "DecisionOfficer",
    "AppealBoardMember",
    "ProgramAdmin",
)

ALL_ROLES = list(ROLES)
STAFF_AND_PARTIES = [
    "ProgramAdmin", "IntakeAnalyst", "ReviewAnalyst", "DecisionOfficer",
    "AppealBoardMember", "Applicant", "PublicParticipant",
]


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return ""
    return value.strip()


def identity(allowed_roles):
    """Rank 1: both headers present and non-empty. Rank 2: role declared and listed."""
    role = _header("X-User-Role")
    user_id = _header("X-User-ID")
    if not role or not user_id:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def clock_identity():
    """The logical-clock endpoint is exempt from the header-presence rule (PRD §2.4)."""
    role = _header("X-User-Role")
    if role and role != "ProgramAdmin":
        raise ApiError("ERR_UNAUTHORIZED")
    return _header("X-User-ID"), role or "ProgramAdmin"
