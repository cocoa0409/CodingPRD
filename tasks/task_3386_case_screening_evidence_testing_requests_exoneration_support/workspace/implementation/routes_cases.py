"""Case endpoints: read, OCC-guarded strategy update, lifecycle advance,
client-contact logging, and the case-scoped sub-collection lists."""

from flask import Blueprint, request

import db
from auth import STAFF_ROLES, require_ownership, require_roles
from clock import CLOCK, parse_iso
from db import touch
from envelope import ok
from errors import (
    ERR_ACTIVE_LAB_ANALYSES_EXIST,
    ERR_CASE_NOT_EXONERATED,
    ERR_CASE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_TRANSITION_EVENT,
    ERR_NO_PRESERVED_EVIDENCE,
    ERR_NO_TEST_RESULTS,
    ERR_OPEN_PETITIONS_EXIST,
    ERR_RELEASE_DATE_NOT_REACHED,
    ERR_RELEASE_NOT_READY,
    ERR_STALE_VERSION,
    raise_err,
)
from validation import (
    as_boolean,
    as_integer,
    as_string,
    body_json,
    opt_datetime,
    opt_str,
    paged_list,
    reject_unknown,
    req_choice,
    req_field,
    req_str,
)

bp = Blueprint("cases", __name__)

ADVANCE_EVENTS = (
    "BEGIN_INVESTIGATION", "BEGIN_TESTING", "BEGIN_LITIGATION",
    "UPDATE_RELEASE_CHECKLIST", "EXECUTE_RELEASE", "CLOSE",
)
RESOLUTIONS = ("UNSUBSTANTIATED", "EVIDENCE_LOST", "CLIENT_WITHDREW", "OTHER")
EXPECTATION_SETTINGS = ("CAUTIOUS", "NEUTRAL", "OPTIMISTIC")
_WORKING_STATUSES = ("OPEN", "INVESTIGATION", "TESTING", "LITIGATION")


def _case_item_ids(cid):
    return {i["id"] for i in db.evidence_items.values() if i["case_id"] == cid}


@bp.get("/cases/<cid>")
def get_case(cid):
    uid, role = require_roles(*STAFF_ROLES, "Client")
    case = db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    if role == "Client":
        ir = db.intake_requests.get(case["intake_request_id"])
        require_ownership(ir is not None and ir["client_id"] == uid)
    return ok(case)


@bp.put("/cases/<cid>")
def update_case(cid):
    require_roles("StaffAttorney")
    case = db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    body = body_json()
    # priority 3.6: OCC evaluated before any business logic / shape checks
    ver = body.get("expected_case_version")
    if isinstance(ver, int) and not isinstance(ver, bool):
        if ver != case["version"]:
            raise_err(ERR_STALE_VERSION,
                      "expected_case_version does not match the current case version")
    # priority 3.8: shape
    reject_unknown(body,
                   {"expected_case_version", "strategy_notes", "theory_of_case",
                    "assigned_attorney_id"})
    ver = as_integer(req_field(body, "expected_case_version"), "expected_case_version")
    if ver != case["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_case_version does not match the current case version")
    for field in ("strategy_notes", "theory_of_case", "assigned_attorney_id"):
        if field in body:
            case[field] = as_string(body[field], field)
    touch(case)
    return ok(case)


