"""Authentication, role authorisation and programme scope (PRD 2.1, ladder 1/2/5)."""

from flask import g, request

from errors import ApiError

ROLES = (
    "PipelineDirector",
    "ProgramLead",
    "BreedingScientist",
    "TrialAgronomist",
    "DataAnalyst",
    "RegulatoryOfficer",
    "SupplyPlanner",
)
ALL_ROLES = list(ROLES)


def authenticate():
    """Ladder step 1. Runs for every endpoint."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or len(user_id.strip()) == 0 or role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Both X-User-ID and a recognised X-User-Role header are required.")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*allowed):
    """Ladder step 2."""
    if g.role not in allowed:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not permitted to perform this operation." % g.role)


def role():
    return g.role


def user_id():
    return g.user_id


def is_program_lead():
    return g.role == "ProgramLead"


def scope(*program_ids):
    """Ladder step 5: for a ProgramLead, X-User-ID must equal the owning
    programme id of every resource named in the path and in the body."""
    if g.role != "ProgramLead":
        return
    for pid in program_ids:
        if pid is None:
            continue
        if pid != g.user_id:
            raise ApiError(
                "ERR_PROGRAM_SCOPE_VIOLATION",
                "The acting ProgramLead does not own the programme this request names.")
