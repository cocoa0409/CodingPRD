"""Sidewalk-closure permitting and the municipal review cycle (PRD 3.4)."""

from flask import Blueprint, request

from envelope import object_response
from errors import fail
from serialize import permit_out
from services import (authenticate, enforce_scope, filter_fk, lookup,
                      municipality_of_jobsite, windows_intersect)
from store import store
from validation import check_body, parse_pagination, plus_seconds, query_enum
from web import json_body, page

bp = Blueprint("permits", __name__)

READ_PERMIT_ROLES = ("PlatformAdmin", "MunicipalLiaison", "AccountManager",
                     "DispatchCoordinator", "CustomerContact")
PERMIT_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "DENIED", "CLOSED")
CLOSURE_TYPES = ("FULL", "PARTIAL", "LANE_SHIFT")
DECISIONS = ("APPROVE", "DENY", "REQUEST_REVISION")

PERMIT_SPEC = {
    "jobsite_id": {"req": True, "type": "string"},
    "closure_linear_feet": {"req": True, "type": "int", "gt": 0},
    "closure_start_utc": {"req": True, "type": "instant"},
    "closure_end_utc": {"req": True, "type": "instant"},
    "sidewalk_closure_type": {"req": True, "type": "string", "enum": CLOSURE_TYPES},
}

SUBMIT_SPEC = {
    "closure_linear_feet": {"type": "int", "gt": 0},
    "closure_start_utc": {"type": "instant"},
    "closure_end_utc": {"type": "instant"},
}

DECISION_SPEC = {
    "decision": {"req": True, "type": "string", "enum": DECISIONS},
    "reviewer_note": {"type": "string"},
    "required_change_summary": {"type": "string"},
}


@bp.post("/fence-rentals/permits")
def create_permit():
    authenticate(("MunicipalLiaison",))
    parsed = check_body(json_body(), PERMIT_SPEC)
    if parsed["closure_end_utc"] <= parsed["closure_start_utc"]:
        fail("ERR_VALIDATION", "closure_end_utc must be strictly after closure_start_utc.")
    jobsite = lookup("jobsites", parsed["jobsite_id"])
    row = store.new_row("permits")
    row.update({
        "jobsite_id": jobsite["id"],
        "closure_linear_feet": parsed["closure_linear_feet"],
        "closure_start_utc": parsed["closure_start_utc"],
        "closure_end_utc": parsed["closure_end_utc"],
        "sidewalk_closure_type": parsed["sidewalk_closure_type"],
        "status": "DRAFT",
        "revision_round": 0,
        "submitted_at_utc": None,
        "decided_at_utc": None,
        "reviewer_note": None,
        "required_change_summary": None,
    })
    store.permits[row["id"]] = row
    return object_response(permit_out(row), 201)


@bp.get("/fence-rentals/permits/<row_id>")
def read_permit(row_id):
    identity = authenticate(READ_PERMIT_ROLES)
    permit = lookup("permits", row_id)
    enforce_scope(identity, lookup("jobsites", permit["jobsite_id"])["customer_account_id"])
    return object_response(permit_out(permit), 200)


@bp.get("/fence-rentals/permits")
def list_permits():
    identity = authenticate(READ_PERMIT_ROLES)
    limit, offset = parse_pagination(request.args)
    status = query_enum(request.args, "status", PERMIT_STATUSES)
    jobsite = filter_fk(request.args, "jobsite_id", "jobsites")
    if jobsite is not None:
        enforce_scope(identity, jobsite["customer_account_id"])
    rows = []
    for permit in store.sorted_rows("permits"):
        if jobsite is not None and permit["jobsite_id"] != jobsite["id"]:
            continue
        if status is not None and permit["status"] != status:
            continue
        if identity.is_customer:
            owner = store.jobsites[permit["jobsite_id"]]["customer_account_id"]
            if owner != identity.user_id:
                continue
        rows.append(permit)
    return page(rows, permit_out, limit, offset)


def corridor_committed_feet(candidate, municipality_id, start, end):
    """PRD 3.4: the contending set is every OTHER SUBMITTED/APPROVED intersecting permit."""
    total = 0
    for other in store.sorted_rows("permits"):
        if other["id"] == candidate["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        jobsite = store.jobsites.get(other["jobsite_id"])
        if jobsite is None or jobsite["municipality_id"] != municipality_id:
            continue
        if windows_intersect(other["closure_start_utc"], other["closure_end_utc"], start, end):
            total += other["closure_linear_feet"]
    return total


@bp.post("/fence-rentals/permits/<row_id>/submit")
def submit_permit(row_id):
    authenticate(("MunicipalLiaison",))
    parsed = check_body(json_body(), SUBMIT_SPEC)
    permit = lookup("permits", row_id)
    start = parsed.get("closure_start_utc", permit["closure_start_utc"])
    end = parsed.get("closure_end_utc", permit["closure_end_utc"])
    feet = parsed.get("closure_linear_feet", permit["closure_linear_feet"])
    if end <= start:
        fail("ERR_VALIDATION", "closure_end_utc must be strictly after closure_start_utc.")
    if permit["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail("ERR_PERMIT_STATE",
             "Only a DRAFT or REVISION_REQUESTED application may be submitted.")

    jobsite = lookup("jobsites", permit["jobsite_id"])
    municipality = municipality_of_jobsite(jobsite)
    earliest = plus_seconds(store.clock, municipality["permit_lead_time_days"] * 86400)
    if start < earliest:                                                       # rung 13
        fail("ERR_PERMIT_LEAD_TIME_NOT_MET",
             "closure_start_utc does not clear the jurisdiction's permit lead time.")
    committed = corridor_committed_feet(permit, municipality["id"], start, end)
    if committed + feet > municipality["max_concurrent_closure_linear_feet"]:   # rung 17
        fail("ERR_CLOSURE_CAPACITY_EXCEEDED",
             "The jurisdiction's concurrent closure corridor would be exceeded.")
    if permit["status"] == "REVISION_REQUESTED":                               # rung 18
        if permit["revision_round"] > municipality["permit_review_rounds_allowed"]:
            fail("ERR_PERMIT_REVISION_LIMIT",
                 "The jurisdiction's review-round allowance is exhausted.")

    permit["closure_start_utc"] = start
    permit["closure_end_utc"] = end
    permit["closure_linear_feet"] = feet
    permit["status"] = "SUBMITTED"
    permit["submitted_at_utc"] = store.clock
    permit["required_change_summary"] = None
    store.touch(permit)
    return object_response(permit_out(permit), 200)


@bp.post("/fence-rentals/permits/<row_id>/municipal-decision")
def decide_permit(row_id):
    authenticate(("MunicipalLiaison",))
    parsed = check_body(json_body(), DECISION_SPEC)
    permit = lookup("permits", row_id)
    if permit["status"] != "SUBMITTED":
        fail("ERR_PERMIT_STATE", "Only a SUBMITTED application may receive a decision.")
    decision = parsed["decision"]
    if decision == "APPROVE":
        permit["status"] = "APPROVED"
        if "reviewer_note" in parsed:
            permit["reviewer_note"] = parsed["reviewer_note"]
    elif decision == "DENY":
        permit["status"] = "DENIED"
    else:
        permit["status"] = "REVISION_REQUESTED"
        permit["revision_round"] += 1
        if "reviewer_note" in parsed:
            permit["reviewer_note"] = parsed["reviewer_note"]
        if "required_change_summary" in parsed:
            permit["required_change_summary"] = parsed["required_change_summary"]
    permit["decided_at_utc"] = store.clock
    store.touch(permit)
    return object_response(permit_out(permit), 200)
