"""Intake request endpoints: create / list / read, screening advance,
submit-supplement, managing-attorney decide, waitlist activation, and the
created-case sub-list."""

from flask import Blueprint, request

import db
from auth import STAFF_ROLES, require_ownership, require_roles
from calculations import screening_score
from clock import CLOCK
from db import touch
from envelope import ok
from errors import (
    ERR_CLIENT_NOT_FOUND,
    ERR_DECISION_SELF_APPROVAL,
    ERR_INTAKE_REQUEST_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_TRANSITION_EVENT,
    ERR_JURISDICTION_NOT_FOUND,
    ERR_SCREENING_CRITERIA_NOT_MET,
    ERR_WAITLIST_EMPTY,
    raise_err,
)
from validation import (
    as_choice,
    as_string,
    body_json,
    opt_str,
    paged_list,
    reject_unknown,
    req_bool,
    req_choice,
    req_datetime,
    req_field,
    req_int,
    req_str,
)

bp = Blueprint("intake", __name__)

CLAIM_STRENGTHS = ("WEAK", "MODERATE", "STRONG", "COMPELLING")
EVIDENCE_POTENTIALS = ("NONE_KNOWN", "UNCERTAIN", "LIKELY_STORED", "CONFIRMED_STORED")
HEALTH_URGENCIES = ("NONE", "MODERATE", "CRITICAL")
RECOMMENDATIONS = ("ACCEPT", "REJECT", "WAITLIST")
DECISIONS = ("ACCEPTED", "REJECTED", "WAITLISTED")
ADVANCE_EVENTS = ("BEGIN_SCREENING", "REQUEST_MORE_INFO", "RECOMMEND")

_CREATE_FIELDS = {
    "client_id", "jurisdiction_id", "conviction_date", "conviction_summary",
    "claim_of_actual_innocence", "claim_strength", "evidence_potential",
    "years_served", "health_urgency", "expedited_review",
}


@bp.post("/intake-requests")
def create_intake_request():
    uid, role = require_roles("IntakeSpecialist", "Client")
    body = body_json()
    # priority 3: body-id existence, in payload field order
    if "client_id" in body:
        db.lookup(db.clients, body.get("client_id"), ERR_CLIENT_NOT_FOUND)
    if "jurisdiction_id" in body:
        db.lookup(db.jurisdictions, body.get("jurisdiction_id"), ERR_JURISDICTION_NOT_FOUND)
    # priority 3.4: a Client may only submit for itself
    if role == "Client":
        require_ownership("client_id" in body and body.get("client_id") == uid)
    # priority 3.8: request shape
    reject_unknown(body, _CREATE_FIELDS)
    client_id = req_str(body, "client_id")
    jurisdiction_id = req_str(body, "jurisdiction_id")
    conviction_date = req_datetime(body, "conviction_date")
    conviction_summary = req_str(body, "conviction_summary")
    claim_of_actual_innocence = req_bool(body, "claim_of_actual_innocence")
    claim_strength = req_choice(body, "claim_strength", CLAIM_STRENGTHS)
    evidence_potential = req_choice(body, "evidence_potential", EVIDENCE_POTENTIALS)
    years_served = req_int(body, "years_served", minimum=0)
    health_urgency = req_choice(body, "health_urgency", HEALTH_URGENCIES)
    expedited_review = False
    if "expedited_review" in body:
        expedited_review = req_bool(body, "expedited_review")
    ir = db.new_entity()
    ir.update({
        "client_id": client_id,
        "jurisdiction_id": jurisdiction_id,
        "conviction_date": conviction_date,
        "conviction_summary": conviction_summary,
        "claim_of_actual_innocence": claim_of_actual_innocence,
        "claim_strength": claim_strength,
        "evidence_potential": evidence_potential,
        "years_served": years_served,
        "health_urgency": health_urgency,
        "expedited_review": expedited_review,
        "status": "RECEIVED",
        "screening_score_standard": None,
        "screening_score_expedited": None,
        "waitlist_priority_score": None,
        "recommendation": None,
        "recommended_by_user_id": None,
        "decided_by_user_id": None,
        "decision": None,
        "decision_reason": None,
        "accepted_case_id": None,
        "supplement_notes": None,
    })
    db.intake_requests[ir["id"]] = ir
    return ok(ir, 201)


@bp.get("/intake-requests")
def list_intake_requests():
    require_roles(*STAFF_ROLES)
    items = list(db.intake_requests.values())
    return paged_list(items, {
        "status": request.args.get("status"),
        "client_id": request.args.get("client_id"),
        "jurisdiction_id": request.args.get("jurisdiction_id"),
    })


@bp.get("/intake-requests/<rid>")
def get_intake_request(rid):
    uid, role = require_roles(*STAFF_ROLES, "Client")
    ir = db.lookup(db.intake_requests, rid, ERR_INTAKE_REQUEST_NOT_FOUND)
    if role == "Client":
        require_ownership(ir["client_id"] == uid)
    return ok(ir)


