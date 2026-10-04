# computed.py — derived fields (recomputed live on every read) and the
# serializers that shape each resource's JSON representation.
from datetime import datetime, timedelta, timezone

import db
from constants import (
    CASE_COMPLETED, CASE_PENDING_STATUSES, CUSTODY_DETAINED,
    TARGET_DAYS_DETAINED, TARGET_DAYS_NON_DETAINED,
    DETAINED_PRIORITY_BASE, AGE_POINTS_PER_DAY, AGE_CAP_DAYS,
    CONTINUANCE_DRAG_POINTS, CONTINUANCE_DRAG_CAP,
    BACKLOG_CRITICAL_RATIO_NUM, BACKLOG_CRITICAL_RATIO_DEN,
    REQ_GRANTED, REP_PRO_SE,
)
from timeutil import fmt, count_weekday_dates

INTERNAL_KEYS = ("_seq",)


def _clean(record, out):
    return out


# ---------------------------------------------------------------------------
# Court computed fields (PRD §2.9)
# ---------------------------------------------------------------------------

def court_pending_count(court_id):
    return sum(1 for c in db.cases.values()
               if c["court_id"] == court_id and c["status"] in CASE_PENDING_STATUSES)


def court_completions_ytd(court_id):
    clock = db.get_clock()
    jan1 = datetime(clock.year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return sum(1 for c in db.cases.values()
               if c["court_id"] == court_id and c["status"] == CASE_COMPLETED
               and c.get("completed_at") is not None
               and jan1 <= c["completed_at"] <= clock)


def court_backlog_critical(court):
    # is_backlog_critical = pending >= ceil(0.25 * annual_goal); boundary inclusive
    goal = court["annual_completion_goal"]
    threshold = -(-goal * BACKLOG_CRITICAL_RATIO_NUM // BACKLOG_CRITICAL_RATIO_DEN)
    return court_pending_count(court["id"]) >= threshold


def serialize_court(court):
    return {
        "id": court["id"],
        "court_code": court["court_code"],
        "name": court["name"],
        "city": court["city"],
        "annual_completion_goal": court["annual_completion_goal"],
        "detained_daily_hearing_capacity": court["detained_daily_hearing_capacity"],
        "pending_case_count": court_pending_count(court["id"]),
        "completions_ytd": court_completions_ytd(court["id"]),
        "is_backlog_critical": court_backlog_critical(court),
        "created_at": fmt(court["created_at"]),
        "updated_at": fmt(court["updated_at"]),
        "version": court["version"],
    }


# ---------------------------------------------------------------------------
# Judge / Interpreter / LegalOrientationProgram
# ---------------------------------------------------------------------------

def judge_pending_load(judge_id):
    return sum(1 for c in db.cases.values()
               if c.get("assigned_judge_id") == judge_id
               and c["status"] != CASE_COMPLETED)


def serialize_judge(judge):
    return {
        "id": judge["id"],
        "court_id": judge["court_id"],
        "full_name": judge["full_name"],
        "max_pending_cases": judge["max_pending_cases"],
        "pending_case_load": judge_pending_load(judge["id"]),
        "created_at": fmt(judge["created_at"]),
        "updated_at": fmt(judge["updated_at"]),
        "version": judge["version"],
    }


def serialize_interpreter(it):
    return {
        "id": it["id"],
        "court_id": it["court_id"],
        "full_name": it["full_name"],
        "language_codes": list(it["language_codes"]),
        "daily_hearing_cap": it["daily_hearing_cap"],
        "created_at": fmt(it["created_at"]),
        "updated_at": fmt(it["updated_at"]),
        "version": it["version"],
    }


def serialize_program(p):
    return {
        "id": p["id"],
        "court_id": p["court_id"],
        "program_name": p["program_name"],
        "coverage_pct": p["coverage_pct"],
        "active": p["active"],
        "created_at": fmt(p["created_at"]),
        "updated_at": fmt(p["updated_at"]),
        "version": p["version"],
    }


# ---------------------------------------------------------------------------
# Case computed fields (SCAFFOLD §1.3 days_pending / case_priority_score)
# ---------------------------------------------------------------------------

def target_days(case):
    return TARGET_DAYS_DETAINED if case["custody_status"] == CUSTODY_DETAINED \
        else TARGET_DAYS_NON_DETAINED


def days_pending_calendar(case):
    # floor((clock - filed_at) / 86400s); timedelta.days already floors
    return (db.get_clock() - case["filed_at"]).days


def days_pending_court(case):
    # count of Mon-Fri dates D with date(filed_at) < D <= date(clock)
    return count_weekday_dates(case["filed_at"].date(), db.get_clock().date())


def is_past_goal(case):
    # strict greater-than: exactly on target is NOT past goal
    return days_pending_calendar(case) > target_days(case)


def case_continuance_count(case_id):
    return sum(1 for r in db.continuances.values()
               if r["case_id"] == case_id and r["status"] == REQ_GRANTED)


def priority_score(case):
    base = DETAINED_PRIORITY_BASE if case["custody_status"] == CUSTODY_DETAINED else 0
    age = AGE_POINTS_PER_DAY * min(days_pending_calendar(case), AGE_CAP_DAYS)
    drag = CONTINUANCE_DRAG_POINTS * min(case_continuance_count(case["id"]),
                                         CONTINUANCE_DRAG_CAP)
    return max(0, base + age - drag)


def serialize_case(case):
    return {
        "id": case["id"],
        "court_id": case["court_id"],
        "case_number": case["case_number"],
        "respondent_full_name": case["respondent_full_name"],
        "custody_status": case["custody_status"],
        "primary_language_code": case["primary_language_code"],
        "representation_status": case["representation_status"],
        "interpreter_required": case["interpreter_required"],
        "assigned_judge_id": case["assigned_judge_id"],
        "status": case["status"],
        "filed_at": fmt(case["filed_at"]),
        "completed_at": fmt(case["completed_at"]),
        "target_completion_date": fmt(case["filed_at"] + timedelta(days=target_days(case))),
        "days_pending_calendar": days_pending_calendar(case),
        "days_pending_court": days_pending_court(case),
        "is_past_goal": is_past_goal(case),
        "continuance_count": case_continuance_count(case["id"]),
        "priority_score": priority_score(case),
        "created_at": fmt(case["created_at"]),
        "updated_at": fmt(case["updated_at"]),
        "version": case["version"],
    }


# ---------------------------------------------------------------------------
# Hearing / HearingNotice / ContinuanceRequest / ChangeOfVenueMotion
# ---------------------------------------------------------------------------

def serialize_hearing(h):
    return {
        "id": h["id"],
        "case_id": h["case_id"],
        "hearing_type": h["hearing_type"],
        "scheduled_start": fmt(h["scheduled_start"]),
        "duration_minutes": h["duration_minutes"],
        "scheduled_end": fmt(h["scheduled_end"]),
        "is_remote": h["is_remote"],
        "judge_id": h["judge_id"],
        "interpreter_id": h["interpreter_id"],
        "supersedes_hearing_id": h["supersedes_hearing_id"],
        "auto_created": h["auto_created"],
        "status": h["status"],
        "created_at": fmt(h["created_at"]),
        "updated_at": fmt(h["updated_at"]),
        "version": h["version"],
    }


def serialize_notice(n):
    return {
        "id": n["id"],
        "hearing_id": n["hearing_id"],
        "service_method": n["service_method"],
        "served_at": fmt(n["served_at"]),
        "status": n["status"],
        "created_at": fmt(n["created_at"]),
        "updated_at": fmt(n["updated_at"]),
        "version": n["version"],
    }


def serialize_continuance(r):
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "hearing_id": r["hearing_id"],
        "reason_code": r["reason_code"],
        "is_first_for_case": r["is_first_for_case"],
        "status": r["status"],
        "decided_by_judge_id": r["decided_by_judge_id"],
        "decided_at": fmt(r["decided_at"]),
        "created_at": fmt(r["created_at"]),
        "updated_at": fmt(r["updated_at"]),
        "version": r["version"],
    }


def serialize_venue_motion(m):
    return {
        "id": m["id"],
        "case_id": m["case_id"],
        "destination_court_id": m["destination_court_id"],
        "reason": m["reason"],
        "status": m["status"],
        "decided_by_judge_id": m["decided_by_judge_id"],
        "decided_at": fmt(m["decided_at"]),
        "created_at": fmt(m["created_at"]),
        "updated_at": fmt(m["updated_at"]),
        "version": m["version"],
    }


# ---------------------------------------------------------------------------
# CaseReassignment / Decision / Appeal / MotionToReopen / DocketReview
# ---------------------------------------------------------------------------

def serialize_reassignment(r):
    # Immutable ledger record: id + created_at only (PRD §2.5)
    return {
        "id": r["id"],
        "case_id": r["case_id"],
        "from_court_id": r["from_court_id"],
        "to_court_id": r["to_court_id"],
        "reason": r["reason"],
        "executed_at": fmt(r["executed_at"]),
        "created_at": fmt(r["created_at"]),
    }


def serialize_decision(d):
    return {
        "id": d["id"],
        "case_id": d["case_id"],
        "judge_id": d["judge_id"],
        "outcome": d["outcome"],
        "source_hearing_id": d["source_hearing_id"],
        "issued_at": fmt(d["issued_at"]),
        "appeal_deadline": fmt(d["appeal_deadline"]),
        "reopen_deadline": fmt(d["reopen_deadline"]),
        "status": d["status"],
        "created_at": fmt(d["created_at"]),
        "updated_at": fmt(d["updated_at"]),
        "version": d["version"],
    }


def serialize_appeal(a):
    return {
        "id": a["id"],
        "decision_id": a["decision_id"],
        "case_id": a["case_id"],
        "grounds": a["grounds"],
        "filed_at": fmt(a["filed_at"]),
        "status": a["status"],
        "remand_instructions": a["remand_instructions"],
        "decided_by_board_member_id": a["decided_by_board_member_id"],
        "decided_at": fmt(a["decided_at"]),
        "created_at": fmt(a["created_at"]),
        "updated_at": fmt(a["updated_at"]),
        "version": a["version"],
    }


def serialize_motion(m):
    return {
        "id": m["id"],
        "case_id": m["case_id"],
        "decision_id": m["decision_id"],
        "basis": m["basis"],
        "filed_at": fmt(m["filed_at"]),
        "status": m["status"],
        "decided_by_judge_id": m["decided_by_judge_id"],
        "decided_at": fmt(m["decided_at"]),
        "created_at": fmt(m["created_at"]),
        "updated_at": fmt(m["updated_at"]),
        "version": m["version"],
    }


def serialize_docket_review(r):
    # Immutable snapshot: id + created_at only (PRD §2.5)
    return {
        "id": r["id"],
        "court_id": r["court_id"],
        "run_index": r["run_index"],
        "computed_at": fmt(r["computed_at"]),
        "pending_case_count": r["pending_case_count"],
        "completions_ytd": r["completions_ytd"],
        "representation_rate_pct": r["representation_rate_pct"],
        "pace_ratio_calendar": r["pace_ratio_calendar"],
        "pace_ratio_hearing_day": r["pace_ratio_hearing_day"],
        "is_backlog_critical": r["is_backlog_critical"],
        "is_on_pace": r["is_on_pace"],
        "cases_finalized_by_lapse": r["cases_finalized_by_lapse"],
        "created_at": fmt(r["created_at"]),
    }
