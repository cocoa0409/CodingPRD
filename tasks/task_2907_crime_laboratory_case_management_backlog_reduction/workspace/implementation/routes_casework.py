"""Examination requests, staffing, bench work and the review gates."""
from decimal import Decimal

from flask import Blueprint, g

import serialize
import services as S
from auth import ANALYST, CASE_MANAGER, QUALITY_MANAGER, endpoint
from envelope import object_response
from errors import ApiError
from store import db, new_row, touch
from util import dec, q2
from validate import Field, parse

bp = Blueprint("casework", __name__)


def _standing_battery(analyst):
    """PRD section 2.8 rule 13, applied to the subject analyst."""
    if analyst["employment_status"] != "ACTIVE":
        raise ApiError("ERR_ANALYST_NOT_ACTIVE")
    if analyst["qualification_state"] == "DECERTIFIED":
        raise ApiError("ERR_ANALYST_DECERTIFIED")
    if analyst["qualification_state"] not in ("QUALIFIED", "PROBATION"):
        raise ApiError("ERR_ANALYST_NOT_QUALIFIED")


def _assignment_battery(analyst, case, method, request_row):
    """Rules 13, 20, 21, 22, 23 and 25 in the order PRD section 2.8 fixes."""
    _standing_battery(analyst)
    if analyst["qualification_state"] == "PROBATION":
        if case["priority_class"] != "P3_ROUTINE":
            raise ApiError("ERR_PROBATION_PRIORITY_RESTRICTED")
        if dec(analyst["training_hours_per_week"]) < S.PROBATION_TRAINING_MINIMUM:
            raise ApiError("ERR_TRAINING_MINIMUM_NOT_MET")
    if method["discipline"] not in analyst["disciplines"]:
        raise ApiError("ERR_ANALYST_DISCIPLINE_MISMATCH")
    if analyst["competency_level"] < method["min_competency_level"]:
        raise ApiError("ERR_ANALYST_COMPETENCY_INSUFFICIENT")
    if not S.capacity_admits(analyst, request_row["estimated_hours"]):
        raise ApiError("ERR_ANALYST_CAPACITY_EXCEEDED")


# ---------------------------------------------------- examination requests
@bp.route("/lab/examination-requests", methods=["POST"])
@endpoint(CASE_MANAGER)
def create_examination_request():
    body = parse([
        Field("case_id", "string", required=True, min_length=1),
        Field("evidence_item_id", "string", required=True, min_length=1),
        Field("method_id", "string", required=True, min_length=1),
        Field("item_count", "integer", required=True, minimum=1),
    ])
    case = S.find_case(body["case_id"])
    item = S.find_evidence_item(body["evidence_item_id"])
    method = S.find_method(body["method_id"])
    for existing in db.examination_requests.values():
        if existing["status"] == "CANCELLED":
            continue
        if (existing["evidence_item_id"] == item["id"]
                and existing["method_id"] == method["id"]):
            raise ApiError("ERR_DUPLICATE_RESOURCE")
    if case["workflow_status"] not in (
            "ACCEPTED", "IN_PROGRESS", "AWAITING_ASSIGNMENT"):
        raise ApiError("ERR_CASE_INVALID_STATE")
    if item["case_id"] != case["id"]:
        raise ApiError("ERR_REFERENTIAL_MISMATCH")
    if item["item_type"] not in S.METHOD_ITEM_TYPE_MATRIX[method["discipline"]]:
        raise ApiError("ERR_REFERENTIAL_MISMATCH")
    if not item["seal_intact"]:
        raise ApiError("ERR_EVIDENCE_SEAL_BROKEN")
    if method["validation_status"] != "VALIDATED":
        raise ApiError("ERR_METHOD_NOT_VALIDATED")
    if body["item_count"] > method["max_items_per_request"]:
        raise ApiError("ERR_ITEM_COUNT_EXCEEDS_METHOD_LIMIT")
    row = new_row()
    row.update({
        "case_id": case["id"],
        "evidence_item_id": item["id"],
        "method_id": method["id"],
        "assigned_analyst_id": None,
        "discipline": method["discipline"],
        "item_count": body["item_count"],
        "estimated_hours": q2(
            dec(method["standard_hours_per_item"]) * Decimal(body["item_count"])
        ),
        "actual_hours_logged": None,
        "status": "QUEUED",
        "revision_round": 0,
        "requested_at_utc": db.now(),
        "released_at_utc": None,
        "vendor_custody_days": Decimal("0.00"),
    })
    db.examination_requests[row["id"]] = row
    S.case_recompute(case)
    return object_response(serialize.examination_request(row), 201)


