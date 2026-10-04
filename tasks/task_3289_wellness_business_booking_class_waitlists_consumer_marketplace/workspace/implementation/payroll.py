"""Payroll periods, commission entries and the instructor substitution ladder."""

from core import fail, now, parse_dt
from commons import (
    mint,
    refresh_payroll_period,
    refresh_staff_accrued,
    require_gate,
    tier_row,
    touch,
)
from store import (
    CLASS_SESSIONS,
    COMMISSION_ENTRIES,
    PAYROLL_PERIODS,
    STAFF_MEMBERS,
    STUDIOS,
    SUBSCRIPTIONS,
)

import calc
import lifecycle


def period_or_404(period_id):
    period = PAYROLL_PERIODS.get(period_id)
    if period is None:
        fail("ERR_PAYROLL_PERIOD_NOT_FOUND")
    return period


def entry_or_404(entry_id):
    entry = COMMISSION_ENTRIES.get(entry_id)
    if entry is None:
        fail("ERR_INVALID_STATE", "The commission entry does not exist.", 404)
    return entry


def create_period(body):
    studio = STUDIOS.get(body.get("studio_id"))
    if studio is None:
        fail("ERR_STUDIO_NOT_FOUND")
    # PRD §2.5 enumerates the gated operations and defining a payroll period is
    # deliberately not among them, so period creation is ungated.
    start = parse_dt(body.get("start_date"))
    end = parse_dt(body.get("end_date"))
    lifecycle.check_period_disjoint(studio["id"], start, end)
    period = mint(
        PAYROLL_PERIODS,
        {
            "studio_id": studio["id"],
            "period_index": int(body.get("period_index", 1)),
            "start_date": start,
            "end_date": end,
            "accrued_commission_cents": 0,
            "paid_commission_cents": 0,
            "reversal_correction_cents": 0,
            "status": "OPEN",
        },
    )
    refresh_payroll_period(period)
    return period


def close_period(period):
    if period.get("status") != "OPEN":
        fail("ERR_PAYROLL_PERIOD_NOT_OPEN")
    studio = STUDIOS.get(period.get("studio_id"))
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id")) if studio else None
    if subscription is not None and subscription.get("payroll_hold"):
        fail("ERR_PAYROLL_HOLD")
    for session in CLASS_SESSIONS.values():
        if session.get("payroll_period_id") != period["id"]:
            continue
        if session.get("status") in ("SCHEDULED", "IN_PROGRESS"):
            fail("ERR_PAYROLL_HOLD", "A session in this period is still open.")
    for entry in COMMISSION_ENTRIES.values():
        if entry.get("payroll_period_id") != period["id"]:
            continue
        if entry.get("status") == "ACCRUED":
            entry["status"] = "PAID"
            touch(entry)
    period["status"] = "LOCKED"
    refresh_payroll_period(period)
    touch(period)
    _refresh_staff_totals(period)
    return period


def reopen_period(period):
    if period.get("status") != "LOCKED":
        fail("ERR_PAYROLL_PERIOD_NOT_OPEN")
    from core import PAYROLL_REOPEN_WINDOW_DAYS, add_days

    if now() >= add_days(period.get("end_date"), PAYROLL_REOPEN_WINDOW_DAYS):
        fail("ERR_PAYROLL_PERIOD_NOT_OPEN", "The reopen window has closed.")
    for entry in COMMISSION_ENTRIES.values():
        if entry.get("payroll_period_id") != period["id"]:
            continue
        if entry.get("status") == "PAID":
            entry["status"] = "ACCRUED"
            touch(entry)
    period["status"] = "OPEN"
    refresh_payroll_period(period)
    touch(period)
    _refresh_staff_totals(period)
    return period


def _refresh_staff_totals(period):
    for staff in STAFF_MEMBERS.values():
        if staff.get("studio_id") == period.get("studio_id"):
            refresh_staff_accrued(staff)


def post_reversal_correction(studio_id, amount):
    """A reversal of a PAID entry posts a signed correction into the next open
    period rather than reopening the closed one."""
    open_periods = [
        p
        for p in PAYROLL_PERIODS.values()
        if p.get("studio_id") == studio_id and p.get("status") == "OPEN"
    ]
    open_periods.sort(key=lambda p: (p.get("period_index", 0), p.get("created_at")))
    if open_periods:
        open_periods[0]["reversal_correction_cents"] = (
            open_periods[0].get("reversal_correction_cents", 0) + amount
        )
        touch(open_periods[0])
        refresh_payroll_period(open_periods[0])


