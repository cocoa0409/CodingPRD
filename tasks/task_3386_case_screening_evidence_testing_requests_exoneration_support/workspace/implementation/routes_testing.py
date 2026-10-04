"""Testing authorization endpoints: create (kind-conditional gates),
kind-conditional advance, OCC-guarded amendments, and the authorized-analyses
sub-list."""

from flask import Blueprint

import db
from auth import STAFF_ROLES, require_roles
from calculations import refresh_testing_status
from db import touch
from envelope import ok
from errors import (
    ERR_CASE_NOT_FOUND,
    ERR_CASE_NOT_READY_FOR_TESTING_AUTH,
    ERR_EVIDENCE_ITEM_NOT_FOUND,
    ERR_EVIDENCE_NOT_IN_CUSTODY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_TRANSITION_EVENT,
    ERR_JURISDICTION_NO_TESTING_STATUTE,
    ERR_STALE_AUTHORIZATION_VERSION,
    ERR_TESTING_AUTHORIZATION_NOT_FOUND,
    raise_err,
)
from validation import (
    as_integer,
    as_string,
    body_json,
    opt_str,
    paged_list,
    reject_unknown,
    req_choice,
    req_field,
    req_str,
)

bp = Blueprint("testing_authorizations", __name__)

KINDS = ("AGREEMENT", "MOTION")
TEST_TYPES = ("DNA_STR", "DNA_TOUCH", "DNA_YSTR", "MITOCHONDRIAL_DNA", "SEROLOGY")
ADVANCE_EVENTS = ("PROPOSE", "COUNTER", "SIGN", "REJECT",
                  "FILE", "RECORD_RULING", "APPEAL")
AGREEMENT_EVENTS = ("PROPOSE", "COUNTER", "SIGN", "REJECT")
MOTION_EVENTS = ("FILE", "RECORD_RULING", "APPEAL")
RULINGS = ("GRANTED", "DENIED")
AMENDABLE_STATUSES = ("DRAFTED", "PROPOSED", "NEGOTIATING")


def _validate_test_types(value, name):
    if not isinstance(value, list):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an array" % name)
    for element in value:
        if not isinstance(element, str) or element not in TEST_TYPES:
            raise_err(ERR_INVALID_REQUEST,
                      "Field '%s' entries must be lab test types" % name)
    return value


def _case_jurisdiction(case):
    ir = db.intake_requests.get(case["intake_request_id"])
    if ir is None:
        return None
    return db.jurisdictions.get(ir["jurisdiction_id"])


@bp.post("/testing-authorizations")
def create_testing_authorization():
    uid, _role = require_roles("StaffAttorney")
    body = body_json()
    # priority 3: body-id existence in payload field order
    if "case_id" in body:
        db.lookup(db.cases, body.get("case_id"), ERR_CASE_NOT_FOUND)
    if "evidence_item_id" in body:
        db.lookup(db.evidence_items, body.get("evidence_item_id"),
                  ERR_EVIDENCE_ITEM_NOT_FOUND)
    # priority 3.8: shape
    reject_unknown(body, {"case_id", "evidence_item_id", "kind", "terms",
                          "proposed_test_types"})
    case_id = req_str(body, "case_id")
    evidence_item_id = req_str(body, "evidence_item_id")
    kind = req_choice(body, "kind", KINDS)
    terms = opt_str(body, "terms")
    proposed_test_types = None
    if "proposed_test_types" in body:
        proposed_test_types = _validate_test_types(body["proposed_test_types"],
                                                   "proposed_test_types")
    # priority 4.5: cross-entity state gates
    case = db.cases[case_id]
    if case["status"] not in ("INVESTIGATION", "TESTING"):
        raise_err(ERR_CASE_NOT_READY_FOR_TESTING_AUTH,
                  "TestingAuthorization creation requires the case to be in "
                  "INVESTIGATION or TESTING")
    item = db.evidence_items[evidence_item_id]
    if item["location_status"] != "CUSTODY_CONFIRMED":
        raise_err(ERR_EVIDENCE_NOT_IN_CUSTODY,
                  "The evidence item must be in CUSTODY_CONFIRMED")
    # priority 8(a): jurisdictional statute flag
    if kind == "MOTION":
        jurisdiction = _case_jurisdiction(case)
        if jurisdiction is None or not jurisdiction["has_post_conviction_dna_statute"]:
            raise_err(ERR_JURISDICTION_NO_TESTING_STATUTE,
                      "The jurisdiction has no post-conviction DNA testing statute")
    ta = db.new_entity()
    ta.update({
        "case_id": case_id,
        "evidence_item_id": evidence_item_id,
        "kind": kind,
        "status": "DRAFTED",
        "terms": terms,
        "proposed_test_types": proposed_test_types,
        "created_by_user_id": uid,
        "last_ruling": None,
    })
    db.testing_authorizations[ta["id"]] = ta
    return ok(ta, 201)


@bp.get("/testing-authorizations/<tid>")
def get_testing_authorization(tid):
    require_roles(*STAFF_ROLES)
    ta = db.lookup(db.testing_authorizations, tid, ERR_TESTING_AUTHORIZATION_NOT_FOUND)
    return ok(ta)


