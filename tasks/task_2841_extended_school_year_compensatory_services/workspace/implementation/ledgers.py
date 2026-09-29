"""Full-recomputation ledgers and version-bearing cascades (PRD section 2.11).

Every derived total below is rebuilt from the current row set rather than
patched with a delta, and every recomputation this module performs bumps the
recomputed resource's `version` and refreshes its `updated_at`.
"""
from calcs import (AUTO_AWARD_THRESHOLD_MINUTES, MAX_PARENT_NO_SHOWS,
                   refresh_available)
from store import db, today, touch
from validate import d

SEAT_HOLDING_COMMITMENT_STATES = ("PLANNED", "ASSIGNED", "ACTIVE", "SUSPENDED")
STAY_PUT_RECORD_TYPES = ("COMPLAINT", "DUE_PROCESS_HEARING")
OWED_NEGOTIATION_STATES = ("AGREED", "CLOSED")


# ---------------------------------------------------------------- commitment
def recompute_commitment_ledger(commitment, bump=True):
    """PRD 3.6: rebuilt across the commitment's VERIFIED logs."""
    logs = [log for log in db.logs.values()
            if log["commitment_id"] == commitment["id"] and log["status"] == "VERIFIED"]
    commitment["delivered_minutes"] = sum(log["minutes_delivered"] for log in logs)
    commitment["compensable_owed_minutes"] = sum(
        log["minutes_scheduled"] - log["minutes_delivered"] for log in logs
        if log["outcome"] in ("MISSED_DISTRICT", "PARTIAL"))
    if bump:
        touch(commitment)
    return commitment


# ------------------------------------------------------------------- student
def recompute_student_ledger(student, bump=True):
    """PRD 3.1: the four minute totals and the two flags, all from scratch."""
    pending = sum(c["compensable_owed_minutes"] for c in db.commitments.values()
                  if c["student_id"] == student["id"] and c["status"] != "TERMINATED")
    student["pending_award_minutes"] = pending
    student["esy_service_alert"] = pending >= AUTO_AWARD_THRESHOLD_MINUTES

    awards = [a for a in db.awards.values() if a["student_id"] == student["id"]]
    student["outstanding_owed_minutes"] = sum(
        max(0, (a["agreed_minutes"] or 0) - a["delivered_minutes"] - a["forfeited_minutes"])
        for a in awards if a["negotiation_status"] in OWED_NEGOTIATION_STATES)
    student["delivered_makeup_minutes_total"] = sum(a["delivered_minutes"] for a in awards)

    student["stay_put_active"] = any(
        r["status"] == "OPEN" and r["record_type"] in STAY_PUT_RECORD_TYPES
        for r in db.records.values() if r["student_id"] == student["id"])
    if bump:
        touch(student)
    return student


def student_of_commitment(commitment):
    return db.students.get(commitment["student_id"])


# --------------------------------------------------------------------- award
def recompute_award_ledger(award, bump=True):
    """PRD 3.8: forfeited_minutes persists and is deliberately not rebuilt."""
    sessions = [s for s in db.sessions.values() if s["award_id"] == award["id"]]
    award["delivered_minutes"] = sum(s["minutes_delivered"] for s in sessions
                                    if s["status"] == "DELIVERED")
    award["scheduled_minutes"] = sum(s["minutes_planned"] for s in sessions
                                    if s["status"] == "SCHEDULED")
    award["parent_no_show_count"] = sum(1 for s in sessions
                                       if s["status"] == "NO_SHOW_PARENT")
    award["remaining_owed_minutes"] = max(
        0, (award["agreed_minutes"] or 0) - award["delivered_minutes"]
        - award["forfeited_minutes"])
    if bump:
        touch(award)
    return award


def close_negotiation_if_delivery_terminal(award):
    """PRD 3.7: FULFILLED or LAPSED drags negotiation AGREED -> CLOSED."""
    if (award["delivery_status"] in ("FULFILLED", "LAPSED")
            and award["negotiation_status"] == "AGREED"):
        award["negotiation_status"] = "CLOSED"
        touch(award)
        return True
    return False


