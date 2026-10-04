"""Cross-entity side effects: assignment release, suspension, clock sweeps."""

import clock
import db
from db import touch


def release_pending_assignments(wholesaler_id):
    """Every PENDING assignment naming the wholesaler becomes RELEASED (§3.5):
    released_qty increases and pending_qty decreases by each assigned_qty."""
    for event in db.allocation_events.values():
        changed = False
        for assignment in event["assignments"]:
            if (assignment["wholesaler_id"] == wholesaler_id
                    and assignment["status"] == "PENDING"):
                assignment["status"] = "RELEASED"
                event["released_qty"] += assignment["assigned_qty"]
                event["pending_qty"] -= assignment["assigned_qty"]
                changed = True
        if changed:
            touch(event)


def maybe_suspend_wholesaler(wholesaler):
    """APPOINTED -> SUSPENDED once the suspended-account count reaches 3 (§3.6).
    The caller performs the wholesaler touch() covering this status change."""
    if (wholesaler["status"] == "APPOINTED"
            and wholesaler["suspended_account_count"] >= 3):
        wholesaler["status"] = "SUSPENDED"
        release_pending_assignments(wholesaler["id"])
        return True
    return False


def run_clock_sweeps(new_clock):
    """Time-based sweeps executed as part of setting the logical clock (§2.5).

    - ROFR_OPEN transfers whose rofr_deadline is strictly before the new clock
      lapse to ROFR_LAPSED.
    - APPROVED transfers whose consummation_deadline is strictly before the new
      clock expire to EXPIRED.
    - OPEN promotion programs whose ends_at is at or before the new clock close.
    """
    rofr_lapsed = 0
    consummation_expired = 0
    promotions_closed = 0
    for transfer in db.transfers.values():
        if (transfer["status"] == "ROFR_OPEN"
                and transfer["rofr_deadline"] is not None
                and clock.parse_iso(transfer["rofr_deadline"]) < new_clock):
            transfer["status"] = "ROFR_LAPSED"
            touch(transfer)
            rofr_lapsed += 1
        elif (transfer["status"] == "APPROVED"
                and transfer["consummation_deadline"] is not None
                and clock.parse_iso(transfer["consummation_deadline"]) < new_clock):
            transfer["status"] = "EXPIRED"
            touch(transfer)
            consummation_expired += 1
    for program in db.programs.values():
        if (program["status"] == "OPEN"
                and clock.parse_iso(program["ends_at"]) <= new_clock):
            program["status"] = "CLOSED"
            touch(program)
            promotions_closed += 1
    return {
        "rofr_lapsed_count": rofr_lapsed,
        "consummation_expired_count": consummation_expired,
        "promotions_closed_count": promotions_closed,
    }
