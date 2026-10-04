"""Legal petition endpoints: drafting under jurisdictional gates, filing with
the statutory deadline, decision recording with the exoneration cascade, and
the appeal loop."""

from flask import Blueprint

import cascades
import db
from auth import require_roles
from calculations import anniversary_deadline
from clock import CLOCK
from db import touch
from envelope import ok
from errors import (
    ERR_CASE_NOT_FOUND,
    ERR_CASE_NOT_IN_LITIGATION,
    ERR_CLEMENCY_NOT_AVAILABLE,
    ERR_FILING_DEADLINE_EXCEEDED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_TRANSITION_EVENT,
    ERR_LEGAL_PETITION_NOT_FOUND,
    ERR_NOT_APPEALABLE,
    ERR_NO_EXCULPATORY_BASIS,
    raise_err,
)
from validation import (
    as_boolean,
    as_string,
    body_json,
    reject_unknown,
    req_choice,
    req_field,
    req_str,
)

bp = Blueprint("legal_petitions", __name__)

PETITION_TYPES = ("POST_CONVICTION", "DIRECT_APPEAL", "CLEMENCY", "HABEAS_CORPUS")
CLAIM_BASES = ("ACTUAL_INNOCENCE", "PROCEDURAL", "BOTH")
ADVANCE_EVENTS = ("FILE", "RECORD_DECISION", "APPEAL")
DECISIONS = ("GRANTED", "DENIED")


def _case_jurisdiction(case):
    ir = db.intake_requests.get(case["intake_request_id"])
    if ir is None:
        return None
    return db.jurisdictions.get(ir["jurisdiction_id"])


@bp.post("/legal-petitions")
def create_legal_petition():
    require_roles("StaffAttorney")
    body = body_json()
    if "case_id" in body:
        db.lookup(db.cases, body.get("case_id"), ERR_CASE_NOT_FOUND)
    reject_unknown(body, {"case_id", "petition_type", "court_name", "claim_basis"})
    case_id = req_str(body, "case_id")
    petition_type = req_choice(body, "petition_type", PETITION_TYPES)
    court_name = req_str(body, "court_name")
    claim_basis = req_choice(body, "claim_basis", CLAIM_BASES)
    case = db.cases[case_id]
    # priority 4.5: drafting requires the case to be in LITIGATION
    if case["status"] != "LITIGATION":
        raise_err(ERR_CASE_NOT_IN_LITIGATION,
                  "Legal petition creation requires the case to be in LITIGATION")
    # priority 8(a): jurisdictional statute flags and exculpatory-basis gate
    if petition_type == "CLEMENCY":
        jurisdiction = _case_jurisdiction(case)
        if jurisdiction is None or not jurisdiction["clemency_available"]:
            raise_err(ERR_CLEMENCY_NOT_AVAILABLE,
                      "Clemency petitions do not exist in this jurisdiction")
    if claim_basis in ("ACTUAL_INNOCENCE", "BOTH") and not case["exculpatory_evidence_flag"]:
        raise_err(ERR_NO_EXCULPATORY_BASIS,
                  "claim_basis %s requires exculpatory evidence on the case"
                  % claim_basis)
    petition = db.new_entity()
    petition.update({
        "case_id": case_id,
        "petition_type": petition_type,
        "court_name": court_name,
        "claim_basis": claim_basis,
        "status": "DRAFT",
        "decision_vacates_conviction": None,
        "filed_at": None,
        "decided_at": None,
    })
    db.legal_petitions[petition["id"]] = petition
    return ok(petition, 201)


@bp.post("/legal-petitions/<pid>/advance")
def advance_legal_petition(pid):
    require_roles("StaffAttorney")
    petition = db.lookup(db.legal_petitions, pid, ERR_LEGAL_PETITION_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event", "decision", "vacates_conviction"})
    event = as_string(req_field(body, "event"), "event")
    if event not in ADVANCE_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for legal-petition advance: %s" % event)
    decision = None
    vacates = False
    if event == "RECORD_DECISION":
        decision = req_choice(body, "decision", DECISIONS)
        if "vacates_conviction" in body and body["vacates_conviction"] is not None:
            vacates = as_boolean(body["vacates_conviction"], "vacates_conviction")
        if decision == "DENIED" and vacates:
            raise_err(ERR_INVALID_REQUEST,
                      "vacates_conviction may only be true when decision=GRANTED")
    status = petition["status"]
    case = db.cases.get(petition["case_id"])
    if event == "FILE":
        if status != "DRAFT":
            raise_err(ERR_INVALID_STATE, "FILE requires status DRAFT")
        if case is None or case["status"] != "LITIGATION":
            raise_err(ERR_CASE_NOT_IN_LITIGATION,
                      "Filing requires the case to be in LITIGATION")
        if petition["petition_type"] == "POST_CONVICTION":
            jurisdiction = _case_jurisdiction(case)
            deadline_years = (jurisdiction["post_conviction_deadline_years"]
                              if jurisdiction is not None else None)
            if deadline_years is not None:
                ir = db.intake_requests[case["intake_request_id"]]
                deadline = anniversary_deadline(ir["conviction_date"],
                                                deadline_years)
                # filing exactly on the anniversary is timely; strictly later
                # is rejected
                if CLOCK.now_dt() > deadline:
                    raise_err(ERR_FILING_DEADLINE_EXCEEDED,
                              "The post-conviction filing deadline has passed")
        petition["filed_at"] = CLOCK.stamp()
        petition["status"] = "FILED"
    elif event == "RECORD_DECISION":
        if status not in ("FILED", "APPEAL_FILED"):
            raise_err(ERR_INVALID_STATE,
                      "RECORD_DECISION requires status FILED or APPEAL_FILED")
        petition["decided_at"] = CLOCK.stamp()
        if decision == "GRANTED":
            petition["decision_vacates_conviction"] = vacates
            petition["status"] = "DECIDED_GRANTED"
            if vacates and case is not None:
                cascades.apply_exoneration_cascade(case, CLOCK.stamp())
        else:
            petition["decision_vacates_conviction"] = False
            petition["status"] = "DECIDED_DENIED"
    else:  # APPEAL
        if status != "DECIDED_DENIED":
            raise_err(ERR_INVALID_STATE, "APPEAL requires status DECIDED_DENIED")
        if petition["petition_type"] == "CLEMENCY":
            raise_err(ERR_NOT_APPEALABLE,
                      "Clemency denials are unappealable")
        petition["status"] = "APPEAL_FILED"
    touch(petition)
    return ok(petition)
