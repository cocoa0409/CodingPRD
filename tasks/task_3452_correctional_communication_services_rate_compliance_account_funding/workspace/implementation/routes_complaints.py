"""Complaint endpoints: file, get/list, start-review, resolve, escalate.

An AccountHolder may only file against the facility hosting their own
account and may only attach subjects belonging to that account
(PRD section 3.9). Escalation requires the complaint to have reached the
minimum age of ESCALATION_MIN_AGE_DAYS = 7 days; a complaint exactly seven
days old may be escalated.
"""

from datetime import timedelta

from flask import Blueprint

from core import (ALL_ROLES, CLOCK, DB, auth, body, err, list_response,
                  new_entity, ok_obj, pub, req_enum, req_str, opt_str, touch,
                  apply_filters)

bp = Blueprint("complaints", __name__)

CATEGORIES = ("RATE_DISPUTE", "FEE_DISCLOSURE", "SERVICE_QUALITY",
              "PRIVACY_CONCERN", "WRONGFUL_BLOCK")

ESCALATION_MIN_AGE_DAYS = 7


def complaint_or_404(complaint_id):
    complaint = DB.complaints.get(complaint_id)
    if complaint is None:
        err("ERR_COMPLAINT_NOT_FOUND", 404,
            "Complaint %s does not exist" % complaint_id)
    return complaint


@bp.post("/comm-services/complaints")
def create_complaint():
    user_id, role = auth(["AccountHolder", "FacilityStaff"])
    data = body()
    category = req_enum(data, "category", CATEGORIES)
    description = req_str(data, "description")
    facility_id = req_str(data, "facility_id")
    subject_account_id = opt_str(data, "subject_account_id")
    subject_call_id = opt_str(data, "subject_call_id")
    if role == "AccountHolder":
        # Tier 3 ownership: the caller's account scopes the facility and the
        # attachable subjects.
        own_account = DB.accounts.get(user_id)
        if own_account is None:
            err("ERR_ACCOUNT_NOT_FOUND", 404,
                "Account %s does not exist" % user_id)
        if own_account["facility_id"] != facility_id:
            err("ERR_NOT_RESOURCE_OWNER", 403,
                "AccountHolder may only file against the facility hosting "
                "their account")
        if subject_account_id is not None and subject_account_id != user_id:
            err("ERR_NOT_RESOURCE_OWNER", 403,
                "AccountHolder may only attach their own account as subject")
        if subject_call_id is not None:
            subject_call = DB.calls.get(subject_call_id)
            if subject_call is not None and subject_call["account_id"] != user_id:
                err("ERR_NOT_RESOURCE_OWNER", 403,
                    "AccountHolder may only attach calls of their own account")
    # Tier 5: body FKs in declared input order.
    if facility_id not in DB.facilities:
        err("ERR_FACILITY_NOT_FOUND", 404,
            "Facility %s does not exist" % facility_id)
    if subject_account_id is not None and subject_account_id not in DB.accounts:
        err("ERR_ACCOUNT_NOT_FOUND", 404,
            "Account %s does not exist" % subject_account_id)
    if subject_call_id is not None and subject_call_id not in DB.calls:
        err("ERR_CALL_NOT_FOUND", 404,
            "CallRecord %s does not exist" % subject_call_id)
    entity = new_entity()
    entity.update({
        "facility_id": facility_id,
        "subject_account_id": subject_account_id,
        "subject_call_id": subject_call_id,
        "category": category,
        "description": description,
        "status": "FILED",
        "filed_by_user_id": user_id,
        "filed_by_role": role,
        "reviewed_by_user_id": None,
        "resolution_note": None,
        "resolved_at": None,
        "escalated_at": None,
    })
    DB.complaints[entity["id"]] = entity
    return ok_obj(pub(entity), 201)


@bp.get("/comm-services/complaints/<complaint_id>")
def get_complaint(complaint_id):
    auth(ALL_ROLES)
    return ok_obj(pub(complaint_or_404(complaint_id)))


@bp.get("/comm-services/complaints")
def list_complaints():
    auth(ALL_ROLES)
    items = apply_filters(DB.complaints.values(),
                          ["facility_id", "subject_account_id",
                           "subject_call_id", "category", "status"])
    return list_response(items, pub)


@bp.post("/comm-services/complaints/<complaint_id>/start-review")
def start_review(complaint_id):
    user_id, role = auth(["ComplianceOfficer"])
    complaint = complaint_or_404(complaint_id)
    if complaint["status"] != "FILED":
        err("ERR_INVALID_STATE", 409,
            "Only a FILED complaint can be moved to UNDER_REVIEW")
    complaint["status"] = "UNDER_REVIEW"
    complaint["reviewed_by_user_id"] = user_id
    touch(complaint)
    return ok_obj(pub(complaint))


@bp.post("/comm-services/complaints/<complaint_id>/resolve")
def resolve_complaint(complaint_id):
    auth(["ComplianceOfficer"])
    data = body()
    # Tier 4 shape (mandatory note) precedes the tier 6 state gate.
    resolution_note = req_str(data, "resolution_note")
    complaint = complaint_or_404(complaint_id)
    if complaint["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409,
            "Only an UNDER_REVIEW complaint can be resolved")
    complaint["status"] = "RESOLVED"
    complaint["resolution_note"] = resolution_note
    complaint["resolved_at"] = CLOCK.now()
    touch(complaint)
    return ok_obj(pub(complaint))


@bp.post("/comm-services/complaints/<complaint_id>/escalate")
def escalate_complaint(complaint_id):
    auth(["ComplianceOfficer"])
    complaint = complaint_or_404(complaint_id)
    if complaint["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409,
            "Only an UNDER_REVIEW complaint can be escalated")
    if CLOCK.now() < complaint["created_at"] + timedelta(
            days=ESCALATION_MIN_AGE_DAYS):
        # Boundary: a complaint exactly ESCALATION_MIN_AGE_DAYS old may be
        # escalated.
        err("ERR_ESCALATION_TOO_EARLY", 409,
            "Complaint is younger than the minimum escalation age")
    complaint["status"] = "ESCALATED_TO_REGULATOR"
    complaint["escalated_at"] = CLOCK.now()
    touch(complaint)
    return ok_obj(pub(complaint))
