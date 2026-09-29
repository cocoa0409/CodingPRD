"""Report intake, evidence attachment and office triage (PRD 3.3)."""

from flask import Blueprint, request

import calc
import cascades
from db import S, new_immutable_row, new_row, touch
from errors import fail
from lookup import (evidence_or_404, faculty_or_404, filter_rows, offering_or_404,
                    report_or_404, student_or_404)
from middleware import (ROLE_APPEALS_DEAN, ROLE_FACULTY_REPORTER, ROLE_INTEGRITY_OFFICER,
                        ROLE_STUDENT, auth, require_owner)
from response import created, ok, ok_list, pagination
from serializers import evidence_json, report_json
from shapes import Field, peek, validate
from util import D0

bp = Blueprint("reports", __name__)

COMPONENT_SCORE_FIELDS = [
    Field("code", "string"),
    Field("earned_points", "integer", minimum=0),
]

REPORT_FIELDS = [
    Field("offering_id", "string"),
    Field("student_id", "string"),
    Field("reporter_id", "string", required=False, ignored=True),
    Field("alleged_violation_type", "enum", values=calc.VIOLATION_TYPES),
    Field("narrative", "string", min_len=20, max_len=4000),
    Field("incident_at", "datetime"),
    Field("component_scores", "object_array", items=COMPONENT_SCORE_FIELDS),
]

TRIAGE_FIELDS = [
    Field("decision", "enum", values=("ACCEPT", "RETURN_FOR_INFO", "REJECT_INSUFFICIENT")),
    Field("triage_note", "string"),
]

EVIDENCE_FIELDS = [
    Field("report_id", "string"),
    Field("kind", "enum", values=calc.EVIDENCE_KINDS),
    Field("sha256", "string", pattern=r"^[0-9a-f]{64}$"),
    Field("page_count", "integer", minimum=0, maximum=500),
    Field("similarity_pct", "number", required=False, minimum=0, maximum=100),
]


def refresh_report_evidence(report):
    report["evidence_strength_score"] = calc.evidence_strength_score(report["id"])


def fk_filter(param, resolver):
    raw = request.args.get(param)
    if raw is not None and raw != "":
        resolver(raw)


# ---------------------------------------------------------------- reports

@bp.route("/integrity/reports", methods=["POST"])
def create_report():
    actor = auth([ROLE_FACULTY_REPORTER])
    body = validate(REPORT_FIELDS)
    if body["incident_at"] > S.clock:
        fail("ERR_INVALID_REQUEST", "incident_at may not be after the current logical clock.")
    offering = offering_or_404(body["offering_id"])
    student_or_404(body["student_id"])
    scores = body["component_scores"]
    if not calc.component_scores_join_ok(offering, scores):
        fail("ERR_COMPONENT_SCORES_INCOMPLETE",
             "component_scores must carry exactly one entry per declared grade component.")
    maxima = dict((component["code"], component["max_points"])
                  for component in offering["grade_components"])
    for entry in scores:
        if entry["earned_points"] > maxima[entry["code"]]:
            fail("ERR_INVALID_REQUEST",
                 "earned_points may not exceed the component's max_points.")
    row = new_row(
        offering_id=body["offering_id"],
        student_id=body["student_id"],
        reporter_id=actor.user_id,
        alleged_violation_type=body["alleged_violation_type"],
        narrative=body["narrative"],
        incident_at=body["incident_at"],
        component_scores=[
            {"code": entry["code"], "earned_points": entry["earned_points"]}
            for entry in scores
        ],
        submitted_at=None,
        status="DRAFT",
        evidence_strength_score=D0,
        returned_at=None,
        triaged_at=None,
        resubmission_count=0,
        triage_note=None,
    )
    S.reports[row["id"]] = row
    return created(report_json(row))


@bp.route("/integrity/reports", methods=["GET"])
def list_reports():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER])
    limit, offset = pagination()
    fk_filter("offering_id", offering_or_404)
    fk_filter("student_id", student_or_404)
    fk_filter("reporter_id", faculty_or_404)
    rows = filter_rows(S.reports, {
        "offering_id": "offering_id",
        "student_id": "student_id",
        "reporter_id": "reporter_id",
        "status": "status",
    })
    return ok_list(rows, report_json, limit, offset)


@bp.route("/integrity/reports/<row_id>", methods=["GET"])
def read_report(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_APPEALS_DEAN])
    return ok(report_json(report_or_404(row_id)))