# ---------------------------------------------------------------- staffing
def _create_assignment(request_row, analyst, reason):
    row = new_row()
    row.update({
        "examination_request_id": request_row["id"],
        "analyst_id": analyst["id"],
        "estimated_hours": q2(dec(request_row["estimated_hours"])),
        "assignment_reason": reason,
        "status": "ACTIVE",
        "superseded_by_assignment_id": None,
        "assigned_at_utc": db.now(),
        "closed_at_utc": None,
    })
    db.assignments[row["id"]] = row
    return row


def _settle_assignment(request_row, case, analyst, reason):
    """Create the incoming holder's row, supersede any incumbent, encumber."""
    incumbent = S.active_assignment_of_request(request_row["id"])
    row = _create_assignment(request_row, analyst, reason)
    if incumbent is not None:
        outgoing = db.analysts.get(incumbent["analyst_id"])
        incumbent["status"] = "SUPERSEDED"
        incumbent["closed_at_utc"] = db.now()
        incumbent["superseded_by_assignment_id"] = row["id"]
        touch(incumbent)
        if outgoing is not None:
            S.subtract_casework_hours(outgoing, incumbent["estimated_hours"])
    S.add_casework_hours(analyst, request_row["estimated_hours"])
    request_row["assigned_analyst_id"] = analyst["id"]
    request_row["status"] = "ASSIGNED"
    touch(request_row)
    if case is not None:
        S.case_recompute(case)
    return row


@bp.route("/lab/examination-requests/<examination_request_id>/assignments",
          methods=["POST"])
@endpoint(CASE_MANAGER)
def create_assignment(examination_request_id):
    request_row = S.find_examination_request(examination_request_id)
    body = parse([
        Field("analyst_id", "string", required=True, min_length=1),
        Field("expected_examination_request_version", "integer", required=True),
        Field("assignment_reason", "enum", default="MANUAL",
              choices=S.ASSIGNMENT_REASONS),
    ])
    analyst = S.find_analyst(body["analyst_id"])
    if request_row["status"] not in ("QUEUED", "ASSIGNED"):
        raise ApiError("ERR_EXAM_REQUEST_INVALID_STATE")
    if body["expected_examination_request_version"] != request_row["version"]:
        raise ApiError("ERR_STALE_EXAM_REQUEST_VERSION")
    case = db.cases.get(request_row["case_id"])
    method = db.methods.get(request_row["method_id"])
    _assignment_battery(analyst, case, method, request_row)
    if request_row["assigned_analyst_id"] == analyst["id"]:
        raise ApiError("ERR_ANALYST_ALREADY_ASSIGNED")
    row = _settle_assignment(request_row, case, analyst,
                             body["assignment_reason"])
    return object_response(serialize.assignment(row), 201)


@bp.route("/lab/examination-requests/<examination_request_id>/auto-assign",
          methods=["POST"])
