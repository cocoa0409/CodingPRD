"""Reinjury reporting, the case-review panel, the wage ledger, program metrics
and the logical clock."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import domain
import serialize
from api_core import _claim_or_404
from api_placement import _placement_or_404
from auth import require_roles, own_placement
from errors import fail
from response import ok, created, ok_list, paginate
from store import db, stamp_new, touch, ordered
from util import (parse_date, parse_instant, fmt_ts, days_between, D, rhu_f,
                  dec_floor)
from validators import (body_of, str_field, enum_field, int_field, num_field,
                        date_field, not_inverted, pagination, query_enum,
                        query_str, query_date, bad)

bp = Blueprint("review", __name__)

REINJURY_SEVERITIES = ("NEAR_MISS", "MINOR", "SIGNIFICANT", "SEVERE")
REPORT_STATUSES = ("SUBMITTED", "TRIAGED", "ESCALATED")
TRIGGER_REASONS = ("REINJURY", "RESTRICTION_CONFLICT", "DURATION_CAP",
                   "COMPLIANCE_CRITICAL", "ADJUSTER_DENIAL")
CASE_REVIEW_STATUSES = ("OPEN", "VOTING", "DECIDED_CONTINUE", "DECIDED_MODIFY",
                        "DECIDED_TERMINATE")
BALLOTS = ("CONTINUE", "MODIFY", "TERMINATE")
VOTE_STATUSES = ("COUNTED", "SUPERSEDED")
WAGE_VARIANTS = ("PROVISIONAL", "FINAL")
ENTRY_STATUSES = ("POSTED", "REVERSED", "REVERSAL")


def _report_or_404(report_id):
    row = db.reinjury_reports.get(report_id)
    if row is None:
        fail("ERR_REINJURY_REPORT_NOT_FOUND",
             "No ReinjuryReport row matches that id.")
    return row


def _case_review_or_404(case_review_id):
    row = db.case_reviews.get(case_review_id)
    if row is None:
        fail("ERR_CASE_REVIEW_NOT_FOUND", "No CaseReview row matches that id.")
    return row


def _wage_entry_or_404(entry_id):
    row = db.wage_entries.get(entry_id)
    if row is None:
        fail("ERR_WAGE_ENTRY_NOT_FOUND",
             "No WageDifferentialEntry row matches that id.")
    return row


# ======================================================== reinjury reports
@bp.post("/rtw/placements/<placement_id>/reinjury-reports")
@require_roles("Supervisor", "OccHealthNurse", "RTWCoordinator", "Employee")
def create_reinjury_report(placement_id):
    body = body_of()
    occurred_on = date_field(body, "occurred_on")
    severity = enum_field(body, "severity", REINJURY_SEVERITIES)
    body_part_code = str_field(body, "body_part_code")
    mechanism_code = str_field(body, "mechanism_code")
    placement = _placement_or_404(placement_id)
    own_placement(placement)
    row = stamp_new({
        "placement_id": placement_id,
        "reported_by_user_id": g.user_id,
        "occurred_on": occurred_on.isoformat(),
        "severity": severity,
        "body_part_code": body_part_code,
        "mechanism_code": mechanism_code,
        "report_status": "SUBMITTED",
        "triage_note": None,
        "risk_points_applied": 0,
    })
    db.reinjury_reports[row["id"]] = row
    return created(serialize.reinjury_report(row))


@bp.get("/rtw/placements/<placement_id>/reinjury-reports")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "Supervisor",
               "Employee")
def list_reinjury_reports(placement_id):
    limit, offset = pagination()
    report_status = query_enum("report_status", REPORT_STATUSES)
    placement = _placement_or_404(placement_id)
    own_placement(placement)
    rows = [r for r in db.reinjury_reports.values()
            if r["placement_id"] == placement_id]
    if report_status:
        rows = [r for r in rows if r["report_status"] == report_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.reinjury_report(r) for r in page], limit, offset,
                   total)


@bp.post("/rtw/reinjury-reports/<report_id>/triage")
@require_roles("OccHealthNurse")
def triage_reinjury_report(report_id):
    body = body_of()
    triage_note = str_field(body, "triage_note")
    row = _report_or_404(report_id)
    if row["report_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "The report has already been triaged.")
    placement = db.placements[row["placement_id"]]
    row["triage_note"] = triage_note
    row["report_status"] = "TRIAGED"
    row["risk_points_applied"] = calc.REINJURY_SEVERITY_POINTS[row["severity"]]
    domain.recompute_surveillance_risk(placement)
    if placement["reinjury_risk_score"] >= calc.RISK_ESCALATION_THRESHOLD:
        row["report_status"] = "ESCALATED"
        touch(row)
        if placement["placement_status"] == "ACTIVE":
            domain.move_placement_to_hold(placement, "REINJURY", "system")
        else:
            touch(placement)
    else:
        touch(row)
        touch(placement)
    return ok(serialize.reinjury_report(row))


# ========================================================== case reviews
@bp.post("/rtw/placements/<placement_id>/case-reviews")
@require_roles("OccHealthNurse", "RTWCoordinator", "ProgramAdmin")
def create_case_review(placement_id):
    body = body_of()
    trigger_reason = enum_field(body, "trigger_reason", TRIGGER_REASONS)
    quorum_required = int_field(body, "quorum_required", required=False,
                                minimum=1, maximum=7, default=3)
    _placement_or_404(placement_id)
    row = domain.new_case_review(placement_id, trigger_reason, g.user_id,
                                 quorum_required)
    return created(serialize.case_review(row))


@bp.get("/rtw/placements/<placement_id>/case-reviews")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "Supervisor")
def list_case_reviews(placement_id):
    limit, offset = pagination()
    review_status = query_enum("review_status", CASE_REVIEW_STATUSES)
    placement = _placement_or_404(placement_id)
    own_placement(placement)
    rows = [c for c in db.case_reviews.values()
            if c["placement_id"] == placement_id]
    if review_status:
        rows = [c for c in rows if c["review_status"] == review_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.case_review(r) for r in page], limit, offset,
                   total)


@bp.get("/rtw/case-reviews/<case_review_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "Supervisor", "TreatingProvider")
def read_case_review(case_review_id):
    return ok(serialize.case_review(_case_review_or_404(case_review_id)))


@bp.post("/rtw/case-reviews/<case_review_id>/open-voting")
@require_roles("OccHealthNurse", "ProgramAdmin")
def open_voting(case_review_id):
    row = _case_review_or_404(case_review_id)
    domain.check_terminal("case_review", row["review_status"])
    domain.check_from_state(row["review_status"], ("OPEN",))
    row["review_status"] = "VOTING"
    touch(row)
    return ok(serialize.case_review(row))


@bp.post("/rtw/case-reviews/<case_review_id>/votes")
@require_roles("RTWCoordinator", "OccHealthNurse", "ClaimAdjuster",
               "Supervisor", "TreatingProvider")
def cast_vote(case_review_id):
    body = body_of()
    ballot = enum_field(body, "ballot", BALLOTS)
    expected_version = int_field(body, "expected_case_review_version")
    rationale = str_field(body, "rationale", required=False, allow_empty=True)
    row = _case_review_or_404(case_review_id)
    placement = db.placements[row["placement_id"]]
    # priority 7
    if g.user_id == placement["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The placement's creator may not vote on its case review.")
    # priority 8
    domain.check_terminal("case_review", row["review_status"])
    # priority 13
    if row["review_status"] != "VOTING":
        fail("ERR_CASE_REVIEW_NOT_VOTING",
             "The addressed CaseReview is not in review_status VOTING.")
    # priority 41
    if expected_version != row["version"]:
        fail("ERR_STALE_CASE_REVIEW_VERSION",
             "expected_case_review_version does not match.")
    for prior in calc.votes_of_case_review(case_review_id):
        if (prior["vote_status"] == "COUNTED"
                and prior["voter_user_id"] == g.user_id):
            prior["vote_status"] = "SUPERSEDED"
    vote = stamp_new({
        "case_review_id": case_review_id,
        "voter_user_id": g.user_id,
        "voter_role": g.role,
        "ballot": ballot,
        "rationale": rationale,
        "vote_status": "COUNTED",
    }, versioned=False)
    db.votes[vote["id"]] = vote
    touch(row)
    return created(serialize.case_review_vote(vote))


@bp.get("/rtw/case-reviews/<case_review_id>/votes")
@require_roles("ProgramAdmin", "RTWCoordinator", "OccHealthNurse",
               "ClaimAdjuster", "Supervisor", "TreatingProvider")
def list_votes(case_review_id):
    limit, offset = pagination()
    vote_status = query_enum("vote_status", VOTE_STATUSES)
    _case_review_or_404(case_review_id)
    rows = [v for v in db.votes.values()
            if v["case_review_id"] == case_review_id]
    if vote_status:
        rows = [v for v in rows if v["vote_status"] == vote_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.case_review_vote(r) for r in page], limit, offset,
                   total)


@bp.post("/rtw/case-reviews/<case_review_id>/close")
@require_roles("OccHealthNurse", "ProgramAdmin")
def close_case_review(case_review_id):
    row = _case_review_or_404(case_review_id)
    # priority 7
    for vote in calc.votes_of_case_review(case_review_id):
        if vote["vote_status"] == "COUNTED" and vote["voter_user_id"] == g.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "A member who cast a counted ballot may not close the panel.")
    # priority 8
    domain.check_terminal("case_review", row["review_status"])
    # priority 13
    if row["review_status"] != "VOTING":
        fail("ERR_CASE_REVIEW_NOT_VOTING",
             "The addressed CaseReview is not in review_status VOTING.")
    tally = calc.case_review_tally(row)
    # priority 34
    if tally["vote_count"] < row["quorum_required"]:
        fail("ERR_QUORUM_NOT_MET",
             "The panel's counted vote_count is below quorum_required.")
    # priority 35
    if D(tally["decision_ratio"]) < calc.CASE_REVIEW_MAJORITY:
        fail("ERR_MAJORITY_NOT_REACHED",
             "The panel's decision_ratio is below the majority bar.")
    winning = tally["winning_ballot"]
    placement = db.placements[row["placement_id"]]
    row["closed_by_user_id"] = g.user_id
    if winning == "CONTINUE":
        row["review_status"] = "DECIDED_CONTINUE"
        touch(row)
        if placement["placement_status"] == "PROGRESSION_HOLD":
            placement["placement_status"] = "ACTIVE"
            touch(placement)
    elif winning == "MODIFY":
        row["review_status"] = "DECIDED_MODIFY"
        touch(row)
        current = D(placement["scheduled_hours_per_day"])
        halved = dec_floor(current * calc.CASE_REVIEW_MODIFY_HOURS_FACTOR)
        placement["scheduled_hours_per_day"] = max(1, halved)
        job = db.jobs[placement["transitional_job_id"]]
        pinned_rs = db.restriction_sets[placement["restriction_set_id"]]
        placement["match_score"] = calc.restriction_match_score(pinned_rs, job)
        domain.recompute_surveillance_risk(placement)
        touch(placement)
        greatest = 0
        for review in calc.reviews_of_placement(placement["id"]):
            if review["step_index"] > greatest:
                greatest = review["step_index"]
        domain.new_progression_review(
            placement["id"], greatest + 1,
            db.today() + timedelta(days=calc.CASE_REVIEW_MODIFY_FOLLOWUP_DAYS))
    else:
        row["review_status"] = "DECIDED_TERMINATE"
        touch(row)
        domain.end_placement(placement, "TERMINATED_EARLY")
    return ok(serialize.case_review(row))


# ==================================================== wage differential ledger
@bp.post("/rtw/placements/<placement_id>/wage-differential-entries")
@require_roles("ProgramAdmin", "RTWCoordinator")
def create_wage_entry(placement_id):
    body = body_of()
    variant = enum_field(body, "variant", WAGE_VARIANTS)
    period_start = date_field(body, "period_start")
    period_end = date_field(body, "period_end")
    not_inverted(period_start, period_end, "period_start", "period_end")
    placement = _placement_or_404(placement_id)
    # priority 28
    for other in calc.wage_entries_of_placement(placement_id):
        if other["variant"] != variant:
            continue
        other_start = parse_date(other["period_start"])
        other_end = parse_date(other["period_end"])
        if period_start <= other_end and other_start <= period_end:
            fail("ERR_WAGE_PERIOD_OVERLAP",
                 "Another entry of the same variant already covers a day "
                 "in this period.")
    claim = db.claims[placement["claim_id"]]
    employee = db.employees[claim["employee_id"]]
    job = db.jobs[placement["transitional_job_id"]]
    amounts = calc.wage_period_amount(placement, job, employee, variant,
                                      period_start, period_end)
    row = stamp_new({
        "placement_id": placement_id,
        "claim_id": placement["claim_id"],
        "reverses_entry_id": None,
        "variant": variant,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "entry_status": "POSTED",
    }, versioned=False)
    row.update(amounts)
    db.wage_entries[row["id"]] = row
    touch(claim)
    return created(serialize.wage_entry(row))


@bp.get("/rtw/wage-differential-entries")
@require_roles("ProgramAdmin", "RTWCoordinator", "ClaimAdjuster")
def list_wage_entries():
    limit, offset = pagination()
    placement_id = query_str("placement_id")
    claim_id = query_str("claim_id")
    reverses_entry_id = query_str("reverses_entry_id")
    variant = query_enum("variant", WAGE_VARIANTS)
    entry_status = query_enum("entry_status", ENTRY_STATUSES)
    if reverses_entry_id is not None:
        _wage_entry_or_404(reverses_entry_id)
    rows = list(db.wage_entries.values())
    if placement_id is not None:
        rows = [w for w in rows if w["placement_id"] == placement_id]
    if claim_id is not None:
        rows = [w for w in rows if w["claim_id"] == claim_id]
    if reverses_entry_id is not None:
        rows = [w for w in rows if w["reverses_entry_id"] == reverses_entry_id]
    if variant:
        rows = [w for w in rows if w["variant"] == variant]
    if entry_status:
        rows = [w for w in rows if w["entry_status"] == entry_status]
    rows = ordered(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize.wage_entry(r) for r in page], limit, offset, total)


@bp.get("/rtw/wage-differential-entries/<entry_id>")
@require_roles("ProgramAdmin", "RTWCoordinator", "ClaimAdjuster")
def read_wage_entry(entry_id):
    return ok(serialize.wage_entry(_wage_entry_or_404(entry_id)))


@bp.post("/rtw/wage-differential-entries/<entry_id>/reverse")
@require_roles("ProgramAdmin")
def reverse_wage_entry(entry_id):
    body = body_of()
    str_field(body, "reason")
    row = _wage_entry_or_404(entry_id)
    # priority 14
    if row["entry_status"] != "POSTED":
        fail("ERR_WAGE_ENTRY_ALREADY_REVERSED",
             "The addressed WageDifferentialEntry is not POSTED.")
    row["entry_status"] = "REVERSED"
    reversal = stamp_new({
        "placement_id": row["placement_id"],
        "claim_id": row["claim_id"],
        "reverses_entry_id": row["id"],
        "variant": row["variant"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "counted_day_count": row["counted_day_count"],
        "tier_multiplier": row["tier_multiplier"],
        "gross_differential_cents": row["gross_differential_cents"],
        "offset_cents": row["offset_cents"],
        "net_amount_cents": -row["net_amount_cents"],
        "entry_status": "REVERSAL",
    }, versioned=False)
    db.wage_entries[reversal["id"]] = reversal
    claim = db.claims.get(row["claim_id"])
    if claim is not None:
        touch(claim)
    return created(serialize.wage_entry(reversal))


# ============================================================ program metrics
@bp.get("/rtw/programs/metrics")
@require_roles("ProgramAdmin", "RTWCoordinator", "ClaimAdjuster")
def program_metrics():
    window_start = query_date("window_start",
                              parse_date(calc.DEFAULT_WINDOW_START))
    window_end = query_date("window_end", parse_date(calc.DEFAULT_WINDOW_END))
    department_code = query_str("department_code")
    cohort = []
    for placement in ordered(list(db.placements.values())):
        if placement["placement_status"] not in calc.DURATION_STATUSES:
            continue
        if not placement["activated_on"]:
            continue
        activated = parse_date(placement["activated_on"])
        if activated < window_start or activated > window_end:
            continue
        if department_code is not None:
            job = db.jobs.get(placement["transitional_job_id"])
            if job is None or job["department_code"] != department_code:
                continue
        cohort.append(placement)
    total_placements = len(cohort)
    active_placements = sum(1 for p in cohort
                            if p["placement_status"] in ("ACTIVE",
                                                         "PROGRESSION_HOLD"))
    completed_count = sum(1 for p in cohort
                          if p["placement_status"] == "COMPLETED")
    reinjury_count = 0
    for p in cohort:
        if any(r["report_status"] in ("TRIAGED", "ESCALATED")
               for r in calc.reinjury_reports_of_placement(p["id"])):
            reinjury_count += 1
    compliant_count = sum(1 for p in cohort
                          if p["compliance_status"] in ("COMPLIANT",
                                                        "REMEDIATED"))
    if total_placements == 0:
        successful_return_rate = 0.0
        average_duration_days = 0.0
        reinjury_rate = 0.0
        compliance_rate = 0.0
    else:
        successful_return_rate = rhu_f(
            D(completed_count) / D(total_placements), 4)
        duration_sum = sum(calc.cumulative_days(p) for p in cohort)
        average_duration_days = rhu_f(D(duration_sum) / D(total_placements), 2)
        reinjury_rate = rhu_f(D(reinjury_count) / D(total_placements), 4)
        compliance_rate = rhu_f(D(compliant_count) / D(total_placements), 4)
    cohort_ids = {p["id"] for p in cohort}
    total_wage = sum(w["net_amount_cents"] for w in db.wage_entries.values()
                     if w["placement_id"] in cohort_ids)
    return ok({
        "total_placements": total_placements,
        "active_placements": active_placements,
        "completed_count": completed_count,
        "successful_return_rate": successful_return_rate,
        "average_duration_days": average_duration_days,
        "reinjury_count": reinjury_count,
        "reinjury_rate": reinjury_rate,
        "compliance_rate": compliance_rate,
        "total_wage_differential_cents": total_wage,
    })


# ============================================================= logical clock
@bp.post("/_clock/set_current_utc")
@require_roles("ProgramAdmin")
def set_clock():
    body = body_of()
    raw = body.get("to_iso8601")
    if raw is None:
        bad("Field 'to_iso8601' is required.")
    instant = parse_instant(raw)
    if instant is None:
        bad("Field 'to_iso8601' must be an ISO 8601 instant.")
    db.clock = instant
    clock_date = db.today()
    expired_restriction_set_ids = []
    for rs in ordered(list(db.restriction_sets.values())):
        if rs["status"] == "ACTIVE" and parse_date(rs["valid_through"]) < clock_date:
            rs["status"] = "EXPIRED"
            touch(rs)
            expired_restriction_set_ids.append(rs["id"])
    expired_training_record_ids = []
    warned_training_record_ids = []
    for record in ordered(list(db.training_records.values())):
        status = record["record_status"]
        if status not in ("VALID", "EXPIRING_SOON"):
            continue
        valid_through = parse_date(record["valid_through"])
        if valid_through < clock_date:
            record["record_status"] = "EXPIRED"
            touch(record)
            expired_training_record_ids.append(record["id"])
        elif status == "VALID" and 0 <= days_between(
                clock_date, valid_through) <= calc.TRAINING_EXPIRY_WARNING_DAYS:
            record["record_status"] = "EXPIRING_SOON"
            touch(record)
            warned_training_record_ids.append(record["id"])
    return ok({
        "current_utc": fmt_ts(db.clock),
        "expired_restriction_set_ids": expired_restriction_set_ids,
        "expired_training_record_ids": expired_training_record_ids,
        "warned_training_record_ids": warned_training_record_ids,
    })
