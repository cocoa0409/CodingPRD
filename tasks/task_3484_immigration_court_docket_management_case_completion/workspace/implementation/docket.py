# docket.py — docket-review pace metrics (calculations.court_completion_pace)
# and the lapse sweep (PRD §3.8).
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from computed import (court_pending_count, court_completions_ytd,
                      court_backlog_critical)
from constants import (
    CASE_PENDING_STATUSES, CASE_DECIDED, CASE_IN_ABSENTIA, CASE_COMPLETED,
    DEC_ISSUED, DEC_FINAL, OUTCOME_IN_ABSENTIA, REP_PRO_SE,
    DAYS_PER_YEAR, HEARING_DAYS_PER_YEAR, MOTION_FILED,
)
from timeutil import count_weekday_dates

Q4 = Decimal("0.0001")
Q1 = Decimal("0.1")


def year_start(clock):
    return datetime(clock.year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def representation_rate_pct(court_id):
    """Share of the court's pending cases not PRO_SE; 1dp round-half-up;
    0.0 when the court has no pending cases."""
    pending = [c for c in db.cases.values()
               if c["court_id"] == court_id and c["status"] in CASE_PENDING_STATUSES]
    if not pending:
        return 0.0
    represented = sum(1 for c in pending
                      if c["representation_status"] != REP_PRO_SE)
    rate = (Decimal(represented * 100) / Decimal(len(pending))).quantize(
        Q1, rounding=ROUND_HALF_UP)
    return float(rate)


def pace_ratios(court, completions, clock):
    """CALENDAR_PRORATA (official, drives is_on_pace) and HEARING_DAY_PRORATA
    (reporting); both 4 decimal places round-half-up."""
    jan1 = year_start(clock)
    elapsed_days = max(1, (clock - jan1).days)
    elapsed_hearing_days = max(1, count_weekday_dates(jan1.date(), clock.date()))
    goal = court["annual_completion_goal"]
    denom_cal = Decimal(goal * elapsed_days) / Decimal(DAYS_PER_YEAR)
    denom_hd = Decimal(goal * elapsed_hearing_days) / Decimal(HEARING_DAYS_PER_YEAR)
    pace_cal = (Decimal(completions) / denom_cal).quantize(Q4, rounding=ROUND_HALF_UP)
    pace_hd = (Decimal(completions) / denom_hd).quantize(Q4, rounding=ROUND_HALF_UP)
    return float(pace_cal), float(pace_hd), pace_cal


def _latest_decision(case_id):
    decs = [d for d in db.decisions.values() if d["case_id"] == case_id]
    if not decs:
        return None
    return max(decs, key=lambda d: d["_seq"])


def _latest_in_absentia_decision(case_id):
    decs = [d for d in db.decisions.values()
            if d["case_id"] == case_id and d["outcome"] == OUTCOME_IN_ABSENTIA]
    if not decs:
        return None
    return max(decs, key=lambda d: d["_seq"])


def _finalize(case, decision, clock):
    decision["status"] = DEC_FINAL
    db.touch(decision)
    case["status"] = CASE_COMPLETED
    case["completed_at"] = clock
    db.touch(case)


def process_lapse(court_id):
    """Lapse sweep (PRD §3.8): DECIDED cases whose latest decision is ISSUED
    with clock strictly past appeal_deadline, and IN_ABSENTIA cases whose
    in-absentia decision is ISSUED with clock strictly past reopen_deadline
    and no FILED motion standing, are finalized (decision FINAL, case
    COMPLETED). Windows are inclusive while open: a deadline exactly at the
    clock is NOT yet lapsed. Returns the number of cases finalized."""
    clock = db.get_clock()
    finalized = 0
    for case in sorted(db.cases.values(), key=lambda c: c["_seq"]):
        if case["court_id"] != court_id:
            continue
        if case["status"] == CASE_DECIDED:
            dec = _latest_decision(case["id"])
            if dec is not None and dec["status"] == DEC_ISSUED \
                    and clock > dec["appeal_deadline"]:
                _finalize(case, dec, clock)
                finalized += 1
        elif case["status"] == CASE_IN_ABSENTIA:
            dec = _latest_in_absentia_decision(case["id"])
            if dec is None or dec["status"] != DEC_ISSUED:
                continue
            if dec["reopen_deadline"] is None or clock <= dec["reopen_deadline"]:
                continue
            open_motion = any(
                m for m in db.motions.values()
                if m["case_id"] == case["id"] and m["status"] == MOTION_FILED)
            if open_motion:
                continue
            _finalize(case, dec, clock)
            finalized += 1
    return finalized


def run_docket_review(court):
    """Freeze the court's live metrics onto an immutable DocketReview snapshot
    exactly as they stand at run time, then process lapses in the same run and
    record how many cases this run finalized (PRD §3.8)."""
    clock = db.get_clock()
    court_id = court["id"]
    run_index = 1 + max([r["run_index"] for r in db.docket_reviews.values()
                         if r["court_id"] == court_id], default=0)
    pending = court_pending_count(court_id)
    completions = court_completions_ytd(court_id)
    backlog = court_backlog_critical(court)
    rep_rate = representation_rate_pct(court_id)
    pace_cal_f, pace_hd_f, pace_cal_dec = pace_ratios(court, completions, clock)
    is_on_pace = pace_cal_dec >= Decimal("1")
    finalized = process_lapse(court_id)
    review = {
        "id": str(uuid.uuid4()),
        "court_id": court_id,
        "run_index": run_index,
        "computed_at": clock,
        "pending_case_count": pending,
        "completions_ytd": completions,
        "representation_rate_pct": rep_rate,
        "pace_ratio_calendar": pace_cal_f,
        "pace_ratio_hearing_day": pace_hd_f,
        "is_backlog_critical": backlog,
        "is_on_pace": bool(is_on_pace),
        "cases_finalized_by_lapse": finalized,
    }
    db.stamp_new(review)  # ledger record: id + created_at only
    db.docket_reviews[review["id"]] = review
    return review
