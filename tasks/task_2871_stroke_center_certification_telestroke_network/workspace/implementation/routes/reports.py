"""Certification reports: gathering, submission, decision, publication (PRD 3.9)."""
from decimal import Decimal

from flask import Blueprint

import db
import response as resp
from constants import MIN_CLOSED_CASES_PER_PERIOD
from errors import fail
from middleware import (
    Field,
    apply_filters,
    authenticate,
    load_path,
    load_ref,
    pagination,
    read_body,
)
from services import calculations as calc
from services import derive
from services import reporting

bp = Blueprint("reports", __name__)

CREATE_SPEC = [
    Field("center_id", "str"),
    Field("period_start", "dt"),
    Field("period_end", "dt"),
    Field("expected_center_version", "int"),
]

DECIDE_SPEC = [Field("reviewer_note", "str", required=False)]


def _overlaps(report, start, end):
    other_start = db.parse_iso(report["period_start"])
    other_end = db.parse_iso(report["period_end"])
    return start < other_end and other_start < end


def _gather(report):
    """Attach every DRAFT or FINALIZED abstraction sitting on an in-period
    closed case at this facility."""
    case_ids = set(case["id"] for case in reporting.closed_cases_in_period(report))
    for abstraction in db.all_of("abstractions"):
        if abstraction["status"] not in ("DRAFT", "FINALIZED"):
            continue
        if abstraction["case_id"] not in case_ids:
            continue
        db.setf(abstraction, "report_id", report["id"])