@endpoint(CASE_MANAGER)
def auto_assign(examination_request_id):
    request_row = S.find_examination_request(examination_request_id)
    parse([])
    if request_row["status"] != "QUEUED":
        raise ApiError("ERR_EXAM_REQUEST_INVALID_STATE")
    case = db.cases.get(request_row["case_id"])
    method = db.methods.get(request_row["method_id"])
    candidates = []
    for analyst in db.analysts.values():
        if analyst["employment_status"] != "ACTIVE":
            continue
        if analyst["qualification_state"] == "PROBATION":
            if case is None or case["priority_class"] != "P3_ROUTINE":
                continue
            if dec(analyst["training_hours_per_week"]) < S.PROBATION_TRAINING_MINIMUM:
                continue
        elif analyst["qualification_state"] != "QUALIFIED":
            continue
        if method is None or method["discipline"] not in analyst["disciplines"]:
            continue
        if analyst["competency_level"] < method["min_competency_level"]:
            continue
        figure = S.post_assignment_utilization(
            analyst, request_row["estimated_hours"])
        if figure is None or figure > S.UTILIZATION_CEILING_PCT:
            continue
        candidates.append((
            figure,
            S.active_assignment_count(analyst["id"]),
            analyst["created_at"],
            analyst["_seq"],
            analyst,
        ))
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_ANALYST")
    candidates.sort(key=lambda entry: entry[0:4])
    chosen = candidates[0][4]
    row = _settle_assignment(request_row, case, chosen, "AUTO_BALANCED")
    return object_response(serialize.assignment(row), 201)


# ---------------------------------------------------------------- bench work
@bp.route("/lab/examination-requests/<examination_request_id>/start-analysis",
          methods=["POST"])
@endpoint(ANALYST)
def start_analysis(examination_request_id):
    request_row = S.find_examination_request(examination_request_id)
    parse([])
    if request_row["assigned_analyst_id"] != g.user_id:
        raise ApiError("ERR_ANALYST_IDENTITY_MISMATCH")
    if request_row["status"] != "ASSIGNED":
        raise ApiError("ERR_EXAM_REQUEST_INVALID_STATE")
    item = db.evidence_items.get(request_row["evidence_item_id"])
    if item is None or item["custody_status"] != "IN_VAULT":
        raise ApiError("ERR_EVIDENCE_CUSTODY_INVALID_STATE")
    if not item["seal_intact"]:
        raise ApiError("ERR_EVIDENCE_SEAL_BROKEN")
    method = db.methods.get(request_row["method_id"])
    if method is None or method["validation_status"] != "VALIDATED":
        raise ApiError("ERR_METHOD_NOT_VALIDATED")
    if (method["validation_expires_at_utc"] is not None
            and method["validation_expires_at_utc"] <= db.now()):
        raise ApiError("ERR_METHOD_VALIDATION_EXPIRED")
    analyst = S.find_analyst(request_row["assigned_analyst_id"])
    case = db.cases.get(request_row["case_id"])
    _standing_battery(analyst)
    if not S.is_bench_eligible(analyst, case):
        raise ApiError("ERR_ANALYST_NOT_QUALIFIED")
    item["custody_status"] = "IN_ANALYSIS"
    item["checkout_count"] = item["checkout_count"] + 1
    touch(item)
    request_row["status"] = "IN_ANALYSIS"
    touch(request_row)
    if case is not None:
        S.case_recompute(case)
    return object_response(serialize.examination_request(request_row), 200)


@bp.route("/lab/examination-requests/<examination_request_id>/complete-analysis",
          methods=["POST"])
