"""Header identity, role permission and payer-scope checks (PRD 2.1, 2.8 #1-#4)."""
from flask import request

from errors import fail
from store import db

ROLES = (
    "AgencyAdmin",
    "PayerReviewer",
    "CaseManager",
    "Scheduler",
    "ClinicalSupervisor",
    "Nurse",
)

AUTH_HEADER_USER = "X-User-ID"
AUTH_HEADER_ROLE = "X-User-Role"


def identity():
    """Check 1: both auth headers present and non-empty."""
    uid = request.headers.get(AUTH_HEADER_USER)
    role = request.headers.get(AUTH_HEADER_ROLE)
    if uid is None or role is None:
        fail("ERR_MISSING_AUTH_HEADER", "X-User-ID and X-User-Role are required.")
    uid = uid.strip()
    role = role.strip()
    if uid == "" or role == "":
        fail("ERR_MISSING_AUTH_HEADER", "X-User-ID and X-User-Role must be non-empty.")
    return uid, role


def require(*allowed):
    """Checks 1 and 2: identity, then a recognised role permitted on this endpoint."""
    uid, role = identity()
    if role not in ROLES or role not in allowed:
        fail("ERR_UNAUTHORIZED_ROLE", "Role %s may not perform this operation." % role)
    return uid, role


def payer_scope(role, uid, payer_id):
    """Check 4: a PayerReviewer acts only inside their own payer's scope."""
    if role != "PayerReviewer":
        return
    if payer_id is None:
        return
    if uid != payer_id:
        fail("ERR_PAYER_SCOPE_VIOLATION", "Acting payer does not own this authorization.")


def payer_scope_for_plan(role, uid, plan):
    """Plan-of-care scope: reached through the plan's patient or its authorizations."""
    if role != "PayerReviewer":
        return
    patient = db.patients.get(plan["patient_id"])
    if patient is not None and patient["payer_id"] == uid:
        return
    for auth in db.authorizations.values():
        if auth["plan_of_care_id"] == plan["id"] and auth["payer_id"] == uid:
            return
    fail("ERR_PAYER_SCOPE_VIOLATION", "Acting payer does not own this plan of care.")


def nurse_owns_shift(role, uid, shift):
    """Check 3: entity-backed Nurse ownership against the shift's ACTIVE assignment."""
    if role != "Nurse":
        return
    active = None
    for assignment in db.assignments.values():
        if assignment["shift_id"] == shift["id"] and assignment["status"] == "ACTIVE":
            if active is None or (assignment["created_at"], assignment["_seq"]) > (
                    active["created_at"], active["_seq"]):
                active = assignment
    if active is None:
        return
    if active["nurse_id"] != uid:
        fail("ERR_UNAUTHORIZED_ROLE", "This shift is not assigned to the acting nurse.")


def nurse_owns_timesheet(role, uid, timesheet):
    if role != "Nurse":
        return
    assignment = db.assignments.get(timesheet["shift_assignment_id"])
    if assignment is None:
        return
    if assignment["nurse_id"] != uid:
        fail("ERR_UNAUTHORIZED_ROLE", "This timesheet does not belong to the acting nurse.")
