"""Auth header extraction, role checks, and Party/Advisor affiliation scoping
(PRD 2.1, 2.6; validation tiers 1-2 and the tier-5 read-perimeter rule)."""
from flask import request

from db import db
from errors import (
    raise_error,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_CASE_ACCESS_DENIED,
)

ALL_ROLES = {
    "TitleIXCoordinator",
    "Investigator",
    "DecisionMaker",
    "AppealOfficer",
    "Party",
    "Advisor",
    "CaseAdministrator",
}

# Six roles are entity-backed on PartyProfile; CaseAdministrator is opaque.
ENTITY_BACKED_ROLES = ALL_ROLES - {"CaseAdministrator"}

STAFF_READ_ROLES = [
    "TitleIXCoordinator", "CaseAdministrator", "Investigator", "DecisionMaker", "AppealOfficer",
]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Tier 1: authentication — headers present, role declared, entity-backed id resolves."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-Role must name a declared role and X-User-ID must be present")
    if role in ENTITY_BACKED_ROLES and user_id not in db["party_profiles"]:
        raise_error(ERR_UNAUTHENTICATED,
                    "entity-backed X-User-ID does not resolve to an existing PartyProfile")
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Tier 2: acting role must be on the endpoint's declared roles list."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller


def party_side_of(case, user_id):
    if user_id == case.get("complainant_id"):
        return "COMPLAINANT"
    if user_id == case.get("respondent_id"):
        return "RESPONDENT"
    return None


def check_case_read_access(caller: Caller, case):
    """Tier 5 read perimeter: Party readers must be a case party; Advisor readers
    must hold an appointment (any status) on the case. Staff read freely."""
    if caller.role == "Party":
        if party_side_of(case, caller.user_id) is None:
            raise_error(ERR_CASE_ACCESS_DENIED,
                        "Party reader is not affiliated with this case")
    elif caller.role == "Advisor":
        affiliated = any(
            a.get("case_id") == case["id"] and a.get("advisor_id") == caller.user_id
            for a in db["advisor_appointments"].values()
        )
        if not affiliated:
            raise_error(ERR_CASE_ACCESS_DENIED,
                        "Advisor reader holds no appointment on this case")