@endpoint(ANALYST)
def complete_analysis(examination_request_id):
    request_row = S.find_examination_request(examination_request_id)
    body = parse([
        Field("actual_hours", "number", required=True,
              exclusive_minimum="0.00", maximum="400.00"),
        Field("evidence_consumed", "boolean", default=False),
    ])
    if request_row["assigned_analyst_id"] != g.user_id:
        raise ApiError("ERR_ANALYST_IDENTITY_MISMATCH")
    if request_row["status"] != "IN_ANALYSIS":
        raise ApiError("ERR_EXAM_REQUEST_INVALID_STATE")
    method = db.methods.get(request_row["method_id"])
    if body["evidence_consumed"] and not (method and method["is_consumptive"]):
        raise ApiError("ERR_METHOD_NOT_CONSUMPTIVE")
    request_row["actual_hours_logged"] = q2(body["actual_hours"])
    request_row["status"] = "TECH_REVIEW"
    touch(request_row)
    item = db.evidence_items.get(request_row["evidence_item_id"])
    if item is not None:
        item["custody_status"] = (
            "CONSUMED" if body["evidence_consumed"] else "IN_VAULT"
        )
        touch(item)
    holder = S.active_assignment_of_request(request_row["id"])
    if holder is not None:
        holder["status"] = "COMPLETED"
        holder["closed_at_utc"] = db.now()
        touch(holder)
        analyst = db.analysts.get(holder["analyst_id"])
        if analyst is not None:
            S.subtract_casework_hours(analyst, holder["estimated_hours"])
    case = db.cases.get(request_row["case_id"])
    if case is not None:
        S.case_recompute(case)
    return object_response(serialize.examination_request(request_row), 200)


# ---------------------------------------------------------------- review gates
DECISION_RATIONALE = [
    Field("decision", "enum", required=True, choices=("AGREE", "DISAGREE")),
    Field("rationale", "string", required=True, min_length=1, max_length=500),
]


def _write_review_record(request_row, review_type, decision, rationale,
                         analyst_id=None, operator_id=None):
    row = new_row(with_audit=False)
    row.update({
        "examination_request_id": request_row["id"],
        "reviewer_analyst_id": analyst_id,
        "reviewer_operator_id": operator_id,
        "review_type": review_type,
        "decision": decision,
        "rationale": rationale,
        "revision_round_snapshot": request_row["revision_round"],
        "recorded_at_utc": db.now(),
    })
    db.review_records[row["id"]] = row
    return row


def _round_parties(request_row, review_types):
    """Parties of the current revision round that a reviewer may not be."""
    parties = set()
    if request_row["assigned_analyst_id"] is not None:
        parties.add(request_row["assigned_analyst_id"])
    for record in S.records_of_request(request_row["id"]):
        if record["revision_round_snapshot"] != request_row["revision_round"]:
            continue
        if record["review_type"] not in review_types:
            continue
        for key in ("reviewer_analyst_id", "reviewer_operator_id"):
            if record[key] is not None:
                parties.add(record[key])
    return parties


@bp.route("/lab/examination-requests/<examination_request_id>/technical-review",
          methods=["POST"])