@bp.post("/intake-requests/<rid>/advance")
def advance_intake_request(rid):
    uid, _role = require_roles("IntakeSpecialist")
    ir = db.lookup(db.intake_requests, rid, ERR_INTAKE_REQUEST_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event", "recommendation"})
    event = as_string(req_field(body, "event"), "event")
    if event not in ADVANCE_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for intake-request advance: %s" % event)
    recommendation = None
    if event == "RECOMMEND":
        recommendation = req_choice(body, "recommendation", RECOMMENDATIONS)
    if event == "BEGIN_SCREENING":
        if ir["status"] != "RECEIVED":
            raise_err(ERR_INVALID_STATE,
                      "BEGIN_SCREENING requires status RECEIVED")
        ir["status"] = "SCREENING"
    elif event == "REQUEST_MORE_INFO":
        if ir["status"] != "SCREENING":
            raise_err(ERR_INVALID_STATE,
                      "REQUEST_MORE_INFO requires status SCREENING")
        ir["status"] = "MORE_INFO_REQUESTED"
    else:  # RECOMMEND
        if ir["status"] != "SCREENING":
            raise_err(ERR_INVALID_STATE, "RECOMMEND requires status SCREENING")
        if recommendation == "ACCEPT" and not (
                ir["claim_of_actual_innocence"]
                and ir["evidence_potential"] in ("LIKELY_STORED", "CONFIRMED_STORED")):
            raise_err(ERR_SCREENING_CRITERIA_NOT_MET,
                      "RECOMMEND=ACCEPT requires claim_of_actual_innocence and "
                      "evidence_potential LIKELY_STORED or CONFIRMED_STORED")
        ir["recommendation"] = recommendation
        ir["recommended_by_user_id"] = uid
        ir["screening_score_standard"] = screening_score(ir, "STANDARD")
        ir["screening_score_expedited"] = screening_score(ir, "EXPEDITED")
        ir["status"] = "DECISION_PENDING"
    touch(ir)
    return ok(ir)


@bp.post("/intake-requests/<rid>/submit-supplement")
def submit_supplement(rid):
    uid, role = require_roles("Client", "IntakeSpecialist")
    ir = db.lookup(db.intake_requests, rid, ERR_INTAKE_REQUEST_NOT_FOUND)
    if role == "Client":
        require_ownership(ir["client_id"] == uid)
    body = body_json()
    reject_unknown(body, {"supplement_notes"})
    notes = req_str(body, "supplement_notes")
    if ir["status"] != "MORE_INFO_REQUESTED":
        raise_err(ERR_INVALID_STATE,
                  "submit-supplement requires status MORE_INFO_REQUESTED")
    ir["supplement_notes"] = notes
    ir["status"] = "SCREENING"
    touch(ir)
    return ok(ir)


@bp.post("/intake-requests/<rid>/decide")
def decide_intake_request(rid):
    uid, _role = require_roles("ManagingAttorney")
    ir = db.lookup(db.intake_requests, rid, ERR_INTAKE_REQUEST_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"decision", "assigned_attorney_id", "rejection_reason"})
    decision = req_choice(body, "decision", DECISIONS)
    assigned_attorney_id = opt_str(body, "assigned_attorney_id")
    rejection_reason = opt_str(body, "rejection_reason")
    if ir["status"] != "DECISION_PENDING":
        raise_err(ERR_INVALID_STATE, "decide requires status DECISION_PENDING")
    # segregation of duties (priority 5)
    if uid == ir["recommended_by_user_id"]:
        raise_err(ERR_DECISION_SELF_APPROVAL,
                  "The recommending specialist may not decide the request")
    ir["decision"] = decision
    ir["decided_by_user_id"] = uid
    # PRD 3.2: an optional rejection_reason is recorded on whichever branch
    # is taken.
    ir["decision_reason"] = rejection_reason
    if decision == "ACCEPTED":
        case = db.new_entity()
        case.update({
            "intake_request_id": ir["id"],
            "assigned_attorney_id": assigned_attorney_id,
            "status": "OPEN",
            "resolution": None,
            "evidence_posture": "NO_EVIDENCE",
            "destroyed_evidence_count": 0,
            "exculpatory_evidence_flag": False,
            "strategy_notes": None,
            "theory_of_case": None,
            "last_contact_at": CLOCK.stamp(),
            "contact_count": 0,
            "contact_overdue": False,
            "contact_interval_days": 90,
            "last_expectation_setting": None,
            "exoneration_date": None,
            "release_housing_ready": False,
            "release_id_documents_ready": False,
            "release_transportation_ready": False,
            "scheduled_release_date": None,
            "release_readiness": "NOT_APPLICABLE",
        })
        db.cases[case["id"]] = case
        ir["accepted_case_id"] = case["id"]
        ir["status"] = "ACCEPTED"
    elif decision == "REJECTED":
        ir["status"] = "REJECTED"
    else:  # WAITLISTED
        ir["waitlist_priority_score"] = (
            ir["screening_score_expedited"] if ir["expedited_review"]
            else ir["screening_score_standard"])
        ir["status"] = "WAITLISTED"
    touch(ir)
    return ok(ir)


@bp.post("/intake-requests/activate-waitlist-next")
def activate_waitlist_next():
    require_roles("ManagingAttorney")
    candidates = [ir for ir in db.intake_requests.values()
                  if ir["status"] == "WAITLISTED"]
    if not candidates:
        raise_err(ERR_WAITLIST_EMPTY, "No WAITLISTED intake request exists")
    # waitlist_priority_score DESC, tie-break created_at ASC; id never used.
    candidates.sort(key=lambda r: (-r["waitlist_priority_score"], r["created_at"]))
    selected = candidates[0]
    selected["status"] = "SCREENING"
    touch(selected)
    return ok(selected)


@bp.get("/intake-requests/<rid>/cases")
def list_intake_request_cases(rid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.intake_requests, rid, ERR_INTAKE_REQUEST_NOT_FOUND)
    items = [c for c in db.cases.values() if c["intake_request_id"] == rid]
    return paged_list(items, {})