@bp.route("/integrity/reports/<row_id>/submit", methods=["POST"])
def submit_report(row_id):
    actor = auth([ROLE_FACULTY_REPORTER])
    known = S.reports.get(row_id)
    if known is not None:
        require_owner(actor, known["reporter_id"])
    report = report_or_404(row_id)
    if report["status"] not in ("DRAFT", "RETURNED_FOR_INFO"):
        fail("ERR_REPORT_STATE_INVALID",
             "Only a DRAFT or RETURNED_FOR_INFO report may be submitted.")
    reporter = S.faculty_members.get(report["reporter_id"])
    if reporter is None or calc.faculty_training_status(reporter) != "CURRENT":
        fail("ERR_REPORTER_TRAINING_LAPSED",
             "The submitting reporter's integrity training has lapsed.")
    items = calc.evidence_of_report(report["id"])
    if report["status"] == "DRAFT":
        if not calc.evidence_complete(report):
            fail("ERR_EVIDENCE_INCOMPLETE",
                 "The report needs at least one evidence item, including a similarity "
                 "report for a plagiarism allegation.")
        report["status"] = "SUBMITTED"
        report["submitted_at"] = S.clock
    else:
        returned_at = report["returned_at"]
        fresh = [item for item in items
                 if returned_at is None or item["created_at"] >= returned_at]
        if not fresh:
            fail("ERR_EVIDENCE_INCOMPLETE",
                 "At least one evidence item must have been added since the report "
                 "was returned for more information.")
        report["status"] = "SUBMITTED"
        report["resubmission_count"] = report["resubmission_count"] + 1
    refresh_report_evidence(report)
    touch(report)
    offering = S.offerings.get(report["offering_id"])
    cascades.recompute_department(S.departments.get(offering["department_id"])
                                 if offering else None)
    return ok(report_json(report))


@bp.route("/integrity/reports/<row_id>/triage", methods=["POST"])
def triage_report(row_id):
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(TRIAGE_FIELDS)
    report = report_or_404(row_id)
    if report["status"] != "SUBMITTED":
        fail("ERR_REPORT_STATE_INVALID", "Only a SUBMITTED report may be triaged.")
    decision = body["decision"]
    if decision == "ACCEPT":
        if report["evidence_strength_score"] < calc.TRIAGE_ACCEPT_MIN_EVIDENCE_SCORE:
            fail("ERR_EVIDENCE_INCOMPLETE",
                 "Accepting a report requires an evidence strength score of at least 20.00.")
        report["status"] = "ACCEPTED"
        report["triaged_at"] = S.clock
    elif decision == "RETURN_FOR_INFO":
        report["status"] = "RETURNED_FOR_INFO"
        report["returned_at"] = S.clock
    else:
        report["status"] = "REJECTED_INSUFFICIENT"
        report["triaged_at"] = S.clock
    report["triage_note"] = body["triage_note"]
    touch(report)
    return ok(report_json(report))


# ---------------------------------------------------------------- evidence

@bp.route("/integrity/evidence-items", methods=["POST"])
def create_evidence():
    actor = auth([ROLE_FACULTY_REPORTER])
    hinted = peek("report_id")
    known = S.reports.get(hinted) if isinstance(hinted, str) else None
    if known is not None:
        require_owner(actor, known["reporter_id"])
    body = validate(EVIDENCE_FIELDS)
    similarity = body["kind"] == "SIMILARITY_REPORT"
    if similarity and not body.has("similarity_pct"):
        fail("ERR_INVALID_REQUEST",
             "similarity_pct is required when kind is SIMILARITY_REPORT.")
    if not similarity and body.has("similarity_pct"):
        fail("ERR_INVALID_REQUEST",
             "similarity_pct must be absent for every kind other than SIMILARITY_REPORT.")
    report = report_or_404(body["report_id"])
    if report["status"] not in ("DRAFT", "RETURNED_FOR_INFO"):
        fail("ERR_REPORT_STATE_INVALID",
             "Evidence may only be attached to a DRAFT or RETURNED_FOR_INFO report.")
    row = new_immutable_row(
        report_id=report["id"],
        kind=body["kind"],
        sha256=body["sha256"],
        page_count=body["page_count"],
        similarity_pct=body["similarity_pct"],
    )
    S.evidence_items[row["id"]] = row
    refresh_report_evidence(report)
    touch(report)
    return created(evidence_json(row))


@bp.route("/integrity/evidence-items", methods=["GET"])
def list_evidence():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_APPEALS_DEAN])
    limit, offset = pagination()
    fk_filter("report_id", report_or_404)
    rows = filter_rows(S.evidence_items, {"report_id": "report_id", "kind": "kind"})
    return ok_list(rows, evidence_json, limit, offset)


@bp.route("/integrity/evidence-items/<row_id>", methods=["GET"])
def read_evidence(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_APPEALS_DEAN])
    return ok(evidence_json(evidence_or_404(row_id)))


@bp.route("/integrity/reports/<row_id>/evidence-items", methods=["GET"])
def list_report_evidence(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_APPEALS_DEAN, ROLE_STUDENT])
    # PRD 2.6: the parent report is resolved before anything nested.
    report = report_or_404(row_id)
    limit, offset = pagination()
    rows = calc.evidence_of_report(report["id"])
    return ok_list(rows, evidence_json, limit, offset)
