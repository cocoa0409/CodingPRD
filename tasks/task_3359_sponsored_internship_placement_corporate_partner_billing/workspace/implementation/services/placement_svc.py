"""Placement and agreement lifecycle helpers (PRD 3.3, 3.4, 3.6)."""

import db

COUNTED_STATES = ("ACCEPTED", "ACTIVE", "COMPLETED")


def rounds_of(placement_id):
    return [r for r in db.all_rows("interview_rounds") if r["placement_id"] == placement_id]


def latest_round(placement_id):
    rounds = rounds_of(placement_id)
    if not rounds:
        return None
    return max(rounds, key=lambda r: (r["round_number"], r["_seq"]))


def satisfaction_of(placement_id):
    return [s for s in db.all_rows("satisfaction_records") if s["placement_id"] == placement_id]


def latest_satisfaction(placement_id):
    records = satisfaction_of(placement_id)
    if not records:
        return None
    return max(records, key=lambda s: (s["submitted_at"], s["_seq"]))


def counted_placements(agreement_id):
    """Placements occupying a slot: ACCEPTED, ACTIVE or COMPLETED."""
    return [
        p for p in db.all_rows("placements")
        if p["agreement_id"] == agreement_id and p["state"] in COUNTED_STATES
    ]


def slot_count_reached(agreement):
    return len(counted_placements(agreement["id"])) >= int(agreement["slot_count"])


def refresh_agreement_status(agreement):
    """ACTIVE <-> FULFILLED driven by the occupied slot count."""
    if agreement is None:
        return None
    if agreement["status"] == "DRAFT":
        return agreement
    occupied = len(counted_placements(agreement["id"]))
    if agreement["status"] == "ACTIVE" and occupied >= int(agreement["slot_count"]):
        agreement["status"] = "FULFILLED"
        db.touch(agreement)
    elif agreement["status"] == "FULFILLED" and occupied < int(agreement["slot_count"]):
        agreement["status"] = "ACTIVE"
        db.touch(agreement)
    return agreement


def refresh_agreement_for_placement(placement):
    if placement is None:
        return None
    return refresh_agreement_status(db.get("agreements", placement["agreement_id"]))


def agreement_window_contains(agreement, start, end):
    return (
        start.date() >= agreement["start_date"].date()
        and end.date() <= agreement["end_date"].date()
    )


def latest_round_failed(placement):
    round_row = latest_round(placement["id"])
    return round_row is not None and round_row["outcome"] == "FAILED"


def latest_round_passed(placement):
    round_row = latest_round(placement["id"])
    return round_row is not None and round_row["outcome"] == "PASSED"
