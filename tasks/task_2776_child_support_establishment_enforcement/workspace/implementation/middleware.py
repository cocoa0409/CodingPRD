"""Auth header extraction, role recognition, RBAC and ownership (PRD 2.1)."""
from flask import g, request

import db
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = [
    "CaseWorker",
    "SupervisingAttorney",
    "FinanceOfficer",
    "EmployerAgent",
    "CustodialParty",
    "NoncustodialParty",
    "InterstateLiaison",
    "ProgramAdmin",
]

PARTY_ROLES = ("CustodialParty", "NoncustodialParty")


def authenticate(allowed_roles):
    """Priority 1-3: header presence, role recognition, role authorization."""
    user_id = request.headers.get(USER_ID_HEADER)
    user_role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "" or \
       user_role is None or str(user_role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    user_id = str(user_id).strip()
    user_role = str(user_role).strip()
    if user_role not in ROLES:
        raise ApiError("ERR_INVALID_ROLE")
    if allowed_roles and user_role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def user_id():
    return getattr(g, "user_id", None)


def user_role():
    return getattr(g, "user_role", None)


def require_case_party(case):
    """Priority 4: CustodialParty / NoncustodialParty must be on the case."""
    role = user_role()
    if role == "CustodialParty":
        if case["custodial_party_id"] != user_id():
            raise ApiError("ERR_NOT_CASE_PARTY")
    elif role == "NoncustodialParty":
        if case["noncustodial_party_id"] != user_id():
            raise ApiError("ERR_NOT_CASE_PARTY")


def require_participant_visibility(participant):
    """A party may read itself or a participant it shares a case with."""
    role = user_role()
    if role not in PARTY_ROLES:
        return
    uid = user_id()
    if participant["id"] == uid:
        return
    field = "custodial_party_id" if role == "CustodialParty" else "noncustodial_party_id"
    for case in db.cases.values():
        if case[field] == uid and participant["id"] in (
                case["custodial_party_id"], case["noncustodial_party_id"]):
            return
    raise ApiError("ERR_NOT_CASE_PARTY")


def require_employer_self(employer_id):
    """Priority 5: EmployerAgent acts only for its own employer row."""
    if user_role() == "EmployerAgent" and user_id() != employer_id:
        raise ApiError("ERR_NOT_IWO_EMPLOYER")
