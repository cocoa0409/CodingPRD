"""Cascading side effects (PRD §2.7, §3.2-§3.4).

Seat flips, the waitlist promotion waterfall, enrollment side effects,
registration cancellation, and the volunteer-cleared auto-confirm.
"""

from datetime import timedelta

import clock
import store
from derived import (
    CHILD_FACING_ROLES,
    REQUIRED_CHECK_TYPES,
    open_seats,
    regs_of_classroom,
)


# ---------------------------------------------------------------- seat flips

def flip_full_if_saturated(classroom):
    """ACCEPTING -> FULL when an enrollment consumed the last open seat."""
    if classroom["status"] == "ACCEPTING" and open_seats(classroom) == 0:
        classroom["status"] = "FULL"
        store.touch(classroom)


def run_promotion_loop(classroom):
    """The waitlist waterfall: promote one, recompute, repeat (PRD §2.7)."""
    if classroom["status"] not in ("ACCEPTING", "FULL"):
        return
    program = store.get("programs", classroom["program_id"])
    ttl = program["waitlist_offer_ttl_hours"] if program else 48
    while True:
        if open_seats(classroom) < 1:
            return
        queue = [
            r
            for r in regs_of_classroom(classroom["id"])
            if r["status"] == "WAITLISTED"
        ]
        if not queue:
            return
        head = min(queue, key=lambda r: r["_seq"])
        head["status"] = "OFFERED"
        head["offer_expires_at"] = clock.now() + timedelta(hours=ttl)
        store.touch(head)


def seat_freed(classroom):
    """A seat opened (cancellation, decline, expiry, capacity increase)."""
    if classroom["status"] == "FULL" and open_seats(classroom) >= 1:
        classroom["status"] = "ACCEPTING"
        store.touch(classroom)
    run_promotion_loop(classroom)


# ---------------------------------------------------------------- enrollment

def _open_day_of_program(program):
    if program["current_day_index"]:
        for d in store.all_of("program_days"):
            if (
                d["program_id"] == program["id"]
                and d["day_index"] == program["current_day_index"]
                and d["status"] == "OPEN"
            ):
                return d
    return None


def on_registration_enrolled(reg, classroom, program):
    """Side effects of a registration entering ENROLLED (create or accept)."""
    reg["enrolled_at"] = clock.now()
    flip_full_if_saturated(classroom)
    if program["status"] == "IN_SESSION":
        day = _open_day_of_program(program)
        if day is not None:
            existing = [
                r
                for r in store.all_of("attendance_records")
                if r["child_id"] == reg["child_id"] and r["program_day_id"] == day["id"]
            ]
            if not existing:
                store.put(
                    "attendance_records",
                    store.new_record(
                        child_id=reg["child_id"],
                        program_day_id=day["id"],
                        registration_id=reg["id"],
                        status="NOT_ARRIVED",
                        tag_code=None,
                        checked_in_at=None,
                        checked_out_at=None,
                        checked_in_by=None,
                        checked_out_by=None,
                        pickup_person=None,
                        late_pickup=False,
                    ),
                )


# ---------------------------------------------------------------- cancellation

def cancel_registration(reg, reason, run_cascade=True):
    """Shared cancellation path (direct cancel, family archive, classroom close).

    ENROLLED cancellations drop future NOT_ARRIVED attendance records and run
    the seat-flip + promotion cascade; OFFERED cancellations free the reserved
    seat the same way; WAITLISTED cancellations just leave the queue. Classroom
    close suppresses the cascade — the whole queue is being torn down.
    """
    previous = reg["status"]
    reg["status"] = "CANCELLED"
    reg["cancellation_reason"] = reason
    if previous == "OFFERED":
        reg["offer_expires_at"] = None
    store.touch(reg)
    classroom = store.get("classrooms", reg["classroom_id"])
    if previous == "ENROLLED":
        for rec in list(store.all_of("attendance_records")):
            if rec["registration_id"] != reg["id"] or rec["status"] != "NOT_ARRIVED":
                continue
            day = store.get("program_days", rec["program_day_id"])
            if day is not None and day["status"] in ("SCHEDULED", "OPEN"):
                store.delete("attendance_records", rec["id"])
        if run_cascade and classroom is not None:
            seat_freed(classroom)
    elif previous == "OFFERED":
        if run_cascade and classroom is not None:
            seat_freed(classroom)


# ---------------------------------------------------------------- volunteers

def assignment_rule_violation(ra, volunteer):
    """True when confirming `ra` would violate lead-uniqueness or double-booking."""
    if ra["role"] == "LEAD_TEACHER":
        for other in store.all_of("role_assignments"):
            if (
                other["id"] != ra["id"]
                and other["classroom_id"] == ra["classroom_id"]
                and other["role"] == "LEAD_TEACHER"
                and other["status"] == "CONFIRMED"
            ):
                return True
    if ra["role"] in CHILD_FACING_ROLES:
        classroom = store.get("classrooms", ra["classroom_id"])
        program_id = classroom["program_id"] if classroom else None
        for other in store.all_of("role_assignments"):
            if (
                other["id"] == ra["id"]
                or other["volunteer_id"] != volunteer["id"]
                or other["status"] != "CONFIRMED"
                or other["role"] not in CHILD_FACING_ROLES
            ):
                continue
            other_classroom = store.get("classrooms", other["classroom_id"])
            if (
                other_classroom is not None
                and other_classroom["program_id"] == program_id
                and other["classroom_id"] != ra["classroom_id"]
            ):
                return True
    return False


def confirm_assignment(ra):
    ra["status"] = "CONFIRMED"
    ra["confirmed_at"] = clock.now()
    store.touch(ra)


def auto_confirm_assignments(volunteer):
    """On CLEARED: auto-confirm PROPOSED assignments, skipping rule violators."""
    proposed = store.by_seq(
        ra
        for ra in store.all_of("role_assignments")
        if ra["volunteer_id"] == volunteer["id"] and ra["status"] == "PROPOSED"
    )
    for ra in proposed:
        if assignment_rule_violation(ra, volunteer):
            continue
        confirm_assignment(ra)


def recompute_volunteer_status(volunteer):
    """Volunteer rollup after a screening decision (PRD §3.4)."""
    checks = [c for c in store.all_of("screening_checks") if c["volunteer_id"] == volunteer["id"]]
    if any(c["status"] == "REJECTED" for c in checks):
        if volunteer["status"] == "SCREENING":
            volunteer["status"] = "REJECTED"
            store.touch(volunteer)
        return
    cleared_types = {c["check_type"] for c in checks if c["status"] == "CLEARED"}
    if REQUIRED_CHECK_TYPES <= cleared_types and volunteer["status"] == "SCREENING":
        volunteer["status"] = "CLEARED"
        store.touch(volunteer)
        auto_confirm_assignments(volunteer)
