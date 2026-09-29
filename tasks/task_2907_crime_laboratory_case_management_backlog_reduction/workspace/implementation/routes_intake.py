"""Case intake, priority overrides, discovery and evidence custody."""
from decimal import Decimal

from flask import Blueprint

import serialize
import services as S
from auth import CASE_MANAGER, EVIDENCE_TECHNICIAN, LAB_DIRECTOR, endpoint
from envelope import object_response
from errors import ApiError
from store import db, new_row, touch
from util import add_days, dec, q2
from validate import Field, parse

bp = Blueprint("intake", __name__)

CASE_CREATE_FIELDS = [
    Field("agency_case_number", "string", required=True,
          min_length=1, max_length=40),
    Field("submitting_agency", "string", required=True,
          min_length=1, max_length=80),
    Field("offense_category", "enum", required=True,
          choices=S.OFFENSE_CATEGORIES),
    Field("suspect_in_custody", "boolean", default=False),
    Field("statutory_deadline_utc", "instant", default=None, nullable=True),
    Field("court_date_utc", "instant", default=None, nullable=True),
]


@bp.route("/lab/cases", methods=["POST"])
@endpoint(EVIDENCE_TECHNICIAN)
def create_case():
    body = parse(CASE_CREATE_FIELDS)
    for existing in db.cases.values():
        if (existing["submitting_agency"] == body["submitting_agency"]
                and existing["agency_case_number"] == body["agency_case_number"]):
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    row = new_row()
    row.update({
        "agency_case_number": body["agency_case_number"],
        "submitting_agency": body["submitting_agency"],
        "offense_category": body["offense_category"],
        "violent_crime_flag": body["offense_category"] in S.VIOLENT_CATEGORIES,
        "suspect_in_custody": body["suspect_in_custody"],
        "statutory_deadline_utc": body["statutory_deadline_utc"],
        "court_date_utc": body["court_date_utc"],
        "received_at_utc": db.now(),
        "priority_override_class": None,
        "priority_override_reason": None,
        "workflow_status": "SUBMITTED",
        "discovery_status": "NONE",
        "discovery_requested_at_utc": None,
        "discovery_due_utc": None,
        "discovery_requesting_party": None,
        "open_examination_request_count": 0,
        "released_examination_request_count": 0,
        "accepted_at_utc": None,
        "reported_at_utc": None,
        "gross_turnaround_days": None,
        "net_turnaround_days": None,
        "rejection_reason": None,
    })
    row["priority_score"] = S.compute_priority_score(row)
    row["priority_class"] = S.derive_priority_class(row)
    db.cases[row["id"]] = row
    return object_response(serialize.case(row), 201)


@bp.route("/lab/cases/<case_id>/accept", methods=["POST"])
@endpoint(EVIDENCE_TECHNICIAN)
def accept_case(case_id):
    case = S.find_case(case_id)
    parse([Field("acceptance_note", "string")])
    if case["workflow_status"] != "SUBMITTED":
        raise ApiError("ERR_CASE_INVALID_STATE")
    items = S.items_of_case(case["id"])
    if not items:
        raise ApiError("ERR_CASE_HAS_NO_EVIDENCE")
    if any(not item["seal_intact"] for item in items):
        raise ApiError("ERR_EVIDENCE_SEAL_BROKEN")
    case["workflow_status"] = "ACCEPTED"
    case["accepted_at_utc"] = db.now()
    touch(case)
    return object_response(serialize.case(case), 200)


@bp.route("/lab/cases/<case_id>/reject", methods=["POST"])
@endpoint(EVIDENCE_TECHNICIAN)
def reject_case(case_id):
    case = S.find_case(case_id)
    body = parse([
        Field("rejection_reason", "string", required=True),
    ])
    if case["workflow_status"] != "SUBMITTED":
        raise ApiError("ERR_CASE_INVALID_STATE")
    case["workflow_status"] = "REJECTED"
    case["rejection_reason"] = body["rejection_reason"]
    touch(case)
    for item in S.items_of_case(case["id"]):
        if item["custody_status"] == "IN_VAULT":
            item["custody_status"] = "RETURNED"
            touch(item)
    return object_response(serialize.case(case), 200)


@bp.route("/lab/cases/<case_id>/priority-overrides", methods=["POST"])
@endpoint(LAB_DIRECTOR)
def override_case_priority(case_id):
    case = S.find_case(case_id)
    body = parse([
        Field("priority_override_class", "enum", required=True,
              choices=S.PRIORITY_CLASSES),
        Field("priority_override_reason", "string", required=True),
        Field("expected_case_version", "integer", required=True),
    ])
    if body["expected_case_version"] != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")
    case["priority_override_class"] = body["priority_override_class"]
    case["priority_override_reason"] = body["priority_override_reason"]
    case["priority_class"] = S.derive_priority_class(case)
    touch(case)
    return object_response(serialize.case(case), 200)