def reopen_negotiation_if_delivery_active(award):
    """PRD 3.8: a void that reopens the debt drags CLOSED back to AGREED."""
    if (award["delivery_status"] in ("SCHEDULING", "IN_PROGRESS")
            and award["negotiation_status"] == "CLOSED"):
        award["negotiation_status"] = "AGREED"
        touch(award)
        return True
    return False


def apply_lazy_lapse(award):
    """PRD 2.5 / 3.8: evaluated at the start of any request touching the award."""
    if award["delivery_status"] not in ("SCHEDULING", "IN_PROGRESS"):
        return False
    if award["remaining_owed_minutes"] <= 0:
        return False
    deadline = award.get("delivery_deadline_date")
    if not deadline or today() <= d(deadline):
        return False
    award["delivery_status"] = "LAPSED"
    touch(award)
    close_negotiation_if_delivery_terminal(award)
    student = db.students.get(award["student_id"])
    if student is not None:
        recompute_student_ledger(student)
    return True


def apply_no_show_forfeiture(award, session):
    """PRD 3.8: at MAX_PARENT_NO_SHOWS this session's planned minutes forfeit."""
    if award["parent_no_show_count"] < MAX_PARENT_NO_SHOWS:
        return False
    award["forfeited_minutes"] += session["minutes_planned"]
    award["remaining_owed_minutes"] = max(
        0, (award["agreed_minutes"] or 0) - award["delivered_minutes"]
        - award["forfeited_minutes"])
    return True


# ------------------------------------------------------------------- run
def recompute_run_seats(run, bump=True):
    """PRD 3.3: a CANCELLED run freezes seats_committed where it stood."""
    if run["status"] == "CANCELLED":
        return run
    run["seats_committed"] = sum(
        1 for c in db.commitments.values()
        if c["transportation_run_id"] == run["id"]
        and c["status"] in SEAT_HOLDING_COMMITMENT_STATES)
    if bump:
        touch(run)
    return run


def release_seat(commitment):
    run_id = commitment.get("transportation_run_id")
    if not run_id:
        return
    run = db.runs.get(run_id)
    if run is not None:
        recompute_run_seats(run)


# ------------------------------------------------------------- fiscal reversal
def allocation_for_charge(program_id, fund_source, budget_code):
    """(program_id, budget_code) is unique, so the charge coding resolves it."""
    for allocation in db.allocations.values():
        if (allocation["program_id"] == program_id
                and allocation["budget_code"] == budget_code
                and allocation["fund_source"] == fund_source):
            return allocation
    return None


def leave_assignment(assignment, new_status, release_reason):
    """PRD 3.5: reverse an assignment's footprint exactly, in three parts."""
    commitment = db.commitments.get(assignment["commitment_id"])
    program_id = commitment["program_id"] if commitment else None
    allocation = allocation_for_charge(
        program_id, assignment.get("charged_fund_source"),
        assignment.get("charged_budget_code"))
    if allocation is not None and assignment["total_charge_cents"]:
        allocation["encumbered_amount_cents"] -= assignment["total_charge_cents"]
        refresh_available(allocation)
        touch(allocation)

    provider = db.providers.get(assignment["provider_id"])
    if provider is not None:
        provider["assigned_weekly_minutes"] = recomputed_provider_load(provider,
                                                                      exclude=assignment["id"])
        touch(provider)

    assignment["status"] = new_status
    assignment["release_reason"] = release_reason
    touch(assignment)
    return assignment


def recomputed_provider_load(provider, exclude=None, extra=0):
    """Sum covered_weekly_minutes over the provider's ACTIVE assignments."""
    total = sum(a["covered_weekly_minutes"] for a in db.assignments.values()
                if a["provider_id"] == provider["id"] and a["status"] == "ACTIVE"
                and a["id"] != exclude)
    return total + extra