@bp.post("/cases/<cid>/advance")
def advance_case(cid):
    require_roles("StaffAttorney", "ManagingAttorney")
    case = db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"event", "resolution", "housing_arranged",
                          "id_documents_ready", "transportation_arranged",
                          "scheduled_release_date"})
    event = as_string(req_field(body, "event"), "event")
    if event not in ADVANCE_EVENTS:
        raise_err(ERR_INVALID_TRANSITION_EVENT,
                  "Unknown event for case advance: %s" % event)
    # event-specific shape (priority 3.8) before state checks
    resolution = None
    if event == "CLOSE":
        resolution = req_choice(body, "resolution", RESOLUTIONS)
    checklist = {}
    release_date = None
    if event == "UPDATE_RELEASE_CHECKLIST":
        for payload_key in ("housing_arranged", "id_documents_ready",
                            "transportation_arranged"):
            if payload_key in body:
                checklist[payload_key] = as_boolean(body[payload_key], payload_key)
        release_date = opt_datetime(body, "scheduled_release_date")

    if event == "BEGIN_INVESTIGATION":
        if case["status"] != "OPEN":
            raise_err(ERR_INVALID_STATE, "BEGIN_INVESTIGATION requires status OPEN")
        case["status"] = "INVESTIGATION"
        case["contact_interval_days"] = 90
    elif event == "BEGIN_TESTING":
        if case["status"] != "INVESTIGATION":
            raise_err(ERR_INVALID_STATE,
                      "BEGIN_TESTING requires status INVESTIGATION")
        if not any(i["case_id"] == cid and i["location_status"] == "CUSTODY_CONFIRMED"
                   for i in db.evidence_items.values()):
            raise_err(ERR_NO_PRESERVED_EVIDENCE,
                      "BEGIN_TESTING requires a CUSTODY_CONFIRMED evidence item")
        case["status"] = "TESTING"
        case["contact_interval_days"] = 60
    elif event == "BEGIN_LITIGATION":
        if case["status"] != "TESTING":
            raise_err(ERR_INVALID_STATE, "BEGIN_LITIGATION requires status TESTING")
        item_ids = _case_item_ids(cid)
        if not any(a["evidence_item_id"] in item_ids
                   and a["status"] in ("RESULT_RECORDED", "INTERPRETED")
                   for a in db.lab_analyses.values()):
            raise_err(ERR_NO_TEST_RESULTS,
                      "BEGIN_LITIGATION requires a RESULT_RECORDED or INTERPRETED "
                      "lab analysis")
        case["status"] = "LITIGATION"
        case["contact_interval_days"] = 30
    elif event == "CLOSE":
        if case["status"] not in _WORKING_STATUSES:
            raise_err(ERR_INVALID_STATE,
                      "CLOSE requires status OPEN, INVESTIGATION, TESTING or "
                      "LITIGATION")
        if any(p["case_id"] == cid and p["status"] in ("DRAFT", "FILED", "APPEAL_FILED")
               for p in db.legal_petitions.values()):
            raise_err(ERR_OPEN_PETITIONS_EXIST,
                      "CLOSE blocked: a legal petition is still open")
        item_ids = _case_item_ids(cid)
        if any(a["evidence_item_id"] in item_ids
               and a["status"] in ("SCHEDULED", "SAMPLE_SHIPPED")
               for a in db.lab_analyses.values()):
            raise_err(ERR_ACTIVE_LAB_ANALYSES_EXIST,
                      "CLOSE blocked: a lab analysis is still active")
        case["status"] = "CLOSED"
        case["resolution"] = resolution
        case["contact_interval_days"] = None
        case["contact_overdue"] = False
    elif event == "UPDATE_RELEASE_CHECKLIST":
        if case["status"] != "EXONERATED":
            raise_err(ERR_CASE_NOT_EXONERATED,
                      "UPDATE_RELEASE_CHECKLIST requires an EXONERATED case")
        if case["release_readiness"] not in ("PLANNING", "READY"):
            raise_err(ERR_INVALID_STATE,
                      "release_readiness must be PLANNING or READY")
        if "housing_arranged" in checklist:
            case["release_housing_ready"] = checklist["housing_arranged"]
        if "id_documents_ready" in checklist:
            case["release_id_documents_ready"] = checklist["id_documents_ready"]
        if "transportation_arranged" in checklist:
            case["release_transportation_ready"] = checklist["transportation_arranged"]
        if release_date is not None:
            case["scheduled_release_date"] = release_date
        case["release_readiness"] = (
            "READY" if (case["release_housing_ready"]
                        and case["release_id_documents_ready"]
                        and case["release_transportation_ready"])
            else "PLANNING")
    else:  # EXECUTE_RELEASE
        if case["status"] != "EXONERATED":
            raise_err(ERR_CASE_NOT_EXONERATED,
                      "EXECUTE_RELEASE requires an EXONERATED case")
        if case["release_readiness"] != "READY":
            raise_err(ERR_RELEASE_NOT_READY,
                      "EXECUTE_RELEASE requires release_readiness READY")
        if case["scheduled_release_date"] is not None:
            if CLOCK.now_dt() < parse_iso(case["scheduled_release_date"]):
                raise_err(ERR_RELEASE_DATE_NOT_REACHED,
                          "The scheduled release date has not been reached")
        case["release_readiness"] = "RELEASED"
    touch(case)
    return ok(case)


@bp.post("/cases/<cid>/log-contact")
def log_contact(cid):
    require_roles("ClientServicesAdvocate")
    case = db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    body = body_json()
    reject_unknown(body, {"channel", "expectation_setting", "summary"})
    req_str(body, "channel")
    expectation = req_choice(body, "expectation_setting", EXPECTATION_SETTINGS)
    opt_str(body, "summary")
    case["last_contact_at"] = CLOCK.stamp()
    case["contact_count"] += 1
    case["contact_overdue"] = False
    case["last_expectation_setting"] = expectation
    touch(case)
    return ok(case)


@bp.get("/cases/<cid>/evidence-items")
def list_case_evidence_items(cid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    items = [i for i in db.evidence_items.values() if i["case_id"] == cid]
    return paged_list(items, {
        "location_status": request.args.get("location_status"),
        "testing_status": request.args.get("testing_status"),
    })


@bp.get("/cases/<cid>/records-requests")
def list_case_records_requests(cid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    items = [r for r in db.records_requests.values() if r["case_id"] == cid]
    return paged_list(items, {"status": request.args.get("status")})


@bp.get("/cases/<cid>/testing-authorizations")
def list_case_testing_authorizations(cid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    items = [t for t in db.testing_authorizations.values() if t["case_id"] == cid]
    return paged_list(items, {
        "kind": request.args.get("kind"),
        "status": request.args.get("status"),
    })


@bp.get("/cases/<cid>/legal-petitions")
def list_case_legal_petitions(cid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    items = [p for p in db.legal_petitions.values() if p["case_id"] == cid]
    return paged_list(items, {
        "status": request.args.get("status"),
        "petition_type": request.args.get("petition_type"),
    })


@bp.get("/cases/<cid>/compensation-claims")
def list_case_compensation_claims(cid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    items = [c for c in db.compensation_claims.values() if c["case_id"] == cid]
    return paged_list(items, {"status": request.args.get("status")})


@bp.get("/cases/<cid>/reentry-referrals")
def list_case_reentry_referrals(cid):
    require_roles(*STAFF_ROLES)
    db.lookup(db.cases, cid, ERR_CASE_NOT_FOUND)
    items = [r for r in db.reentry_referrals.values() if r["case_id"] == cid]
    return paged_list(items, {
        "status": request.args.get("status"),
        "provider_id": request.args.get("provider_id"),
    })