@endpoint(ANALYST)
def technical_review(examination_request_id):
    request_row = S.find_examination_request(examination_request_id)
    body = parse(DECISION_RATIONALE)
    reviewer = S.find_analyst(g.user_id)
    if request_row["status"] != "TECH_REVIEW":
        raise ApiError("ERR_EXAM_REQUEST_INVALID_STATE")
    if reviewer["employment_status"] != "ACTIVE":
        raise ApiError("ERR_ANALYST_NOT_ACTIVE")
    if reviewer["qualification_state"] == "DECERTIFIED":
        raise ApiError("ERR_ANALYST_DECERTIFIED")
    if reviewer["qualification_state"] != "QUALIFIED":
        raise ApiError("ERR_ANALYST_NOT_QUALIFIED")
    if g.user_id == request_row["assigned_analyst_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    method = db.methods.get(request_row["method_id"])
    if method is None or method["discipline"] not in reviewer["disciplines"]:
        raise ApiError("ERR_ANALYST_DISCIPLINE_MISMATCH")
    if reviewer["competency_level"] < method["min_competency_level"]:
        raise ApiError("ERR_ANALYST_COMPETENCY_INSUFFICIENT")
    record = _write_review_record(
        request_row, "TECHNICAL", body["decision"], body["rationale"],
        analyst_id=g.user_id,
    )
    case = db.cases.get(request_row["case_id"])
    implicated_id = request_row["assigned_analyst_id"]
    if body["decision"] == "AGREE":
        request_row["status"] = "ADMIN_REVIEW"
        touch(request_row)
        if case is not None:
            S.case_recompute(case)
    else:
        request_row["status"] = "DISAGREEMENT"
        touch(request_row)
        if case is not None:
            S.case_recompute(case)
        S.open_nonconformance(
            "TECHNICAL_DISAGREEMENT", "MAJOR",
            "Technical review disagreement on examination request %s."
            % request_row["id"],
            examination_request_id=request_row["id"],
            analyst_id=implicated_id,
        )
        implicated = db.analysts.get(implicated_id) if implicated_id else None
        if implicated is not None:
            S.enter_probation(implicated)
    return object_response(serialize.review_record(record), 201)


@bp.route("/lab/examination-requests/<examination_request_id>"
          "/disagreement-resolution", methods=["POST"])
@endpoint(QUALITY_MANAGER)
def disagreement_resolution(examination_request_id):
    request_row = S.find_examination_request(examination_request_id)
    body = parse([
        Field("decision", "enum", required=True,
              choices=("UPHOLD_ANALYST", "UPHOLD_REVIEWER")),
        Field("rationale", "string", required=True, min_length=1, max_length=500),
    ])
    if request_row["status"] != "DISAGREEMENT":
        raise ApiError("ERR_EXAM_REQUEST_INVALID_STATE")
    if g.user_id in _round_parties(request_row, ("TECHNICAL", "ADMINISTRATIVE")):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    record = _write_review_record(
        request_row, "DISAGREEMENT_RESOLUTION", body["decision"],
        body["rationale"], operator_id=g.user_id,
    )
    case = db.cases.get(request_row["case_id"])
    if body["decision"] == "UPHOLD_ANALYST":
        request_row["status"] = "ADMIN_REVIEW"
        touch(request_row)
        if case is not None:
            S.case_recompute(case)
        for finding in S.findings_of_request(request_row["id"]):
            if finding["source"] != "TECHNICAL_DISAGREEMENT":
                continue
            if finding["status"] not in ("OPEN", "ROOT_CAUSE_SUBMITTED"):
                continue
            finding["status"] = "VOIDED"
            finding["closed_at_utc"] = db.now()
            touch(finding)
            implicated = db.analysts.get(finding["analyst_id"])
            S.restore_to_qualified(implicated)
    else:
        request_row["revision_round"] = request_row["revision_round"] + 1
        S.reopen_hold(request_row)
    return object_response(serialize.review_record(record), 201)


@bp.route("/lab/examination-requests/<examination_request_id>"
          "/administrative-review", methods=["POST"])
@endpoint(CASE_MANAGER)
def administrative_review(examination_request_id):
    request_row = S.find_examination_request(examination_request_id)
    body = parse([
        Field("decision", "enum", required=True, choices=("APPROVE", "RETURN")),
        Field("rationale", "string", required=True, min_length=1, max_length=500),
    ])
    if request_row["status"] != "ADMIN_REVIEW":
        raise ApiError("ERR_EXAM_REQUEST_INVALID_STATE")
    if g.user_id in _round_parties(request_row, ("TECHNICAL",)):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    record = _write_review_record(
        request_row, "ADMINISTRATIVE", body["decision"], body["rationale"],
        operator_id=g.user_id,
    )
    case = db.cases.get(request_row["case_id"])
    if body["decision"] == "APPROVE":
        request_row["status"] = "RELEASED"
        request_row["released_at_utc"] = db.now()
        touch(request_row)
        if case is not None:
            S.case_recompute(case)
    else:
        request_row["revision_round"] = request_row["revision_round"] + 1
        S.reopen_hold(request_row)
    return object_response(serialize.review_record(record), 201)