@bp.post("/testing-authorizations/<tid>/advance")
def advance_testing_authorization(tid):
    require_roles("StaffAttorney")
    ta = db.lookup(db.testing_authorizations, tid, ERR_TESTING_AUTHORIZATION_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event", "ruling"})
    event = as_string(req_field(body, "event"), "event")
    if event not in ADVANCE_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for testing-authorization advance: %s" % event)
    ruling = None
    if event == "RECORD_RULING":
        ruling = req_choice(body, "ruling", RULINGS)
    # priority 4: kind-conditional from-state legality. An agreement event on
    # a motion (or vice versa) is ERR_INVALID_STATE regardless of status.
    if ta["kind"] == "AGREEMENT" and event not in AGREEMENT_EVENTS:
        raise_err(ERR_INVALID_STATE,
                  "Event %s is not legal for kind=AGREEMENT" % event)
    if ta["kind"] == "MOTION" and event not in MOTION_EVENTS:
        raise_err(ERR_INVALID_STATE,
                  "Event %s is not legal for kind=MOTION" % event)
    status = ta["status"]
    item = db.evidence_items.get(ta["evidence_item_id"])
    if event == "PROPOSE":
        if status != "DRAFTED":
            raise_err(ERR_INVALID_STATE, "PROPOSE requires status DRAFTED")
        ta["status"] = "PROPOSED"
    elif event == "COUNTER":
        if status not in ("PROPOSED", "NEGOTIATING"):
            raise_err(ERR_INVALID_STATE,
                      "COUNTER requires status PROPOSED or NEGOTIATING")
        ta["status"] = "NEGOTIATING"
    elif event == "SIGN":
        if status not in ("PROPOSED", "NEGOTIATING"):
            raise_err(ERR_INVALID_STATE,
                      "SIGN requires status PROPOSED or NEGOTIATING")
        ta["status"] = "SIGNED"
        if item is not None and refresh_testing_status(item):
            touch(item)
    elif event == "REJECT":
        if status not in ("PROPOSED", "NEGOTIATING"):
            raise_err(ERR_INVALID_STATE,
                      "REJECT requires status PROPOSED or NEGOTIATING")
        ta["status"] = "REJECTED_BY_PROSECUTION"
    elif event == "FILE":
        if status != "DRAFTED":
            raise_err(ERR_INVALID_STATE, "FILE requires status DRAFTED")
        ta["status"] = "FILED"
    elif event == "RECORD_RULING":
        if status not in ("FILED", "APPEALED"):
            raise_err(ERR_INVALID_STATE,
                      "RECORD_RULING requires status FILED or APPEALED")
        ta["last_ruling"] = ruling
        ta["status"] = ruling
        if ruling == "GRANTED" and item is not None and refresh_testing_status(item):
            touch(item)
    else:  # APPEAL
        if status != "DENIED":
            raise_err(ERR_INVALID_STATE, "APPEAL requires status DENIED")
        ta["status"] = "APPEALED"
    touch(ta)
    return ok(ta)


@bp.post("/testing-authorizations/<tid>/amendments")
def amend_testing_authorization(tid):
    require_roles("StaffAttorney")
    ta = db.lookup(db.testing_authorizations, tid, ERR_TESTING_AUTHORIZATION_NOT_FOUND)
    body = body_json()
    # priority 3.6: OCC before any business logic / shape checks
    ver = body.get("expected_testing_authorization_version")
    if isinstance(ver, int) and not isinstance(ver, bool):
        if ver != ta["version"]:
            raise_err(ERR_STALE_AUTHORIZATION_VERSION,
                      "expected_testing_authorization_version does not match the "
                      "current authorization version")
    # priority 3.8: shape
    reject_unknown(body, {"expected_testing_authorization_version", "terms",
                          "proposed_test_types"})
    ver = as_integer(req_field(body, "expected_testing_authorization_version"),
                     "expected_testing_authorization_version")
    if ver != ta["version"]:
        raise_err(ERR_STALE_AUTHORIZATION_VERSION,
                  "expected_testing_authorization_version does not match the "
                  "current authorization version")
    terms = opt_str(body, "terms")
    proposed_test_types = None
    if "proposed_test_types" in body:
        proposed_test_types = _validate_test_types(body["proposed_test_types"],
                                                   "proposed_test_types")
    # amendments are AGREEMENT-only and only while negotiable
    if ta["kind"] != "AGREEMENT" or ta["status"] not in AMENDABLE_STATUSES:
        raise_err(ERR_INVALID_STATE,
                  "Amendments require kind=AGREEMENT and status DRAFTED, PROPOSED "
                  "or NEGOTIATING")
    if "terms" in body:
        ta["terms"] = terms
    if "proposed_test_types" in body:
        ta["proposed_test_types"] = proposed_test_types
    touch(ta)
    return ok(ta)


@bp.get("/testing-authorizations/<tid>/lab-analyses")
def list_testing_authorization_lab_analyses(tid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.testing_authorizations, tid, ERR_TESTING_AUTHORIZATION_NOT_FOUND)
    items = [a for a in db.lab_analyses.values() if a["authorization_id"] == tid]
    return paged_list(items, {})