def reverse_entry(entry, reason):
    """ACCRUED entries reverse in place; PAID entries become a period
    correction."""
    if entry.get("status") == "REVERSED":
        return
    if entry.get("status") == "ACCRUED":
        entry["status"] = "REVERSED"
        entry["reversal_reason"] = reason
        touch(entry)
        period = PAYROLL_PERIODS.get(entry.get("payroll_period_id"))
        if period is not None:
            refresh_payroll_period(period)
        staff = STAFF_MEMBERS.get(entry.get("staff_member_id"))
        if staff is not None:
            refresh_staff_accrued(staff)
    else:
        entry["status"] = "REVERSED"
        entry["reversal_reason"] = reason
        touch(entry)
        post_reversal_correction(
            entry.get("studio_id"), -entry.get("commission_cents", 0)
        )


# ---------------------------------------------------------------------------
# Substitution ladder
# ---------------------------------------------------------------------------


def candidate_instructors(session, exclude_staff_id=None):
    studio_id = session.get("studio_id")
    of_record = session.get("instructor_staff_id")
    candidates = []
    for staff in STAFF_MEMBERS.values():
        if staff.get("studio_id") != studio_id:
            continue
        if staff.get("staff_role") != "INSTRUCTOR":
            continue
        if staff.get("status") not in ("ACTIVE", "SUBSTITUTE_ONLY"):
            continue
        if staff["id"] == of_record and exclude_staff_id is None:
            continue
        if exclude_staff_id is not None and staff["id"] == exclude_staff_id:
            continue
        candidates.append(staff)
    studio = STUDIOS.get(studio_id)
    subscription = SUBSCRIPTIONS.get(studio.get("subscription_id")) if studio else None
    tier = subscription.get("tier") if subscription else None
    all_sessions = list(CLASS_SESSIONS.values())
    scored = []
    for staff in candidates:
        overlap = calc.overlapping_taught_minutes(staff["id"], session, all_sessions)
        score = calc.substitution_score(staff, session, tier, overlap)
        scored.append((score, staff.get("created_at"), staff))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored


def eligible_instructors(session, exclude_staff_id=None, limit=None):
    scored = candidate_instructors(session, exclude_staff_id)
    result = []
    for score, _created, staff in scored:
        result.append(
            {
                "id": staff["id"],
                "staff_member_id": staff["id"],
                "full_name": staff.get("full_name"),
                "staff_role": staff.get("staff_role"),
                "status": staff.get("status"),
                "score": score,
                "overlapping_taught_minutes": calc.overlapping_taught_minutes(
                    staff["id"], session, list(CLASS_SESSIONS.values())
                ),
            }
        )
    return result


def reassign_instructor(session, body):
    if session.get("status") != "SCHEDULED":
        fail("ERR_SESSION_NOT_SCHEDULED")
    selected_id = body.get("selected_staff_id")
    studio = STUDIOS.get(session.get("studio_id"))
    require_gate(studio, "instructor_substitution") if studio else None

    selected = STAFF_MEMBERS.get(selected_id)
    if selected is None:
        fail("ERR_STAFF_MEMBER_NOT_FOUND")

    # PRD §3.5: a nominated instructor who is absent from the candidate set —
    # *or who is the instructor of record* — is refused with
    # ERR_INSTRUCTOR_NOT_ELIGIBLE.  Because the candidate set excludes the
    # instructor of record, naming them is a distinct refusal from the
    # empty-pool ERR_NO_ELIGIBLE_SUBSTITUTE.
    if selected_id == session.get("instructor_staff_id"):
        fail("ERR_INSTRUCTOR_NOT_ELIGIBLE")

    scored = candidate_instructors(session)
    if not scored:
        if not body.get("override_reason"):
            fail("ERR_NO_ELIGIBLE_SUBSTITUTE")
    else:
        eligible_ids = [staff["id"] for _s, _c, staff in scored]
        if selected_id not in eligible_ids:
            fail("ERR_INSTRUCTOR_NOT_ELIGIBLE")

    previous = session.get("instructor_staff_id")
    session["instructor_staff_id"] = selected_id
    session["substitute_accepted"] = True
    touch(session)
    for entry in COMMISSION_ENTRIES.values():
        if entry.get("booking_id") is None:
            continue
        booking = None
        from store import BOOKINGS

        booking = BOOKINGS.get(entry.get("booking_id"))
        if booking is None or booking.get("class_session_id") != session["id"]:
            continue
        if entry.get("staff_member_id") == previous:
            reverse_entry(entry, "INSTRUCTOR_SUBSTITUTED")
    selected["substitution_count"] = selected.get("substitution_count", 0) + 1
    touch(selected)
    return session