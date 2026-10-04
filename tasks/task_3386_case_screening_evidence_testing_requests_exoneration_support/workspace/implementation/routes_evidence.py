"""Evidence item and records request endpoints, including the records-response
reveal cascades (PRD 2.6 chain A)."""

from flask import Blueprint

import cascades
import db
from auth import STAFF_ROLES, require_roles
from calculations import refresh_testing_status
from db import touch
from envelope import ok
from errors import (
    ERR_CASE_NOT_FOUND,
    ERR_EVIDENCE_ITEM_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_TRANSITION_EVENT,
    ERR_RECORDS_REQUEST_NOT_FOUND,
    raise_err,
)
from validation import (
    as_choice,
    as_string,
    body_json,
    paged_list,
    reject_unknown,
    req_choice,
    req_field,
    req_int,
    req_str,
)

bp = Blueprint("evidence", __name__)

EVIDENCE_TYPES = ("BIOLOGICAL_SWAB", "CLOTHING", "WEAPON", "FINGERPRINT_CARD", "OTHER")
CUSTODIAN_TYPES = ("COURT_CLERK", "POLICE_PROPERTY", "CRIME_LAB", "MEDICAL_EXAMINER")
AGENCY_TYPES = ("COURT", "POLICE", "LABORATORY", "MEDICAL_EXAMINER")
ITEM_EVENTS = ("START_SEARCH", "MARK_LOCATED", "MARK_MISSING",
               "CONFIRM_CUSTODY", "VERIFY_DESTRUCTION")
RECORDS_EVENTS = ("SUBMIT", "RECORD_RESPONSE", "APPEAL")
RESPONSE_DISPOSITIONS = ("FULFILLED", "PARTIALLY_FULFILLED", "DENIED")
REVEAL_DISPOSITIONS = ("LOCATED", "DESTROYED", "MISSING")

# Legality of a reveal disposition against the item's current location_status.
REVEAL_LEGALITY = {
    "LOCATED": ("SEARCHING", "REPORTED_MISSING"),
    "DESTROYED": ("IDENTIFIED", "SEARCHING", "REPORTED_MISSING"),
    "MISSING": ("IDENTIFIED", "SEARCHING"),
}
REVEAL_TARGET = {
    "LOCATED": "LOCATED",
    "DESTROYED": "REPORTED_DESTROYED",
    "MISSING": "REPORTED_MISSING",
}


# ---------------------------------------------------------------------------
# Evidence items
# ---------------------------------------------------------------------------

@bp.post("/evidence-items")
def create_evidence_item():
    require_roles("EvidenceAnalyst")
    body = body_json()
    if "case_id" in body:
        db.lookup(db.cases, body.get("case_id"), ERR_CASE_NOT_FOUND)
    reject_unknown(body, {"case_id", "description", "evidence_type",
                          "custodian_type", "initial_sample_ng"})
    case_id = req_str(body, "case_id")
    description = req_str(body, "description")
    evidence_type = req_choice(body, "evidence_type", EVIDENCE_TYPES)
    custodian_type = req_choice(body, "custodian_type", CUSTODIAN_TYPES)
    initial_sample_ng = req_int(body, "initial_sample_ng", minimum=1)
    item = db.new_entity()
    item.update({
        "case_id": case_id,
        "description": description,
        "evidence_type": evidence_type,
        "custodian_type": custodian_type,
        "location_status": "IDENTIFIED",
        "testing_status": "UNTESTED",
        "initial_sample_ng": initial_sample_ng,
        "remaining_sample_ng": initial_sample_ng,
    })
    db.evidence_items[item["id"]] = item
    # arrival re-derives the owning case's evidence posture
    case = db.cases[case_id]
    cascades.refresh_case_posture_touch(case)
    return ok(item, 201)


@bp.get("/evidence-items/<iid>")
def get_evidence_item(iid):
    require_roles(*STAFF_ROLES)
    item = db.lookup(db.evidence_items, iid, ERR_EVIDENCE_ITEM_NOT_FOUND)
    return ok(item)