@bp.route("/lab/cases/<case_id>/report", methods=["POST"])
@endpoint(CASE_MANAGER)
def report_case(case_id):
    case = S.find_case(case_id)
    parse([Field("report_note", "string")])
    if case["workflow_status"] != "IN_PROGRESS":
        raise ApiError("ERR_CASE_INVALID_STATE")
    if case["open_examination_request_count"] != 0:
        raise ApiError("ERR_CASE_HAS_OPEN_REQUESTS")
    if case["released_examination_request_count"] < 1:
        raise ApiError("ERR_CASE_HAS_NO_RELEASED_REQUEST")
    case["workflow_status"] = "REPORTED"
    case["reported_at_utc"] = db.now()
    gross, net = S.compute_turnaround(case)
    case["gross_turnaround_days"] = gross
    case["net_turnaround_days"] = net
    touch(case)
    return object_response(serialize.case(case), 200)


@bp.route("/lab/cases/<case_id>/discovery-request", methods=["POST"])
@endpoint(CASE_MANAGER)
def discovery_request(case_id):
    case = S.find_case(case_id)
    body = parse([
        Field("discovery_requesting_party", "string", required=True),
    ])
    if case["discovery_status"] != "NONE":
        raise ApiError("ERR_DISCOVERY_ALREADY_RECEIVED")
    if case["workflow_status"] not in (
            "ACCEPTED", "AWAITING_ASSIGNMENT", "IN_PROGRESS", "REPORTED"):
        raise ApiError("ERR_CASE_INVALID_STATE")
    requested = db.now()
    case["discovery_status"] = "RECEIVED"
    case["discovery_requesting_party"] = body["discovery_requesting_party"]
    case["discovery_requested_at_utc"] = requested
    case["discovery_due_utc"] = add_days(requested, S.DISCOVERY_RESPONSE_DAYS)
    touch(case)
    return object_response(serialize.case(case), 200)


@bp.route("/lab/cases/<case_id>/discovery-response", methods=["POST"])
@endpoint(CASE_MANAGER)
def discovery_response(case_id):
    case = S.find_case(case_id)
    body = parse([
        Field("decision", "enum", required=True, choices=("FULFILL", "DENY")),
        Field("response_note", "string"),
    ])
    if body["decision"] == "DENY" and not body.get("response_note"):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "A denial requires a present, non-empty response_note.",
        )
    if case["discovery_status"] != "RECEIVED":
        raise ApiError("ERR_DISCOVERY_NOT_PENDING")
    if body["decision"] == "FULFILL":
        if case["released_examination_request_count"] < 1:
            raise ApiError("ERR_CASE_HAS_NO_RELEASED_REQUEST")
        case["discovery_status"] = "FULFILLED"
    else:
        case["discovery_status"] = "DENIED"
    touch(case)
    if case["discovery_due_utc"] is not None and db.now() > case["discovery_due_utc"]:
        S.open_nonconformance(
            "DEADLINE_MISS", "MAJOR",
            "Discovery response deadline missed for case %s." % case["id"],
        )
    return object_response(serialize.case(case), 200)


# ---------------------------------------------------------------- evidence
@bp.route("/lab/evidence-items", methods=["POST"])
@endpoint(EVIDENCE_TECHNICIAN)
def create_evidence_item():
    body = parse([
        Field("case_id", "string", required=True, min_length=1),
        Field("item_number", "string", required=True, min_length=1, max_length=20),
        Field("item_description", "string", required=True),
        Field("item_type", "enum", required=True, choices=S.ITEM_TYPES),
        Field("seal_intact", "boolean", required=True),
    ])
    case = S.find_case(body["case_id"])
    for item in S.items_of_case(case["id"]):
        if item["item_number"] == body["item_number"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    if case["workflow_status"] != "SUBMITTED":
        raise ApiError("ERR_CASE_INVALID_STATE")
    row = new_row()
    row.update({
        "case_id": case["id"],
        "item_number": body["item_number"],
        "item_description": body["item_description"],
        "item_type": body["item_type"],
        "seal_intact": body["seal_intact"],
        "custody_status": "IN_VAULT",
        "checkout_count": 0,
        "logged_at_utc": db.now(),
    })
    db.evidence_items[row["id"]] = row
    return object_response(serialize.evidence_item(row), 201)


@bp.route("/lab/evidence-items/<evidence_item_id>/return", methods=["POST"])
@endpoint(EVIDENCE_TECHNICIAN)
def return_evidence_item(evidence_item_id):
    item = S.find_evidence_item(evidence_item_id)
    parse([Field("return_note", "string")])
    if item["custody_status"] != "IN_VAULT":
        raise ApiError("ERR_EVIDENCE_CUSTODY_INVALID_STATE")
    case = db.cases.get(item["case_id"])
    if case is None or case["workflow_status"] not in ("REPORTED", "REJECTED"):
        raise ApiError("ERR_CASE_INVALID_STATE")
    item["custody_status"] = "RETURNED"
    touch(item)
    return object_response(serialize.evidence_item(item), 200)
