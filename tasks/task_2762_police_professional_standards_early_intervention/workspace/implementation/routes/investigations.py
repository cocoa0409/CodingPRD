"""Investigations: opening, assignment, tolling, findings, close."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    bad_request,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_enum,
    f_int,
    f_num,
    f_bool,
    f_str,
    floor_days,
    new_row,
    paginate,
    q_bool,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("investigations", __name__)

TOLLING_ACTIONS = ("SUSPEND", "RESUME")


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------
@bp.post("/complaints/<complaint_id>/investigations")
@endpoint("IACommander")
def open_investigation(complaint_id):
    complaint = svc.need_complaint(complaint_id)
    payload = body()
    f_str(payload, "opening_note", required=False)
    # tier 8 -- state legality
    if complaint["status"] != "CLASSIFIED":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID")
    # tier 10 -- referential business rules
    if complaint["allegation_count"] < 1:
        raise ApiError("ERR_NO_ALLEGATIONS")
    if svc.investigation_of(complaint["id"]) is not None:
        raise ApiError("ERR_INVESTIGATION_ALREADY_EXISTS")

    statutory_days, required_cert, due_at = calc.investigation_window(
        complaint["classification"], complaint["received_at"], 0
    )
    investigation = new_row(
        "Investigation",
        complaint_id=complaint["id"],
        assigned_investigator_officer_id=None,
        status="UNASSIGNED",
        statutory_days=statutory_days,
        tolled_days=0,
        due_at=due_at,
        overdue=False,
        assignment_count=0,
        interview_held_count=0,
        findings_submitted_at=None,
        suspended_at=None,
        required_certification_level=required_cert,
        closed_at=None,
    )
    db.investigations[investigation["id"]] = investigation
    complaint["status"] = "UNDER_INVESTIGATION"
    touch(complaint)
    return respond_object(svc.dump_investigation(investigation), 201)


@bp.get("/investigations/<investigation_id>")
@endpoint(
    "Supervisor", "Investigator", "IACommander", "RecordsCustodian", "AppealsOfficer"
)
def read_investigation(investigation_id):
    return respond_object(
        svc.dump_investigation(svc.need_investigation(investigation_id))
    )


@bp.get("/investigations")
@endpoint(
    "Supervisor", "Investigator", "IACommander", "RecordsCustodian", "AppealsOfficer"
)
def list_investigations():
    complaint_id = q_str("complaint_id")
    assignee_id = q_str("assigned_investigator_officer_id")
    status = q_enum("status", calc.INVESTIGATION_STATUSES)
    overdue = q_bool("overdue")
    rows = sort_created(list(db.investigations.values()))
    if complaint_id is not None:
        rows = [r for r in rows if r["complaint_id"] == complaint_id]
    if assignee_id is not None:
        rows = [
            r for r in rows if r["assigned_investigator_officer_id"] == assignee_id
        ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if overdue is not None:
        rows = [r for r in rows if calc.is_overdue(r) == overdue]
    return paginate(rows, dumper=svc.dump_investigation)


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------
@bp.post("/investigations/<investigation_id>/assignments")
@endpoint("IACommander")
def assign_investigation(investigation_id):
    investigation = svc.need_investigation(investigation_id)
    payload = body()
    expected_version = f_int(payload, "expected_investigation_version")
    nominee_id = f_str(payload, "investigator_officer_id", required=False)
    f_str(payload, "assignment_note", required=False)
    # tier 5 -- body reference existence
    nominee = svc.need_officer(nominee_id) if nominee_id is not None else None
    # tier 7 -- version pinning
    if expected_version != investigation["version"]:
        raise ApiError("ERR_STALE_INVESTIGATION_VERSION")
    # tier 8 -- state legality
    if investigation["status"] not in ("UNASSIGNED", "ASSIGNED"):
        raise ApiError("ERR_INVESTIGATION_STATE_INVALID")

    complaint_id = investigation["complaint_id"]
    if nominee is None:
        # tier 10 -- referential business rules
        nominee = calc.select_investigator(investigation, complaint_id, g.user_id)
        if nominee is None:
            raise ApiError("ERR_NO_ELIGIBLE_INVESTIGATOR")
    else:
        failures = calc.eligibility_failures(
            nominee, investigation, complaint_id, g.user_id
        )
        # tier 9 -- business safety
        if failures & {5, 6, 7, 8}:
            raise ApiError("ERR_INVESTIGATOR_CONFLICT")
        # tier 12 -- business constraints
        if 4 in failures:
            raise ApiError("ERR_CASE_LOAD_EXCEEDED")
        if failures & {1, 2, 3}:
            raise ApiError("ERR_CERTIFICATION_INSUFFICIENT")

    svc.release_investigator(investigation)
    investigation["assigned_investigator_officer_id"] = nominee["id"]
    investigation["assignment_count"] += 1
    investigation["status"] = "ASSIGNED"
    touch(investigation)
    nominee["open_case_load"] += 1
    touch(nominee)
    return respond_object(svc.dump_investigation(investigation))


# ---------------------------------------------------------------------------
# Tolling
# ---------------------------------------------------------------------------
@bp.post("/investigations/<investigation_id>/tolling")
@endpoint("Investigator", "IACommander")
def toll_investigation(investigation_id):
    investigation = svc.need_investigation(investigation_id)
    payload = body()
    action = f_enum(payload, "action", TOLLING_ACTIONS)
    f_str(payload, "tolling_reason", required=(action == "SUSPEND"))
    complaint = db.complaints.get(investigation["complaint_id"])
    # tier 8 -- state legality
    if action == "SUSPEND":
        if investigation["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVESTIGATION_STATE_INVALID")
        investigation["status"] = "TOLLED"
        investigation["suspended_at"] = db.clock
        touch(investigation)
        return respond_object(svc.dump_investigation(investigation))

    if investigation["status"] not in ("TOLLED", "PENDING_REVIEW"):
        raise ApiError("ERR_INVESTIGATION_STATE_INVALID")

    if investigation["status"] == "TOLLED":
        suspended_at = investigation.get("suspended_at")
        elapsed = floor_days(db.clock, suspended_at) if suspended_at else 0
        investigation["tolled_days"] += elapsed
        investigation["suspended_at"] = None
        investigation["status"] = "IN_PROGRESS"
        if complaint is not None:
            svc.refresh_investigation_window(investigation, complaint)
        touch(investigation)
        return respond_object(svc.dump_investigation(investigation))

    # RESUME from PENDING_REVIEW -- the commander returns the file for more work.
    if any(
        a["disposition"] != "PENDING"
        for a in svc.allegations_of(investigation["complaint_id"])
    ):
        raise ApiError("ERR_INVESTIGATION_STATE_INVALID")
    investigation["status"] = "IN_PROGRESS"
    investigation["findings_submitted_at"] = None
    touch(investigation)
    if complaint is not None and complaint["status"] == "ADJUDICATION":
        complaint["status"] = "UNDER_INVESTIGATION"
        touch(complaint)
    return respond_object(svc.dump_investigation(investigation))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
@bp.post("/investigations/<investigation_id>/findings")
@endpoint("Investigator")
def submit_findings(investigation_id):
    investigation = svc.need_investigation(investigation_id)
    payload = body()
    # tier 4 -- schema
    raw = payload.get("allegation_findings")
    if raw is None:
        bad_request("Field 'allegation_findings' is required.")
    if not isinstance(raw, list) or not raw:
        bad_request("Field 'allegation_findings' must be a non-empty array.")
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            bad_request("Each 'allegation_findings' entry must be an object.")
        entries.append(
            {
                "allegation_id": f_str(item, "allegation_id"),
                # PRD section 2.7 tier 4 enumerates the declared numeric ranges and
                # does not include the evidence weights; PRD section 3.6's worked
                # example uses weights of 5001 and 5000, so no upper bound applies.
                "evidence_weight_for": f_num(
                    item, "evidence_weight_for", minimum=0
                ),
                "evidence_weight_against": f_num(
                    item, "evidence_weight_against", minimum=0
                ),
                "policy_compliant": f_bool(item, "policy_compliant"),
            }
        )
    f_str(payload, "summary", required=False)
    # tier 6 -- resource-level ownership
    if investigation.get("assigned_investigator_officer_id") != g.user_id:
        raise ApiError("ERR_NOT_ASSIGNED_INVESTIGATOR")
    # tier 8 -- state legality
    if investigation["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVESTIGATION_STATE_INVALID")
    # tier 10 -- referential business rules
    allegations = svc.allegations_of(investigation["complaint_id"])
    expected_ids = {a["id"] for a in allegations}
    supplied_ids = [e["allegation_id"] for e in entries]
    if len(set(supplied_ids)) != len(supplied_ids) or set(supplied_ids) != expected_ids:
        raise ApiError("ERR_FINDINGS_INCOMPLETE")
    if investigation["interview_held_count"] < 1:
        raise ApiError("ERR_NO_INTERVIEW_HELD")

    by_id = {a["id"]: a for a in allegations}
    for entry in entries:
        allegation = by_id[entry["allegation_id"]]
        allegation["evidence_weight_for"] = entry["evidence_weight_for"]
        allegation["evidence_weight_against"] = entry["evidence_weight_against"]
        allegation["policy_compliant"] = entry["policy_compliant"]
        support_pct, preponderance_met = calc.preponderance(
            entry["evidence_weight_for"], entry["evidence_weight_against"]
        )
        allegation["support_pct"] = support_pct
        allegation["preponderance_met"] = preponderance_met
        touch(allegation)
    investigation["findings_submitted_at"] = db.clock
    investigation["status"] = "PENDING_REVIEW"
    touch(investigation)
    complaint = db.complaints.get(investigation["complaint_id"])
    if complaint is not None:
        complaint["status"] = "ADJUDICATION"
        touch(complaint)
    return respond_object(svc.dump_investigation(investigation))


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------
@bp.post("/investigations/<investigation_id>/close")
@endpoint("IACommander")
def close_investigation(investigation_id):
    investigation = svc.need_investigation(investigation_id)
    payload = body()
    f_str(payload, "closing_note", required=False)
    # tier 8 -- state legality
    if investigation["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVESTIGATION_STATE_INVALID")
    # tier 10 -- referential business rules
    allegations = svc.allegations_of(investigation["complaint_id"])
    if any(a["disposition"] == "PENDING" for a in allegations):
        raise ApiError("ERR_PENDING_DISPOSITIONS")

    investigation["status"] = "CLOSED"
    investigation["closed_at"] = db.clock
    touch(investigation)
    svc.release_investigator(investigation)
    complaint = db.complaints.get(investigation["complaint_id"])
    if complaint is not None:
        complaint["status"] = "CLOSED"
        complaint["closed_at"] = db.clock
        svc.recompute_sustained_count(complaint)
        complaint["retention_until"] = calc.retention_until_for(
            complaint["id"], complaint["closed_at"]
        )
        touch(complaint)
    return respond_object(svc.dump_investigation(investigation))
