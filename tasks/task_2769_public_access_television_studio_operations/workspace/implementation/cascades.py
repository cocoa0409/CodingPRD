"""Synchronous cascades (PRD 2.9): every downstream row moves before the
response is written. There is no eventual consistency here.
"""

import calc
import constants
import db


# --------------------------------------------------------------------------- #
# crew
# --------------------------------------------------------------------------- #
def release_slot_crew(slot, release_reason):
    """Release every OFFERED or CONFIRMED assignment on a slot."""
    released = []
    for assignment in db.all_rows("crew_assignments"):
        if assignment["slot_id"] != slot["id"]:
            continue
        if assignment["status"] not in ("OFFERED", "CONFIRMED"):
            continue
        assignment["status"] = "RELEASED"
        assignment["release_reason"] = release_reason
        db.bump(assignment)
        released.append(assignment)
    # staffing_status on the slot and confirmed_crew_commitments on each
    # volunteer are derived quantities and are re-read from these rows.
    return released


# --------------------------------------------------------------------------- #
# series hold plan bookkeeping
# --------------------------------------------------------------------------- #
def restore_hold_slot(slot, count_missed_window):
    """Return a consumed hold slot. Cancellation also spends a missed window."""
    if slot.get("booking_type") != "SERIES_HOLD":
        return None
    series = db.get("series", slot.get("series_id")) if slot.get("series_id") else None
    if series is None:
        return None
    series["remaining_hold_slots"] = series["remaining_hold_slots"] + 1
    if count_missed_window:
        series["missed_windows"] = series["missed_windows"] + 1
    db.bump(series)
    if count_missed_window:
        lapse_series_if_due(series)
    return series


def lapse_series_if_due(series):
    """ACTIVE -> LAPSED fires the moment missed_windows reaches the threshold."""
    if series["status"] != "ACTIVE":
        return False
    if series["missed_windows"] < constants.SERIES_LAPSE_MISSED_WINDOWS:
        return False
    series["status"] = "LAPSED"
    series["remaining_hold_slots"] = 0
    db.bump(series)
    return True


def retire_series(series):
    if series["status"] not in ("PROPOSED", "ACTIVE", "LAPSED"):
        return False
    series["status"] = "RETIRED"
    series["remaining_hold_slots"] = 0
    db.bump(series)
    for successor in db.all_rows("series"):
        if successor.get("predecessor_series_id") != series["id"]:
            continue
        if successor.get("seniority_at") is None:
            continue
        recomputed = calc.series_seniority_at(successor)
        if recomputed != successor["seniority_at"]:
            successor["seniority_at"] = recomputed
            db.bump(successor)
    return True


# --------------------------------------------------------------------------- #
# playback slots
# --------------------------------------------------------------------------- #
def withdraw_slot(slot):
    """SCHEDULED -> WITHDRAWN behind a withdrawn or rejected program.

    The channel's scheduled_seconds falls out of the derived sum, the hold slot
    is returned without spending a missed window, and the crew is released.
    """
    if slot["status"] != "SCHEDULED":
        return False
    slot["status"] = "WITHDRAWN"
    db.bump(slot)
    restore_hold_slot(slot, count_missed_window=False)
    release_slot_crew(slot, "PROGRAM_WITHDRAWN")
    return True


def preempt_slot(slot, challenger_slot_id):
    slot["status"] = "PREEMPTED"
    slot["preempted_by_slot_id"] = challenger_slot_id
    db.bump(slot)
    release_slot_crew(slot, "SLOT_PREEMPTED")
    return True


# --------------------------------------------------------------------------- #
# archive assets
# --------------------------------------------------------------------------- #
def withdraw_published_assets(program):
    for asset in db.all_rows("archive_assets"):
        if asset["program_id"] != program["id"]:
            continue
        if asset["on_demand_status"] != "PUBLISHED":
            continue
        asset["on_demand_status"] = "WITHDRAWN"
        db.bump(asset)


# --------------------------------------------------------------------------- #
# programs
# --------------------------------------------------------------------------- #
def derive_clearance_status(program):
    """PRD 3.3: the latest attestation of each required kind must carry the
    current statement version. A revoked producer clears nothing.
    """
    producer = db.get("producers", program["producer_id"])
    if producer is not None and producer["status"] == "REVOKED":
        return "INCOMPLETE"
    for kind in constants.REQUIRED_ATTESTATION_KINDS:
        latest = latest_attestation(program["id"], kind)
        if latest is None:
            return "INCOMPLETE"
        if latest["statement_version"] != constants.CURRENT_STATEMENT_VERSION:
            return "INCOMPLETE"
    return "CLEARED"


