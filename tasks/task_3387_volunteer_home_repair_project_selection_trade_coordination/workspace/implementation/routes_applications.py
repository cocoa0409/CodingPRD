"""Homeowner applications: submission, verification, lifecycle, withdrawal
(PRD 3.2)."""
from flask import Blueprint, request

from db import STORES, new_record
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, req_str, req_int,
    req_bool, req_dt, raise_err, now_iso, parse_date, clock_date,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_NOT_OWNER, E_FORBIDDEN,
    E_APPLICATION_NOT_FOUND, E_CYCLE_NOT_FOUND, E_INCOME_LIMIT,
    E_VERIFICATION_INCOMPLETE,
)
from logic import (
    bump, income_eligible, compute_priority_score,
)
from cascades import cancel_project
from serializers import ser_application

bp = Blueprint("applications", __name__)

APPLICATION_STATUSES = (
    "SUBMITTED", "UNDER_VERIFICATION", "VERIFIED", "REJECTED", "ASSESSING",
    "ASSESSED", "CANDIDATE", "SELECTED", "DEFERRED", "WITHDRAWN", "FULFILLED",
)
HOMEOWNER_WITHDRAWABLE = ("UNDER_VERIFICATION", "VERIFIED", "CANDIDATE",
                          "DEFERRED", "SELECTED")
STAFF_WITHDRAWABLE = ("SUBMITTED",) + HOMEOWNER_WITHDRAWABLE


def _compute_is_older_adult(dob_value):
    """Age >= 62 by calendar birthday math against the logical clock date."""
    dob = parse_date(dob_value)
    today = clock_date()
    age = today.year - dob.year - (
        (today.month, today.day) < (dob.month, dob.day))
    return age >= 62


@bp.post("/rebuild/applications")
def create_application():
    require_roles("Anonymous", "AffiliateStaff")
    b = body()
    cycle_id = b.get("funding_cycle_id")
    if cycle_id is None:
        raise_err(E_INVALID_REQUEST, 400, "funding_cycle_id is required")
    get_or_404("funding_cycles", cycle_id, E_CYCLE_NOT_FOUND)
    dob = req_dt(b, "date_of_birth")
    rec = new_record("applications", {
        "funding_cycle_id": cycle_id,
        "homeowner_name": req_str(b, "homeowner_name"),
        "date_of_birth": dob,
        "household_size": req_int(b, "household_size", lo=1, hi=8),
        "household_income_cents": req_int(b, "household_income_cents", lo=0),
        "is_veteran": req_bool(b, "is_veteran"),
        "has_disability": req_bool(b, "has_disability"),
        "ownership_doc_provided": req_bool(b, "ownership_doc_provided"),
        "occupancy_doc_provided": req_bool(b, "occupancy_doc_provided"),
        "address": req_str(b, "address"),
        "status": "SUBMITTED",
        "is_older_adult": _compute_is_older_adult(dob),
        "priority_score": None,
        "decision_reason": None,
    }, now_iso)
    return ok_obj(ser_application(rec), 201)


@bp.get("/rebuild/applications")
def list_applications():
    # Deliberately NOT 'Any': the application list is staff-only (PRD 4).
    require_roles("AffiliateStaff", "PlatformAdmin", "Assessor")
    recs = list(STORES["applications"].values())
    fc = request.args.get("funding_cycle_id")
    if fc is not None:
        recs = [r for r in recs if r["funding_cycle_id"] == fc]
    st = request.args.get("status")
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_response(recs, ser_application)


@bp.get("/rebuild/applications/<applicationId>")
def get_application_route(applicationId):
    uid, role = require_roles("Any")
    if role == "Homeowner" and uid != applicationId:
        raise_err(E_NOT_OWNER, 403,
                  "a Homeowner may read only its own application")
    rec = get_or_404("applications", applicationId, E_APPLICATION_NOT_FOUND)
    return ok_obj(ser_application(rec))


def _staff_withdraw(rec):
    """Withdrawal side effects; SELECTED withdrawal cascades into the project."""
    if rec["status"] == "SELECTED":
        project = next(
            (p for p in STORES["projects"].values()
             if p["application_id"] == rec["id"]
             and p["status"] != "CANCELLED"), None)
        if project is not None:
            # The cascade drives the application to WITHDRAWN itself.
            cancel_project(project, "HOMEOWNER_WITHDRAWN")
        else:
            rec["status"] = "WITHDRAWN"
            bump(rec)
    else:
        rec["status"] = "WITHDRAWN"
        bump(rec)