@bp.route("/certification-reports", methods=["POST"])
def create_report():
    authenticate(("ProgramCoordinator",))
    body = read_body(CREATE_SPEC)
    center = load_ref("centers", body["center_id"])
    if body["expected_center_version"] != center["version"]:
        fail("ERR_STALE_CENTER_VERSION",
             "expected_center_version %s does not match the facility's current "
             "version %s." % (body["expected_center_version"], center["version"]))
    start = db.parse_iso(body["period_start"])
    end = db.parse_iso(body["period_end"])
    if not start < end:
        fail("ERR_INVALID_PERIOD_RANGE",
             "period_start must be strictly earlier than period_end.")
    for other in db.all_of("reports"):
        if other["center_id"] != center["id"] or other["status"] == "SUPERSEDED":
            continue
        if _overlaps(other, start, end):
            fail("ERR_REPORT_PERIOD_OVERLAP",
                 "The period intersects an existing report's period.")
    record = {
        "center_id": center["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "included_abstraction_count": 0,
        "closed_case_count_in_period": 0,
        "dtn_60_compliance_pct": Decimal("0.00"),
        "dti_45_compliance_pct": Decimal("0.00"),
        "telestroke_response_compliance_pct": Decimal("0.00"),
        "mean_dtn_excess_pct": None,
        "rate_variant": "PROVISIONAL",
        "substantiated_major_count": 0,
        "substantiated_sentinel_count": 0,
        "composite_certification_score": Decimal("0.00"),
        "decision": "PENDING",
        "submitted_at": None,
        "decided_at": None,
        "published_at": None,
        "superseded_by_report_id": None,
    }
    db.insert("reports", record)
    # Creation supersedes the facility's existing DRAFT report and detaches
    # every abstraction that was attached to it.
    for other in db.all_of("reports"):
        if (other["id"] == record["id"] or other["center_id"] != center["id"]
                or other["status"] != "DRAFT"):
            continue
        other["status"] = "SUPERSEDED"
        other["superseded_by_report_id"] = record["id"]
        db.touch(other)
        for abstraction in reporting.attached_abstractions(other):
            db.setf(abstraction, "report_id", None)
    _gather(record)
    reporting.recompute_counts(record)
    reporting.recompute_rates(record, "PROVISIONAL")
    reporting.recompute_mean_dtn_excess(record)
    reporting.recompute_substantiated_counts(record)
    db.touch(center)
    return resp.object_response(record, 201)


@bp.route("/certification-reports/<record_id>", methods=["GET"])
def read_report(record_id):
    authenticate("any")
    return resp.object_response(load_path("reports", record_id))


@bp.route("/certification-reports", methods=["GET"])
def list_reports():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("reports"), {
        "center_id": "center_id",
        "status": "status",
        "decision": "decision",
        "superseded_by_report_id": "superseded_by_report_id",
        "rate_variant": "rate_variant",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/certification-reports/<record_id>/submit", methods=["POST"])
def submit_report(record_id):
    user_id, _role = authenticate(("ProgramCoordinator",))
    record = load_path("reports", record_id)
    read_body([])
    if record["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_INVALID_REPORT_STATE",
             "No submission is declared from %s." % record["status"])
    closed_cases = reporting.closed_cases_in_period(record)
    case_ids = set(case["id"] for case in closed_cases)
    finalized = [a for a in db.all_of("abstractions")
                 if a["status"] == "FINALIZED"
                 and (a["report_id"] == record["id"] or a["case_id"] in case_ids)]
    if len(finalized) < 1:
        fail("ERR_NO_FINALIZED_ABSTRACTIONS",
             "The report carries no finalised abstraction.")
    if len(closed_cases) < MIN_CLOSED_CASES_PER_PERIOD:
        fail("ERR_INSUFFICIENT_CASE_VOLUME",
             "The period carries %d closed cases; %d are required."
             % (len(closed_cases), MIN_CLOSED_CASES_PER_PERIOD))
    if record["status"] == "RETURNED":
        # A returned report is judged fresh: the previous verdict is cleared
        # before any recomputation runs.
        record["decision"] = "PENDING"
        record["decided_by_user_id"] = None
    # Re-gather: DRAFT rows are detached, in-period FINALIZED rows attached.
    for abstraction in reporting.attached_abstractions(record):
        if abstraction["status"] == "DRAFT":
            db.setf(abstraction, "report_id", None)
    for abstraction in finalized:
        db.setf(abstraction, "report_id", record["id"])
    reporting.recompute_counts(record)
    record["rate_variant"] = "CERTIFIED"
    reporting.recompute_rates(record, "CERTIFIED")
    reporting.recompute_mean_dtn_excess(record)
    reporting.recompute_substantiated_counts(record)
    center = db.get("centers", record["center_id"])
    record["composite_certification_score"] = calc.composite_score(
        record["dtn_60_compliance_pct"], record["dti_45_compliance_pct"],
        record["telestroke_response_compliance_pct"],
        record["substantiated_major_count"], record["substantiated_sentinel_count"],
        record["included_abstraction_count"],
        center["facility_type"] if center is not None else None)
    record["status"] = "SUBMITTED"
    record["submitted_at"] = db.now_raw()
    record["submitted_by_user_id"] = user_id
    db.touch(record)
    return resp.object_response(record)


@bp.route("/certification-reports/<record_id>/decide", methods=["POST"])
def decide_report(record_id):
    user_id, _role = authenticate(("CertificationReviewer",))
    record = load_path("reports", record_id)
    read_body(DECIDE_SPEC)
    if record["status"] != "SUBMITTED":
        fail("ERR_INVALID_REPORT_STATE",
             "No decision is declared from %s." % record["status"])
    if user_id == record["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The deciding user must differ from submitted_by_user_id.")
    # The decision re-reads the composite the submission produced.
    decision = calc.decision_for_score(record["composite_certification_score"])
    record["decision"] = decision
    record["decided_at"] = db.now_raw()
    record["decided_by_user_id"] = user_id
    record["status"] = "RETURNED" if decision == "DENIED" else "ACCEPTED"
    db.touch(record)
    center = db.get("centers", record["center_id"])
    if center is None:
        return resp.object_response(record)
    if decision in ("CERTIFIED", "CONDITIONAL"):
        center["certification_status"] = decision
        center["consecutive_denied_report_count"] = 0
        center["suspension_reason"] = None
        db.touch(center)
        derive.recompute_ems_posture(center)
        return resp.object_response(record)
    # Denial escalates in hops.
    withdrawn = (center["certification_status"] == "SUSPENDED"
                 and center["consecutive_denied_report_count"] == 1)
    if withdrawn:
        center["consecutive_denied_report_count"] = 2
        center["certification_status"] = "WITHDRAWN"
    else:
        center["consecutive_denied_report_count"] = (
            center["consecutive_denied_report_count"] + 1)
        center["certification_status"] = "SUSPENDED"
    db.touch(center)
    derive.recompute_ems_posture(center)
    for agreement in db.all_of("agreements"):
        if (agreement["hub_center_id"] == center["id"]
                and agreement["status"] == "ACTIVE"):
            derive.suspend_agreement_cascade(
                agreement, "hub certification suspended", "agreement suspended")
    if withdrawn:
        derive.terminate_hub_agreements(center)
    return resp.object_response(record)


@bp.route("/certification-reports/<record_id>/publish", methods=["POST"])
def publish_report(record_id):
    authenticate(("ProgramCoordinator",))
    record = load_path("reports", record_id)
    read_body([])
    if (record["status"] != "ACCEPTED"
            or record["decision"] not in ("CERTIFIED", "CONDITIONAL")):
        fail("ERR_INVALID_REPORT_STATE",
             "No publication is declared from %s." % record["status"])
    center = db.get("centers", record["center_id"])
    if center is None or center["certification_status"] in ("SUSPENDED", "WITHDRAWN"):
        fail("ERR_CENTER_NOT_CERTIFIED",
             "The facility's certification_status blocks publication.")
    record["status"] = "PUBLISHED"
    record["published_at"] = db.now_raw()
    db.touch(record)
    # The rollup overwrites outright, at one decimal place.
    center["public_dtn_compliance_pct"] = db.q1(record["dtn_60_compliance_pct"])
    center["public_report_published_at"] = db.now_raw()
    db.touch(center)
    return resp.object_response(record)
