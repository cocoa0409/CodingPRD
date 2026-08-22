"""Placements, adjuster directives, progression reviews and compliance audits."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import domain
import serialize
from api_core import (_claim_or_404, _rs_or_404, _job_or_404, _supervisor_or_404,
                      RISK_CLASSES)
from auth import require_roles, own_placement, own_claim
from errors import fail
from response import ok, created, ok_list, paginate
from store import db, stamp_new, touch, ordered
from util import parse_date, days_between, D
from validators import (body_of, str_field, enum_field, int_field, num_field,
                        bool_field, date_field, id_list_field, not_inverted,
                        pagination, query_enum, query_str, bad)

bp = Blueprint("placement", __name__)

PLACEMENT_STATUSES = ("PROPOSED", "ADJUSTER_PENDING", "ACTIVE",
                      "PROGRESSION_HOLD", "SUSPENDED", "COMPLETED",
                      "TERMINATED_EARLY", "DECLINED")
COMPLIANCE_STATUSES = ("COMPLIANT", "WATCH", "NONCOMPLIANT", "REMEDIATED")
SUSPENSION_REASONS = ("RESTRICTION_CONFLICT", "MEDICAL_HOLD", "OPERATIONAL")
DIRECTIVE_STATUSES = ("PENDING", "AUTHORIZED", "AUTHORIZED_WITH_CONDITIONS",
                      "DENIED", "SUPERSEDED")
DECISIONS = ("AUTHORIZED", "AUTHORIZED_WITH_CONDITIONS", "DENIED")
REVIEW_STATUSES = ("SCHEDULED", "IN_REVIEW", "ADVANCED", "EXTENDED", "ESCALATED")
REVIEW_DECISIONS = ("ADVANCE", "EXTEND", "ESCALATE", "DEFER")
FINDING_SEVERITIES = ("NONE", "MINOR", "MAJOR", "CRITICAL")
FINDING_CODES = ("RESTRICTION_DEVIATION", "HOURS_DEVIATION", "SUPERVISION_GAP",
                 "DOCUMENTATION", "NONE")


def _placement_or_404(placement_id):
    row = db.placements.get(placement_id)
    if row is None:
        fail("ERR_PLACEMENT_NOT_FOUND", "No Placement row matches that id.")
    return row


def _directive_or_404(directive_id):
    row = db.directives.get(directive_id)
    if row is None:
        fail("ERR_DIRECTIVE_NOT_FOUND",
             "No AdjusterDirective row matches that id.")
    return row


def _review_or_404(review_id):
    row = db.progression_reviews.get(review_id)
    if row is None:
        fail("ERR_PROGRESSION_REVIEW_NOT_FOUND",
             "No ProgressionReview row matches that id.")
    return row


def _employee_of_claim(claim):
    return db.employees[claim["employee_id"]]


def _governing_rs(placement):
    rs = calc.active_restriction_set(placement["claim_id"])
    if rs is None:
        rs = db.restriction_sets[placement["restriction_set_id"]]
    return rs


# ------------------------------------------------------- placement creation
def _persist_placement(rs, job, claim, start, end, hours):
    row = stamp_new({
        "claim_id": rs["claim_id"],
        "restriction_set_id": rs["id"],
        "transitional_job_id": job["id"],
        "supervisor_id": job["supervisor_id"],
        "created_by_user_id": g.user_id,
        "placement_status": "PROPOSED",
        "compliance_status": "COMPLIANT",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "scheduled_hours_per_day": hours,
        "activated_on": None,
        "ended_on": None,
        "suspension_reason": None,
        "decline_reason": None,
        "logged_hours": [],
        "progression_step": 0,
        "match_score": calc.restriction_match_score(rs, job),
        "reinjury_risk_score": calc.reinjury_risk_baseline(rs, job),
        "reinjury_risk_variant": "BASELINE",
    })
    db.placements[row["id"]] = row
    touch(rs)
    return row


def _posture_gates(claim, restricted_too):
    posture = calc.claim_rtw_posture(claim)
    if posture == "FROZEN":
        fail("ERR_CLAIM_POSTURE_FROZEN", "The claim's rtw_posture is FROZEN.")
    if restricted_too and posture == "RESTRICTED":
        fail("ERR_CLAIM_POSTURE_RESTRICTED",
             "The claim's rtw_posture is RESTRICTED.")


@bp.post("/rtw/placements")
@require_roles("RTWCoordinator", "ProgramAdmin")
def create_placement():
    body = body_of()
    restriction_set_id = str_field(body, "restriction_set_id")
    transitional_job_id = str_field(body, "transitional_job_id")
    start = date_field(body, "start_date")
    end = date_field(body, "end_date")
    not_inverted(start, end, "start_date", "end_date")
    hours = num_field(body, "scheduled_hours_per_day", gt=0, le=12)
    expected_version = int_field(body, "expected_restriction_set_version")
    # priority 5
    rs = _rs_or_404(restriction_set_id)
    job = _job_or_404(transitional_job_id)
    claim = db.claims[rs["claim_id"]]
    employee = _employee_of_claim(claim)
    # priority 10
    if rs["status"] != "ACTIVE":
        fail("ERR_RESTRICTION_SET_NOT_ACTIVE",
             "The referenced RestrictionSet is not ACTIVE.")
    # priority 11
    if claim["claim_status"] != "RTW_ELIGIBLE":
        fail("ERR_CLAIM_NOT_RTW_ELIGIBLE",
             "The owning Claim is not RTW_ELIGIBLE.")
    # priorities 15 and 16
    _posture_gates(claim, restricted_too=True)
    # priority 19
    if domain.restriction_breach(rs, job, hours):
        fail("ERR_RESTRICTION_VIOLATION",
             "The job's demand or the requested schedule breaches a restriction.")
    # priority 20
    match_score = calc.restriction_match_score(rs, job)
    if D(match_score) < calc.MIN_ELIGIBLE_MATCH_SCORE:
        fail("ERR_MATCH_SCORE_BELOW_FLOOR",
             "The computed match_score is below the eligibility floor.")
    # priority 21
    if calc.reinjury_risk_baseline(rs, job) >= calc.RISK_ESCALATION_THRESHOLD:
        fail("ERR_REINJURY_RISK_TOO_HIGH",
             "The BASELINE reinjury_risk_score reaches the escalation threshold.")
    # priority 25
    if (start < parse_date(rs["effective_from"])
            or end > parse_date(rs["valid_through"])):
        fail("ERR_PLACEMENT_OUTSIDE_RESTRICTION_WINDOW",
             "The placement window is not inside the restriction window.")
    # priority 26
    if domain.worker_window_overlap(claim["employee_id"], start, end):
        fail("ERR_PLACEMENT_WINDOW_OVERLAP",
             "The window intersects another live placement of this worker.")
    # priority 27
    if domain.job_changeover_conflict(job["id"], start):
        fail("ERR_JOB_CHANGEOVER_BUFFER",
             "The start_date falls inside another occupant's changeover buffer.")
    # priority 29
    if domain.job_seat_unavailable(job, start, end):
        fail("ERR_JOB_SEAT_UNAVAILABLE",
             "Seat capacity would be exceeded on at least one day.")
    # priority 30
    if job["job_status"] != "OPEN":
        fail("ERR_JOB_NOT_OPEN", "The referenced TransitionalJob is not OPEN.")
    # priority 41
    if expected_version != rs["version"]:
        fail("ERR_STALE_RESTRICTION_SET_VERSION",
             "expected_restriction_set_version does not match.")
    row = _persist_placement(rs, job, claim, start, end, hours)
    return created(serialize.placement(row))


@bp.post("/rtw/placements/auto-match")
@require_roles("RTWCoordinator")
def auto_match_placement():
    body = body_of()
    restriction_set_id = str_field(body, "restriction_set_id")
    start = date_field(body, "start_date")
    end = date_field(body, "end_date")
    not_inverted(start, end, "start_date", "end_date")
    hours = num_field(body, "scheduled_hours_per_day", gt=0, le=12)
    expected_version = int_field(body, "expected_restriction_set_version")
    department_code = str_field(body, "department_code", required=False)
    exclude_job_ids = id_list_field(body, "exclude_job_ids", [])
    # priority 5
    rs = _rs_or_404(restriction_set_id)
    claim = db.claims[rs["claim_id"]]
    # priority 10
    if rs["status"] != "ACTIVE":
        fail("ERR_RESTRICTION_SET_NOT_ACTIVE",
             "The referenced RestrictionSet is not ACTIVE.")
    # priority 11
    if claim["claim_status"] != "RTW_ELIGIBLE":
        fail("ERR_CLAIM_NOT_RTW_ELIGIBLE",
             "The owning Claim is not RTW_ELIGIBLE.")
    # priorities 15 and 16
    _posture_gates(claim, restricted_too=True)
    # priority 26
    if domain.worker_window_overlap(claim["employee_id"], start, end):
        fail("ERR_PLACEMENT_WINDOW_OVERLAP",
             "The window intersects another live placement of this worker.")
    # priority 31 - the selector
    candidates = []
    for job in ordered(list(db.jobs.values())):
        if job["job_status"] != "OPEN":
            continue
        supervisor = db.supervisors.get(job["supervisor_id"])
        if supervisor is None or supervisor["oversight_status"] != "ACTIVE":
            continue
        if calc.supervisor_training_status(supervisor["id"]) not in (
                "VALID", "EXPIRING_SOON"):
            continue
        if department_code is not None and job["department_code"] != department_code:
            continue
        if job["id"] in exclude_job_ids:
            continue
        if domain.job_demand_breach(rs, job):
            continue
        if domain.job_changeover_conflict(job["id"], start):
            continue
        if domain.job_seat_unavailable(job, start, end):
            continue
        score = calc.restriction_match_score(rs, job)
        if D(score) < calc.MIN_ELIGIBLE_MATCH_SCORE:
            continue
        if calc.reinjury_risk_baseline(rs, job) >= calc.RISK_ESCALATION_THRESHOLD:
            continue
        candidates.append((job, score))
    if not candidates:
        fail("ERR_NO_ELIGIBLE_JOB",
             "No transitional job satisfies the selector's eligibility filter.")
    candidates.sort(key=lambda item: (
        -D(item[1]),
        calc.RISK_CLASS_RANK[item[0]["risk_class"]],
        -item[0]["hourly_rate_cents"],
        item[0]["created_at"],
        item[0]["_seq"],
    ))
    job = candidates[0][0]
    # priority 41
    if expected_version != rs["version"]:
        fail("ERR_STALE_RESTRICTION_SET_VERSION",
             "expected_restriction_set_version does not match.")
    row = _persist_placement(rs, job, claim, start, end, hours)
    return created(serialize.placement(row))


@bp.get("/rtw/placements/<placement_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "Supervisor", "Employee")
def read_placement(placement_id):
    row = _placement_or_404(placement_id)
    own_placement(row)
    return ok(serialize.placement(row))


@bp.get("/rtw/placements")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "Supervisor")
def list_placements():
    limit, offset = pagination()
    claim_id = query_str("claim_id")
    restriction_set_id = query_str("restriction_set_id")
    transitional_job_id = query_str("transitional_job_id")
    supervisor_id = query_str("supervisor_id")
    placement_status = query_enum("placement_status", PLACEMENT_STATUSES)
    compliance_status = query_enum("compliance_status", COMPLIANCE_STATUSES)
    if restriction_set_id is not None:
        _rs_or_404(restriction_set_id)
    if transitional_job_id is not None:
        _job_or_404(transitional_job_id)
    if supervisor_id is not None:
        _supervisor_or_404(supervisor_id)
    rows = list(db.placements.values())
    if claim_id is not None:
        rows = [p for p in rows if p["claim_id"] == claim_id]
    if restriction_set_id is not None:
        rows = [p for p in rows if p["restriction_set_id"] == restriction_set_id]
    if transitional_job_id is not None:
        rows = [p for p in rows
                if p["transitional_job_id"] == transitional_job_id]
    if supervisor_id is not None:
        rows = [p for p in rows if p["supervisor_id"] == supervisor_id]
    if placement_status:
        rows = [p for p in rows if p["placement_status"] == placement_status]
    if compliance_status:
        rows = [p for p in rows if p["compliance_status"] == compliance_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.placement(r) for r in page], limit, offset, total)


@bp.get("/rtw/claims/<claim_id>/placements")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "Employee")
def list_claim_placements(claim_id):
    limit, offset = pagination()
    placement_status = query_enum("placement_status", PLACEMENT_STATUSES)
    claim = _claim_or_404(claim_id)
    own_claim(claim)
    rows = [p for p in db.placements.values() if p["claim_id"] == claim_id]
    if placement_status:
        rows = [p for p in rows if p["placement_status"] == placement_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.placement(r) for r in page], limit, offset, total)


# ------------------------------------------------------- lifecycle actions
@bp.post("/rtw/placements/<placement_id>/submit-to-adjuster")
@require_roles("RTWCoordinator")
def submit_to_adjuster(placement_id):
    row = _placement_or_404(placement_id)
    domain.check_terminal("placement", row["placement_status"])
    domain.check_from_state(row["placement_status"], ("PROPOSED",))
    rs = db.restriction_sets[row["restriction_set_id"]]
    if rs["status"] != "ACTIVE":
        fail("ERR_RESTRICTION_SET_NOT_ACTIVE",
             "The referenced RestrictionSet is not ACTIVE.")
    claim = db.claims[row["claim_id"]]
    _posture_gates(claim, restricted_too=False)
    job = db.jobs[row["transitional_job_id"]]
    employee = _employee_of_claim(claim)
    directive = stamp_new({
        "placement_id": row["id"],
        "directive_status": "PENDING",
        "requested_weekly_cost_cents":
            calc.projected_weekly_cost_cents(row, job, employee),
        "authorized_weekly_cost_cents": 0,
        "condition_note": None,
        "denial_reason": None,
        "decided_by_user_id": None,
        "decided_at": None,
    })
    db.directives[directive["id"]] = directive
    row["placement_status"] = "ADJUSTER_PENDING"
    touch(row)
    return ok(serialize.placement(row))


@bp.get("/rtw/placements/<placement_id>/adjuster-directives")
@require_roles("ProgramAdmin", "RTWCoordinator", "ClaimAdjuster",
               "OccHealthNurse")
def list_directives(placement_id):
    limit, offset = pagination()
    directive_status = query_enum("directive_status", DIRECTIVE_STATUSES)
    _placement_or_404(placement_id)
    rows = [d for d in db.directives.values()
            if d["placement_id"] == placement_id]
    if directive_status:
        rows = [d for d in rows if d["directive_status"] == directive_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.directive(r) for r in page], limit, offset, total)


@bp.post("/rtw/adjuster-directives/<directive_id>/decide")
@require_roles("ClaimAdjuster")
def decide_directive(directive_id):
    body = body_of()
    decision = enum_field(body, "decision", DECISIONS)
    authorized = None
    condition_note = None
    denial_reason = None
    if decision in ("AUTHORIZED", "AUTHORIZED_WITH_CONDITIONS"):
        authorized = int_field(body, "authorized_weekly_cost_cents")
    if decision == "AUTHORIZED_WITH_CONDITIONS":
        condition_note = str_field(body, "condition_note")
    if decision == "DENIED":
        denial_reason = str_field(body, "denial_reason")
    row = _directive_or_404(directive_id)
    placement = db.placements[row["placement_id"]]
    claim = db.claims[placement["claim_id"]]
    # priority 6 - only the claim's own adjuster operator may decide
    if g.user_id != claim["adjuster_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Only the claim's adjuster_user_id may decide this directive.")
    domain.check_terminal("directive", row["directive_status"])
    # priority 12
    if row["directive_status"] != "PENDING":
        fail("ERR_DIRECTIVE_ALREADY_DECIDED",
             "The addressed AdjusterDirective is no longer PENDING.")
    # priority 40
    if (decision in ("AUTHORIZED", "AUTHORIZED_WITH_CONDITIONS")
            and authorized > claim["max_authorized_weekly_cost_cents"]):
        fail("ERR_ADJUSTER_AUTHORIZATION_EXCEEDED",
             "authorized_weekly_cost_cents exceeds the claim's ceiling.")
    row["directive_status"] = decision
    if decision == "DENIED":
        row["authorized_weekly_cost_cents"] = 0
        row["denial_reason"] = denial_reason
    else:
        row["authorized_weekly_cost_cents"] = authorized
        if decision == "AUTHORIZED_WITH_CONDITIONS":
            row["condition_note"] = condition_note
    row["decided_by_user_id"] = g.user_id
    row["decided_at"] = db.now_iso()
    touch(row)
    return ok(serialize.directive(row))


def _current_directive(placement_id):
    live = [d for d in calc.directives_of_placement(placement_id)
            if d["directive_status"] != "SUPERSEDED"]
    return live[-1] if live else None


@bp.post("/rtw/placements/<placement_id>/activate")
@require_roles("RTWCoordinator")
def activate_placement(placement_id):
    row = _placement_or_404(placement_id)
    domain.check_terminal("placement", row["placement_status"])
    domain.check_from_state(row["placement_status"], ("ADJUSTER_PENDING",))
    rs = db.restriction_sets[row["restriction_set_id"]]
    if rs["status"] != "ACTIVE":
        fail("ERR_RESTRICTION_SET_NOT_ACTIVE",
             "The referenced RestrictionSet is not ACTIVE.")
    claim = db.claims[row["claim_id"]]
    _posture_gates(claim, restricted_too=False)
    supervisor = db.supervisors[row["supervisor_id"]]
    # priority 23
    if supervisor["oversight_status"] != "ACTIVE":
        fail("ERR_SUPERVISOR_OVERSIGHT_SUSPENDED",
             "The placement's supervisor is SUSPENDED.")
    # priority 24
    if calc.supervisor_training_status(supervisor["id"]) not in (
            "VALID", "EXPIRING_SOON"):
        fail("ERR_SUPERVISOR_TRAINING_EXPIRED",
             "The placement's supervisor has no current RTW_CORE training.")
    directive = _current_directive(row["id"])
    # priority 38
    if directive is None or directive["directive_status"] == "PENDING":
        fail("ERR_ADJUSTER_AUTHORIZATION_MISSING",
             "No decided AdjusterDirective exists for this placement.")
    # priority 39
    if directive["directive_status"] not in ("AUTHORIZED",
                                             "AUTHORIZED_WITH_CONDITIONS"):
        fail("ERR_ADJUSTER_DIRECTIVE_DENIED",
             "The placement's current AdjusterDirective is DENIED.")
    job = db.jobs[row["transitional_job_id"]]
    employee = _employee_of_claim(claim)
    projected = calc.projected_weekly_cost_cents(row, job, employee)
    # priority 40
    if projected > directive["authorized_weekly_cost_cents"]:
        fail("ERR_ADJUSTER_AUTHORIZATION_EXCEEDED",
             "projected_weekly_cost_cents exceeds the authorized ceiling.")
    row["placement_status"] = "ACTIVE"
    row["activated_on"] = row["start_date"]
    touch(row)
    due = parse_date(row["start_date"]) + timedelta(
        days=calc.PROGRESSION_REVIEW_INTERVAL_DAYS)
    domain.new_progression_review(row["id"], 1, due)
    return ok(serialize.placement(row))


@bp.post("/rtw/placements/<placement_id>/suspend")
@require_roles("RTWCoordinator", "OccHealthNurse")
def suspend_placement(placement_id):
    body = body_of()
    reason = enum_field(body, "suspension_reason", SUSPENSION_REASONS)
    row = _placement_or_404(placement_id)
    domain.check_terminal("placement", row["placement_status"])
    domain.check_from_state(row["placement_status"], ("ACTIVE",))
    row["placement_status"] = "SUSPENDED"
    row["suspension_reason"] = reason
    touch(row)
    return ok(serialize.placement(row))


@bp.post("/rtw/placements/<placement_id>/resume")
@require_roles("RTWCoordinator")
def resume_placement(placement_id):
    row = _placement_or_404(placement_id)
    domain.check_terminal("placement", row["placement_status"])
    domain.check_from_state(row["placement_status"], ("SUSPENDED",))
    rs = db.restriction_sets[row["restriction_set_id"]]
    if rs["status"] != "ACTIVE":
        fail("ERR_RESTRICTION_SET_NOT_ACTIVE",
             "The referenced RestrictionSet is not ACTIVE.")
    claim = db.claims[row["claim_id"]]
    _posture_gates(claim, restricted_too=False)
    supervisor = db.supervisors[row["supervisor_id"]]
    if supervisor["oversight_status"] != "ACTIVE":
        fail("ERR_SUPERVISOR_OVERSIGHT_SUSPENDED",
             "The placement's supervisor is SUSPENDED.")
    if calc.supervisor_training_status(supervisor["id"]) not in (
            "VALID", "EXPIRING_SOON"):
        fail("ERR_SUPERVISOR_TRAINING_EXPIRED",
             "The placement's supervisor has no current RTW_CORE training.")
    job = db.jobs[row["transitional_job_id"]]
    if domain.job_seat_unavailable(job, parse_date(row["start_date"]),
                                   parse_date(row["end_date"]),
                                   exclude_placement_id=row["id"]):
        fail("ERR_JOB_SEAT_UNAVAILABLE",
             "Seat capacity would be exceeded on at least one day.")
    row["placement_status"] = "ACTIVE"
    row["suspension_reason"] = None
    touch(row)
    return ok(serialize.placement(row))


@bp.post("/rtw/placements/<placement_id>/extend")
@require_roles("RTWCoordinator")
def extend_placement(placement_id):
    body = body_of()
    new_end_date = date_field(body, "new_end_date")
    reason = str_field(body, "reason")
    row = _placement_or_404(placement_id)
    domain.check_terminal("placement", row["placement_status"])
    claim = db.claims[row["claim_id"]]
    _posture_gates(claim, restricted_too=False)
    rs = db.restriction_sets[row["restriction_set_id"]]
    job = db.jobs[row["transitional_job_id"]]
    start = parse_date(row["start_date"])
    # priority 19
    if domain.restriction_breach(rs, job, row["scheduled_hours_per_day"]):
        fail("ERR_RESTRICTION_VIOLATION",
             "The job's demand or the schedule breaches a restriction.")
    # priority 25
    if (start < parse_date(rs["effective_from"])
            or new_end_date > parse_date(rs["valid_through"])):
        fail("ERR_PLACEMENT_OUTSIDE_RESTRICTION_WINDOW",
             "The placement window is not inside the restriction window.")
    # priority 26
    if domain.worker_window_overlap(claim["employee_id"], start, new_end_date,
                                    exclude_placement_id=row["id"]):
        fail("ERR_PLACEMENT_WINDOW_OVERLAP",
             "The window intersects another live placement of this worker.")
    projection = calc.projected_cumulative(row, new_end_date)
    # priority 36
    if projection >= calc.DURATION_HARD_CAP_DAYS:
        fail("ERR_DURATION_HARD_CAP",
             "The projected cumulative duration reaches the hard cap.")
    # priority 37
    if projection >= calc.DURATION_SOFT_CAP_DAYS:
        has_continue = any(c["review_status"] == "DECIDED_CONTINUE"
                           for c in calc.case_reviews_of_placement(row["id"]))
        if not has_continue:
            fail("ERR_DURATION_SOFT_CAP_REQUIRES_CASE_REVIEW",
                 "The projected duration reaches the soft cap without a "
                 "DECIDED_CONTINUE case review.")
    # priority 40
    directive = _current_directive(row["id"])
    if directive is not None:
        employee = _employee_of_claim(claim)
        projected_cost = calc.projected_weekly_cost_cents(row, job, employee)
        if projected_cost > directive["authorized_weekly_cost_cents"]:
            fail("ERR_ADJUSTER_AUTHORIZATION_EXCEEDED",
                 "projected_weekly_cost_cents exceeds the authorized ceiling.")
    row["end_date"] = new_end_date.isoformat()
    touch(row)
    return ok(serialize.placement(row))


@bp.post("/rtw/placements/<placement_id>/complete")
@require_roles("RTWCoordinator")
def complete_placement(placement_id):
    row = _placement_or_404(placement_id)
    domain.check_terminal("placement", row["placement_status"])
    domain.check_from_state(row["placement_status"], ("ACTIVE",))
    domain.end_placement(row, "COMPLETED")
    return ok(serialize.placement(row))


@bp.post("/rtw/placements/<placement_id>/terminate")
@require_roles("RTWCoordinator", "ProgramAdmin")
def terminate_placement(placement_id):
    body = body_of()
    reason = str_field(body, "reason")
    row = _placement_or_404(placement_id)
    domain.check_terminal("placement", row["placement_status"])
    domain.check_from_state(row["placement_status"],
                            ("PROPOSED", "ADJUSTER_PENDING", "ACTIVE",
                             "PROGRESSION_HOLD", "SUSPENDED"))
    if row["placement_status"] in ("PROPOSED", "ADJUSTER_PENDING"):
        domain.end_placement(row, "DECLINED", reason)
    else:
        domain.end_placement(row, "TERMINATED_EARLY")
    return ok(serialize.placement(row))


@bp.post("/rtw/placements/<placement_id>/hours-log")
@require_roles("Supervisor", "RTWCoordinator", "ProgramAdmin")
def log_hours(placement_id):
    body = body_of()
    work_date = date_field(body, "work_date")
    hours_worked = num_field(body, "hours_worked", ge=0)
    row = _placement_or_404(placement_id)
    own_placement(row)
    # priority 22
    active_rs = calc.active_restriction_set(row["claim_id"])
    if active_rs is not None and hours_worked > active_rs["max_hours_per_day"]:
        fail("ERR_HOURS_EXCEED_RESTRICTION",
             "hours_worked exceeds the active restriction's max_hours_per_day.")
    stamp = work_date.isoformat()
    entries = [e for e in row["logged_hours"] if e["work_date"] != stamp]
    entries.append({"work_date": stamp, "hours_worked": hours_worked})
    entries.sort(key=lambda e: e["work_date"])
    row["logged_hours"] = entries
    touch(row)
    return ok(serialize.placement(row))


# --------------------------------------------------------- progression ladder
@bp.get("/rtw/placements/<placement_id>/progression-reviews")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "Supervisor")
def list_progression_reviews(placement_id):
    limit, offset = pagination()
    review_status = query_enum("review_status", REVIEW_STATUSES)
    row = _placement_or_404(placement_id)
    own_placement(row)
    rows = [r for r in db.progression_reviews.values()
            if r["placement_id"] == placement_id]
    if review_status:
        rows = [r for r in rows if r["review_status"] == review_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.progression_review(r) for r in page], limit,
                   offset, total)


@bp.get("/rtw/progression-reviews/<review_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "Supervisor")
def read_progression_review(review_id):
    return ok(serialize.progression_review(_review_or_404(review_id)))


@bp.post("/rtw/progression-reviews/<review_id>/open")
@require_roles("RTWCoordinator", "OccHealthNurse")
def open_progression_review(review_id):
    row = _review_or_404(review_id)
    domain.check_terminal("progression_review", row["review_status"])
    domain.check_from_state(row["review_status"], ("SCHEDULED",))
    placement = db.placements[row["placement_id"]]
    if placement["placement_status"] not in ("ACTIVE", "PROGRESSION_HOLD"):
        fail("ERR_INVALID_STATE",
             "The owning placement is not ACTIVE or PROGRESSION_HOLD.")
    row["review_status"] = "IN_REVIEW"
    row["reviewed_by_user_id"] = g.user_id
    touch(row)
    return ok(serialize.progression_review(row))


def _panel_in_progress(placement_id):
    return any(c["review_status"] in ("OPEN", "VOTING")
               for c in calc.case_reviews_of_placement(placement_id))


@bp.post("/rtw/progression-reviews/<review_id>/decide")
@require_roles("RTWCoordinator", "OccHealthNurse")
def decide_progression_review(review_id):
    body = body_of()
    decision = enum_field(body, "decision", REVIEW_DECISIONS)
    outcome_note = str_field(body, "outcome_note", required=False,
                             allow_empty=True)
    row = _review_or_404(review_id)
    domain.check_terminal("progression_review", row["review_status"])
    domain.check_from_state(row["review_status"], ("IN_REVIEW",))
    placement = db.placements[row["placement_id"]]
    # priority 32
    if (decision == "ADVANCE"
            and placement["progression_step"] >= calc.MAX_PROGRESSION_STEPS):
        fail("ERR_MAX_PROGRESSION_STEPS",
             "The placement already reached the progression-step ceiling.")
    # priority 33
    if (decision == "DEFER"
            and row["deferral_count"] >= calc.MAX_REVIEW_DEFERRALS):
        fail("ERR_MAX_DEFERRALS_REACHED",
             "The review already reached the deferral ceiling.")
    # priority 43
    if decision in ("ADVANCE", "EXTEND") and _panel_in_progress(placement["id"]):
        fail("ERR_CASE_REVIEW_IN_PROGRESS",
             "A case review of this placement is OPEN or VOTING.")
    if outcome_note is not None:
        row["outcome_note"] = outcome_note
    clock_date = db.today()
    if decision == "ADVANCE":
        claim = db.claims[placement["claim_id"]]
        employee = _employee_of_claim(claim)
        job = db.jobs[placement["transitional_job_id"]]
        rs = _governing_rs(placement)
        target_hours, target_lift = calc.progression_step_target(
            placement, rs, job, employee)
        row["target_hours_per_day"] = target_hours
        row["target_lift_lbs"] = target_lift
        row["review_status"] = "ADVANCED"
        touch(row)
        placement["scheduled_hours_per_day"] = target_hours
        placement["progression_step"] += 1
        pinned_rs = db.restriction_sets[placement["restriction_set_id"]]
        placement["match_score"] = calc.restriction_match_score(pinned_rs, job)
        touch(placement)
        domain.new_progression_review(
            placement["id"], row["step_index"] + 1,
            clock_date + timedelta(days=calc.PROGRESSION_REVIEW_INTERVAL_DAYS))
    elif decision == "EXTEND":
        row["review_status"] = "EXTENDED"
        touch(row)
        domain.new_progression_review(
            placement["id"], row["step_index"] + 1,
            clock_date + timedelta(days=calc.PROGRESSION_REVIEW_INTERVAL_DAYS))
    elif decision == "ESCALATE":
        row["review_status"] = "ESCALATED"
        touch(row)
        if placement["placement_status"] == "ACTIVE":
            placement["placement_status"] = "PROGRESSION_HOLD"
            touch(placement)
        domain.new_case_review(placement["id"], "DURATION_CAP", g.user_id, 3)
    else:  # DEFER
        row["review_status"] = "SCHEDULED"
        row["deferral_count"] += 1
        row["due_date"] = (parse_date(row["due_date"])
                           + timedelta(days=calc.REVIEW_DEFERRAL_DAYS)).isoformat()
        row["reviewed_by_user_id"] = None
        touch(row)
    return ok(serialize.progression_review(row))


# ----------------------------------------------------- compliance monitoring
@bp.post("/rtw/placements/<placement_id>/compliance-audits")
@require_roles("Supervisor", "RTWCoordinator", "ProgramAdmin", "OccHealthNurse")
def create_compliance_audit(placement_id):
    body = body_of()
    observed_on = date_field(body, "observed_on")
    finding_severity = enum_field(body, "finding_severity", FINDING_SEVERITIES)
    finding_code = enum_field(body, "finding_code", FINDING_CODES)
    deviation = bool_field(body, "restriction_deviation_detected",
                           required=False, default=False)
    corrective = str_field(body, "corrective_action_note", required=False,
                           allow_empty=True)
    row = _placement_or_404(placement_id)
    own_placement(row)
    audit = stamp_new({
        "placement_id": placement_id,
        "auditor_user_id": g.user_id,
        "observed_on": observed_on.isoformat(),
        "finding_severity": finding_severity,
        "finding_code": finding_code,
        "restriction_deviation_detected": deviation,
        "corrective_action_note": corrective,
    }, versioned=False)
    db.audits[audit["id"]] = audit
    domain.apply_compliance_finding(row, finding_severity)
    return created(serialize.compliance_audit(audit))


@bp.get("/rtw/placements/<placement_id>/compliance-audits")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "Supervisor")
def list_compliance_audits(placement_id):
    limit, offset = pagination()
    finding_severity = query_enum("finding_severity", FINDING_SEVERITIES)
    row = _placement_or_404(placement_id)
    own_placement(row)
    rows = [a for a in db.audits.values() if a["placement_id"] == placement_id]
    if finding_severity:
        rows = [a for a in rows if a["finding_severity"] == finding_severity]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.compliance_audit(r) for r in page], limit, offset,
                   total)