@bp.patch("/rebuild/applications/<applicationId>")
def patch_application(applicationId):
    uid, role = require_roles("AffiliateStaff", "Homeowner")
    b = body()
    # Tier 3: entity-backed ownership + Homeowner field rule.
    if role == "Homeowner":
        if uid != applicationId:
            raise_err(E_NOT_OWNER, 403,
                      "a Homeowner may modify only its own application")
        if b.get("status") != "WITHDRAWN":
            raise_err(E_FORBIDDEN, 403,
                      "a Homeowner may only drive its application to "
                      "WITHDRAWN")
    rec = get_or_404("applications", applicationId, E_APPLICATION_NOT_FOUND)
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in APPLICATION_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(APPLICATION_STATUSES))

    if target == "WITHDRAWN":
        if role == "Homeowner":
            if rec["status"] not in HOMEOWNER_WITHDRAWABLE:
                raise_err(E_FORBIDDEN, 403,
                          "a Homeowner cannot withdraw from state %s"
                          % rec["status"])
            _staff_withdraw(rec)
        else:
            if rec["status"] not in STAFF_WITHDRAWABLE:
                raise_err(E_INVALID_STATE, 409,
                          "cannot withdraw from state %s" % rec["status"])
            _staff_withdraw(rec)
        return ok_obj(ser_application(rec))

    if role == "Homeowner":
        # Unreachable (field rule above), kept as a hard guard.
        raise_err(E_FORBIDDEN, 403, "Homeowner may only set WITHDRAWN")

    if target == "UNDER_VERIFICATION":
        if rec["status"] != "SUBMITTED":
            raise_err(E_INVALID_STATE, 409,
                      "application must be SUBMITTED")
        rec["status"] = "UNDER_VERIFICATION"
    elif target == "VERIFIED":
        if rec["status"] != "UNDER_VERIFICATION":
            raise_err(E_INVALID_STATE, 409,
                      "application must be UNDER_VERIFICATION")
        if not income_eligible(rec["household_income_cents"],
                               rec["household_size"]):
            raise_err(E_INCOME_LIMIT, 422,
                      "household income exceeds 80% of area median income")
        if not (rec["ownership_doc_provided"] and rec["occupancy_doc_provided"]):
            raise_err(E_VERIFICATION_INCOMPLETE, 422,
                      "ownership and occupancy documentation must be on file")
        rec["status"] = "VERIFIED"
        rec["priority_score"] = compute_priority_score(rec, None)
        rec["decision_reason"] = None
    elif target == "REJECTED":
        if rec["status"] != "UNDER_VERIFICATION":
            raise_err(E_INVALID_STATE, 409,
                      "application must be UNDER_VERIFICATION")
        reason = b.get("decision_reason")
        if reason is not None and not isinstance(reason, str):
            raise_err(E_INVALID_REQUEST, 400,
                      "decision_reason must be a string")
        rec["status"] = "REJECTED"
        rec["decision_reason"] = reason
    elif target == "DEFERRED":
        if rec["status"] != "CANDIDATE":
            raise_err(E_INVALID_STATE, 409,
                      "application must be CANDIDATE")
        reason = b.get("decision_reason")
        if reason is not None and not isinstance(reason, str):
            raise_err(E_INVALID_REQUEST, 400,
                      "decision_reason must be a string")
        rec["status"] = "DEFERRED"
        rec["decision_reason"] = reason
    elif target == "CANDIDATE":
        if rec["status"] == "ASSESSED":
            rec["status"] = "CANDIDATE"
            rec["decision_reason"] = None
        elif rec["status"] == "DEFERRED":
            cycle = STORES["funding_cycles"].get(rec["funding_cycle_id"])
            if cycle is None or cycle["status"] not in ("OPEN", "SELECTION_OPEN"):
                raise_err(E_INVALID_STATE, 409,
                          "cycle must be OPEN or SELECTION_OPEN to restore a "
                          "deferred application")
            rec["status"] = "CANDIDATE"
            rec["decision_reason"] = None
        else:
            raise_err(E_INVALID_STATE, 409,
                      "application must be ASSESSED or DEFERRED")
    else:
        # ASSESSING / ASSESSED / SELECTED / FULFILLED are system-driven.
        raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)
    bump(rec)
    return ok_obj(ser_application(rec))