@bp.post("/evidence-items/<iid>/advance")
def advance_evidence_item(iid):
    require_roles("EvidenceAnalyst")
    item = db.lookup(db.evidence_items, iid, ERR_EVIDENCE_ITEM_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event"})
    event = as_string(req_field(body, "event"), "event")
    if event not in ITEM_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for evidence-item advance: %s" % event)
    loc = item["location_status"]
    if event == "START_SEARCH":
        if loc != "IDENTIFIED":
            raise_err(ERR_INVALID_STATE, "START_SEARCH requires IDENTIFIED")
        item["location_status"] = "SEARCHING"
    elif event == "MARK_LOCATED":
        if loc not in ("SEARCHING", "REPORTED_MISSING"):
            raise_err(ERR_INVALID_STATE,
                      "MARK_LOCATED requires SEARCHING or REPORTED_MISSING")
        item["location_status"] = "LOCATED"
    elif event == "MARK_MISSING":
        if loc not in ("IDENTIFIED", "SEARCHING"):
            raise_err(ERR_INVALID_STATE,
                      "MARK_MISSING requires IDENTIFIED or SEARCHING")
        item["location_status"] = "REPORTED_MISSING"
    elif event == "CONFIRM_CUSTODY":
        if loc != "LOCATED":
            raise_err(ERR_INVALID_STATE, "CONFIRM_CUSTODY requires LOCATED")
        item["location_status"] = "CUSTODY_CONFIRMED"
    else:  # VERIFY_DESTRUCTION
        if loc != "REPORTED_DESTROYED":
            raise_err(ERR_INVALID_STATE,
                      "VERIFY_DESTRUCTION requires REPORTED_DESTROYED")
        item["location_status"] = "DESTRUCTION_VERIFIED"
    touch(item)
    case = db.cases.get(item["case_id"])
    if case is not None:
        cascades.refresh_case_posture_touch(case)
    if event == "CONFIRM_CUSTODY":
        # custody confirmation also re-derives the testing dimension
        if refresh_testing_status(item):
            touch(item)
    return ok(item)


@bp.get("/evidence-items/<iid>/testing-authorizations")
def list_evidence_item_testing_authorizations(iid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.evidence_items, iid, ERR_EVIDENCE_ITEM_NOT_FOUND)
    items = [t for t in db.testing_authorizations.values()
             if t["evidence_item_id"] == iid]
    return paged_list(items, {})


@bp.get("/evidence-items/<iid>/lab-analyses")
def list_evidence_item_lab_analyses(iid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.evidence_items, iid, ERR_EVIDENCE_ITEM_NOT_FOUND)
    items = [a for a in db.lab_analyses.values() if a["evidence_item_id"] == iid]
    return paged_list(items, {})


# ---------------------------------------------------------------------------
# Records requests
# ---------------------------------------------------------------------------

@bp.post("/records-requests")
def create_records_request():
    require_roles("EvidenceAnalyst")
    body = body_json()
    if "case_id" in body:
        db.lookup(db.cases, body.get("case_id"), ERR_CASE_NOT_FOUND)
    reject_unknown(body, {"case_id", "agency_type", "agency_name", "request_summary"})
    rr = db.new_entity()
    rr.update({
        "case_id": req_str(body, "case_id"),
        "agency_type": req_choice(body, "agency_type", AGENCY_TYPES),
        "agency_name": req_str(body, "agency_name"),
        "request_summary": req_str(body, "request_summary"),
        "status": "DRAFT",
        "response_disposition": None,
        "items_revealed": [],
    })
    db.records_requests[rr["id"]] = rr
    return ok(rr, 201)


def _validate_reveals(body, disposition):
    """Shape-validate items_revealed for a RECORD_RESPONSE; returns a list of
    (evidence_item_id, disposition) pairs for fulfilling responses."""
    if disposition == "DENIED":
        revealed = body.get("items_revealed")
        if revealed:  # must be absent or empty on a denial
            raise_err(ERR_INVALID_REQUEST,
                      "A DENIED records response must not carry items_revealed")
        return []
    if "items_revealed" not in body or not isinstance(body["items_revealed"], list):
        raise_err(ERR_INVALID_REQUEST,
                  "A fulfilling records response must carry an items_revealed array")
    reveals = []
    for entry in body["items_revealed"]:
        if not isinstance(entry, dict) or set(entry.keys()) != {"evidence_item_id",
                                                                "disposition"}:
            raise_err(ERR_INVALID_REQUEST,
                      "Each items_revealed entry must be an object with exactly "
                      "evidence_item_id and disposition")
        iid = as_string(entry["evidence_item_id"], "evidence_item_id")
        disp = as_choice(entry["disposition"], "disposition", REVEAL_DISPOSITIONS)
        reveals.append((iid, disp))
    return reveals


@bp.post("/records-requests/<rid>/advance")
def advance_records_request(rid):
    require_roles("EvidenceAnalyst")
    rr = db.lookup(db.records_requests, rid, ERR_RECORDS_REQUEST_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event", "disposition", "items_revealed"})
    event = as_string(req_field(body, "event"), "event")
    if event not in RECORDS_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for records-request advance: %s" % event)
    if event == "SUBMIT":
        if rr["status"] != "DRAFT":
            raise_err(ERR_INVALID_STATE, "SUBMIT requires status DRAFT")
        rr["status"] = "SUBMITTED"
    elif event == "APPEAL":
        if rr["status"] != "DENIED":
            raise_err(ERR_INVALID_STATE, "APPEAL requires status DENIED")
        rr["status"] = "APPEALED"
    else:  # RECORD_RESPONSE
        disposition = req_choice(body, "disposition", RESPONSE_DISPOSITIONS)
        reveals = _validate_reveals(body, disposition)
        # existence of every referenced evidence item
        for iid, _disp in reveals:
            db.lookup(db.evidence_items, iid, ERR_EVIDENCE_ITEM_NOT_FOUND)
        if rr["status"] not in ("SUBMITTED", "APPEALED"):
            raise_err(ERR_INVALID_STATE,
                      "RECORD_RESPONSE requires status SUBMITTED or APPEALED")
        if disposition == "DENIED":
            rr["response_disposition"] = "DENIED"
            rr["status"] = "DENIED"
            touch(rr)
            cascades.apply_records_denial_cascade(rr)
            return ok(rr)
        # Pre-simulate the reveal sequence (applied in payload array order);
        # an illegal reveal rejects the whole response with no mutation.
        simulated = {}
        for iid, disp in reveals:
            item = db.evidence_items[iid]
            current = simulated.get(iid, item["location_status"])
            if current not in REVEAL_LEGALITY[disp]:
                raise_err(ERR_INVALID_STATE,
                          "Reveal disposition %s is illegal for an evidence item "
                          "in location_status %s" % (disp, current))
            simulated[iid] = REVEAL_TARGET[disp]
        # Commit: apply each reveal in order, running cascades per reveal.
        case = db.cases.get(rr["case_id"])
        for iid, disp in reveals:
            item = db.evidence_items[iid]
            item["location_status"] = REVEAL_TARGET[disp]
            touch(item)
            if disp == "DESTROYED":
                cascades.apply_destruction_cascade(item)
            elif case is not None:
                cascades.refresh_case_posture_touch(case)
        rr["response_disposition"] = disposition
        rr["items_revealed"] = body["items_revealed"]
        rr["status"] = disposition
        touch(rr)
        return ok(rr)
    touch(rr)
    return ok(rr)
