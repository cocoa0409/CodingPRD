"""Single reads, list reads and the two computed reads."""
from flask import Blueprint, request

import serialize
import services as S
from auth import (ANALYST, CASE_MANAGER, EVIDENCE_TECHNICIAN, LAB_DIRECTOR,
                  QUALITY_MANAGER, endpoint)
from envelope import array_response, object_response, paginate, pagination
from errors import ApiError
from store import by_created, db
from util import as_number, fmt_instant, parse_instant

bp = Blueprint("reads", __name__)

ALL_ROLES = (LAB_DIRECTOR, QUALITY_MANAGER, CASE_MANAGER, EVIDENCE_TECHNICIAN,
             ANALYST)
STAFF_ROLES = (LAB_DIRECTOR, QUALITY_MANAGER, CASE_MANAGER, ANALYST)


def _filter(rows, pairs):
    """Query-string equality filters; an unmatched value narrows to nothing."""
    for param, field in pairs:
        wanted = request.args.get(param)
        if wanted is None:
            continue
        rows = [r for r in rows if r.get(field) == wanted]
    return rows


def _listing(rows, render):
    limit, offset = pagination()
    total = len(rows)
    page = paginate(rows, limit, offset)
    return array_response([render(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------- singles
@bp.route("/lab/analysts/<analyst_id>", methods=["GET"])
@endpoint(*STAFF_ROLES)
def get_analyst(analyst_id):
    return object_response(serialize.analyst(S.find_analyst(analyst_id)))


@bp.route("/lab/methods/<method_id>", methods=["GET"])
@endpoint(*STAFF_ROLES)
def get_method(method_id):
    return object_response(serialize.method(S.find_method(method_id)))


@bp.route("/lab/vendors/<vendor_id>", methods=["GET"])
@endpoint(LAB_DIRECTOR, CASE_MANAGER, QUALITY_MANAGER)
def get_vendor(vendor_id):
    return object_response(serialize.vendor(S.find_vendor(vendor_id)))


@bp.route("/lab/cases/<case_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_case(case_id):
    return object_response(serialize.case(S.find_case(case_id)))


@bp.route("/lab/evidence-items/<evidence_item_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_evidence_item(evidence_item_id):
    return object_response(
        serialize.evidence_item(S.find_evidence_item(evidence_item_id)))


@bp.route("/lab/examination-requests/<examination_request_id>", methods=["GET"])
@endpoint(*STAFF_ROLES)
def get_examination_request(examination_request_id):
    return object_response(serialize.examination_request(
        S.find_examination_request(examination_request_id)))


@bp.route("/lab/assignments/<assignment_id>", methods=["GET"])
@endpoint(*STAFF_ROLES)
def get_assignment(assignment_id):
    return object_response(serialize.assignment(S.find_assignment(assignment_id)))


@bp.route("/lab/review-records/<review_record_id>", methods=["GET"])
@endpoint(*STAFF_ROLES)
def get_review_record(review_record_id):
    return object_response(
        serialize.review_record(S.find_review_record(review_record_id)))


@bp.route("/lab/proficiency-tests/<proficiency_test_id>", methods=["GET"])
@endpoint(LAB_DIRECTOR, QUALITY_MANAGER, ANALYST)
def get_proficiency_test(proficiency_test_id):
    return object_response(
        serialize.proficiency_test(S.find_proficiency_test(proficiency_test_id)))


@bp.route("/lab/vendor-engagements/<vendor_engagement_id>", methods=["GET"])
@endpoint(LAB_DIRECTOR, QUALITY_MANAGER, CASE_MANAGER)
def get_vendor_engagement(vendor_engagement_id):
    return object_response(serialize.vendor_engagement(
        S.find_vendor_engagement(vendor_engagement_id)))


@bp.route("/lab/nonconformances/<nonconformance_id>", methods=["GET"])
@endpoint(*STAFF_ROLES)
def get_nonconformance(nonconformance_id):
    return object_response(
        serialize.nonconformance(S.find_nonconformance(nonconformance_id)))


@bp.route("/lab/court-events/<court_event_id>", methods=["GET"])
@endpoint(*STAFF_ROLES)
def get_court_event(court_event_id):
    return object_response(
        serialize.court_event(S.find_court_event(court_event_id)))


# ------------------------------------------------------------------- lists
@bp.route("/lab/cases", methods=["GET"])
@endpoint(LAB_DIRECTOR, QUALITY_MANAGER, CASE_MANAGER, EVIDENCE_TECHNICIAN)
def list_cases():
    rows = _filter(by_created(db.cases.values()), [
        ("submitting_agency", "submitting_agency"),
        ("offense_category", "offense_category"),
        ("priority_class", "priority_class"),
        ("workflow_status", "workflow_status"),
        ("discovery_status", "discovery_status"),
    ])
    rows = sorted(rows, key=lambda r: (r["received_at_utc"], r["_seq"]))
    rows = sorted(rows, key=lambda r: r["priority_score"], reverse=True)
    return _listing(rows, serialize.case)


@bp.route("/lab/evidence-items", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_evidence_items():
    rows = _filter(by_created(db.evidence_items.values()), [
        ("case_id", "case_id"),
        ("custody_status", "custody_status"),
        ("item_type", "item_type"),
    ])
    return _listing(rows, serialize.evidence_item)


@bp.route("/lab/examination-requests", methods=["GET"])
@endpoint(*STAFF_ROLES)
def list_examination_requests():
    rows = _filter(by_created(db.examination_requests.values()), [
        ("case_id", "case_id"),
        ("evidence_item_id", "evidence_item_id"),
        ("method_id", "method_id"),
        ("assigned_analyst_id", "assigned_analyst_id"),
        ("discipline", "discipline"),
        ("status", "status"),
    ])

    def case_score(row):
        case_row = db.cases.get(row["case_id"])
        return case_row["priority_score"] if case_row else 0

    rows = sorted(rows, key=lambda r: (r["requested_at_utc"], r["_seq"]))
    rows = sorted(rows, key=case_score, reverse=True)
    return _listing(rows, serialize.examination_request)


@bp.route("/lab/assignments", methods=["GET"])
@endpoint(*STAFF_ROLES)
def list_assignments():
    rows = _filter(by_created(db.assignments.values()), [
        ("examination_request_id", "examination_request_id"),
        ("analyst_id", "analyst_id"),
        ("superseded_by_assignment_id", "superseded_by_assignment_id"),
        ("status", "status"),
    ])
    return _listing(rows, serialize.assignment)


@bp.route("/lab/review-records", methods=["GET"])
@endpoint(*STAFF_ROLES)
def list_review_records():
    rows = _filter(by_created(db.review_records.values()), [
        ("examination_request_id", "examination_request_id"),
        ("reviewer_analyst_id", "reviewer_analyst_id"),
        ("review_type", "review_type"),
    ])
    rows = sorted(rows, key=lambda r: (r["recorded_at_utc"], r["_seq"]))
    return _listing(rows, serialize.review_record)


@bp.route("/lab/proficiency-tests", methods=["GET"])
@endpoint(LAB_DIRECTOR, QUALITY_MANAGER, ANALYST)
def list_proficiency_tests():
    rows = _filter(by_created(db.proficiency_tests.values()), [
        ("analyst_id", "analyst_id"),
        ("method_id", "method_id"),
        ("test_cycle", "test_cycle"),
        ("status", "status"),
        ("result", "result"),
    ])
    return _listing(rows, serialize.proficiency_test)


@bp.route("/lab/vendor-engagements", methods=["GET"])
@endpoint(LAB_DIRECTOR, QUALITY_MANAGER, CASE_MANAGER)
def list_vendor_engagements():
    rows = _filter(by_created(db.vendor_engagements.values()), [
        ("examination_request_id", "examination_request_id"),
        ("vendor_id", "vendor_id"),
        ("status", "status"),
    ])
    return _listing(rows, serialize.vendor_engagement)


@bp.route("/lab/nonconformances", methods=["GET"])
@endpoint(*STAFF_ROLES)
def list_nonconformances():
    rows = _filter(by_created(db.nonconformances.values()), [
        ("examination_request_id", "examination_request_id"),
        ("analyst_id", "analyst_id"),
        ("source", "source"),
        ("severity", "severity"),
        ("status", "status"),
    ])
    return _listing(rows, serialize.nonconformance)


@bp.route("/lab/court-events", methods=["GET"])
@endpoint(*STAFF_ROLES)
def list_court_events():
    rows = _filter(by_created(db.court_events.values()), [
        ("examination_request_id", "examination_request_id"),
        ("analyst_id", "analyst_id"),
        ("status", "status"),
    ])
    rows = sorted(rows, key=lambda r: (r["start_utc"], r["_seq"]))
    return _listing(rows, serialize.court_event)


# --------------------------------------------------------- computed reads
@bp.route("/lab/analysts/<analyst_id>/workload", methods=["GET"])
@endpoint(*STAFF_ROLES)
def analyst_workload(analyst_id):
    analyst = S.find_analyst(analyst_id)
    doc = S.workload_document(analyst)
    return object_response({
        "analyst_id": doc["analyst_id"],
        "available_hours": as_number(doc["available_hours"]),
        "projected_load_hours": as_number(doc["projected_load_hours"]),
        "projected_utilization_pct": as_number(doc["projected_utilization_pct"]),
        "realized_load_hours": as_number(doc["realized_load_hours"]),
        "realized_utilization_pct": as_number(doc["realized_utilization_pct"]),
        "casework_training_ratio": as_number(doc["casework_training_ratio"]),
        "active_assignment_count": doc["active_assignment_count"],
        "assigned_casework_hours": as_number(doc["assigned_casework_hours"]),
    })


@bp.route("/lab/backlog-report", methods=["GET"])
@endpoint(LAB_DIRECTOR, QUALITY_MANAGER, CASE_MANAGER)
def backlog_report():
    raw = request.args.get("as_of_utc")
    if raw is None:
        as_of = db.now()
    else:
        as_of = parse_instant(raw)
        if as_of is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "as_of_utc must be an ISO-8601 UTC instant")
    discipline = request.args.get("discipline")
    doc = S.backlog_report(as_of, discipline)
    return object_response({
        "as_of_utc": fmt_instant(doc["as_of_utc"]),
        "open_request_count": doc["open_request_count"],
        "backlog_index": as_number(doc["backlog_index"]),
        "bucket_0_29_count": doc["bucket_0_29_count"],
        "bucket_30_59_count": doc["bucket_30_59_count"],
        "bucket_60_89_count": doc["bucket_60_89_count"],
        "bucket_90_plus_count": doc["bucket_90_plus_count"],
        "p1_open_count": doc["p1_open_count"],
        "outsourcing_recommended": doc["outsourcing_recommended"],
    })