def latest_attestation(program_id, kind):
    """Greatest created_at, then greatest sequence_number."""
    latest = None
    for row in db.all_rows("attestations"):
        if row["program_id"] != program_id or row["attestation_kind"] != kind:
            continue
        if latest is None:
            latest = row
            continue
        key_new = (row["created_at"], row["sequence_number"])
        key_old = (latest["created_at"], latest["sequence_number"])
        if key_new > key_old:
            latest = row
    return latest


def refresh_clearance(program):
    derived = derive_clearance_status(program)
    if derived != program["clearance_status"]:
        program["clearance_status"] = derived
        return True
    return False


def withdraw_program_slots(program, release_reason="PROGRAM_WITHDRAWN"):
    for slot in db.all_rows("playback_slots"):
        if slot["program_id"] != program["id"] or slot["status"] != "SCHEDULED":
            continue
        slot["status"] = "WITHDRAWN"
        db.bump(slot)
        restore_hold_slot(slot, count_missed_window=False)
        release_slot_crew(slot, release_reason)


# --------------------------------------------------------------------------- #
# reservations and deposits
# --------------------------------------------------------------------------- #
def settle_reservation(reservation, assessed_repair_cents):
    """The DAMAGE_REVIEW -> SETTLED join point (PRD 3.7)."""
    reservation["assessed_repair_cents"] = assessed_repair_cents
    reservation.update(calc.settlement(reservation, assessed_repair_cents))
    reservation["status"] = "SETTLED"
    db.bump(reservation)
    return reservation


def cancel_reservation_for_sanction(reservation, cancellation_reason):
    """Cancel a REQUESTED or CONFIRMED reservation, releasing any hold."""
    if reservation["status"] not in ("REQUESTED", "CONFIRMED"):
        return False
    was_confirmed = reservation["status"] == "CONFIRMED"
    reservation["status"] = "CANCELLED"
    reservation["cancellation_reason"] = cancellation_reason
    if was_confirmed:
        # the hold itself is retained for audit rather than zeroed
        reservation["deposit_refunded_cents"] = reservation["deposit_hold_cents"]
        reservation["deposit_forfeited_cents"] = 0
        reservation["uncovered_liability_cents"] = 0
    db.bump(reservation)
    return True


# --------------------------------------------------------------------------- #
# producers
# --------------------------------------------------------------------------- #
def suspend_producer_if_due(producer):
    """The third link of the finalization cascade (PRD 3.7)."""
    if producer["status"] != "ACTIVE":
        return False
    if producer["suspension_points"] < constants.SUSPENSION_THRESHOLD_POINTS:
        return False
    producer["status"] = "SUSPENDED"
    db.bump(producer)
    for reservation in db.all_rows("reservations"):
        if reservation["producer_id"] != producer["id"]:
            continue
        cancel_reservation_for_sanction(reservation, "PRODUCER_SUSPENDED")
    for assignment in db.all_rows("crew_assignments"):
        if assignment["volunteer_producer_id"] != producer["id"]:
            continue
        if assignment["status"] not in ("OFFERED", "CONFIRMED"):
            continue
        slot = db.get("playback_slots", assignment["slot_id"])
        if slot is None or slot["status"] != "SCHEDULED":
            continue
        assignment["status"] = "RELEASED"
        assignment["release_reason"] = "VOLUNTEER_SUSPENDED"
        db.bump(assignment)
    return True


def revoke_producer(producer, revocation_reason):
    """PRD 3.7 revocation: reservations, crew, series and clearance all unwind."""
    producer["status"] = "REVOKED"
    producer["revocation_reason"] = revocation_reason
    db.bump(producer)

    for reservation in db.all_rows("reservations"):
        if reservation["producer_id"] != producer["id"]:
            continue
        cancel_reservation_for_sanction(reservation, "PRODUCER_REVOKED")

    for assignment in db.all_rows("crew_assignments"):
        if assignment["volunteer_producer_id"] != producer["id"]:
            continue
        if assignment["status"] not in ("OFFERED", "CONFIRMED"):
            continue
        assignment["status"] = "RELEASED"
        assignment["release_reason"] = "VOLUNTEER_REVOKED"
        db.bump(assignment)

    for series in db.all_rows("series"):
        if series["producer_id"] != producer["id"]:
            continue
        retire_series(series)

    for program in db.all_rows("programs"):
        if program["producer_id"] != producer["id"]:
            continue
        if program["review_status"] in ("REJECTED", "WITHDRAWN"):
            continue
        if refresh_clearance(program):
            db.bump(program)
