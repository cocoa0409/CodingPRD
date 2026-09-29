"""Capacity counters, conservation invariants and the reconciliation chains.

PRD section 2.9: every counter is recomputed by aggregation after any write that
can move it, and every touched row has updated_at refreshed and version bumped.
"""

from domain import (
    active_placement_count_of_participant, apply, enrollments_of_session,
    opening_of_placement, partnership_of_opening, partnership_of_placement,
    placements_of_opening, placements_of_partnership, sync_participant,
    sync_placement,
)
from ledger import recompute_grant_by_id
from store import db, touch


def sync_opening(opening):
    """openings_count == offered_count + filled_count + remaining_openings."""
    if opening is None:
        return False
    placements = placements_of_opening(opening["id"])
    offered = len([p for p in placements if p["employment_status"] == "OFFERED"])
    filled = len([p for p in placements if p["employment_status"] == "ACTIVE"])
    remaining = int(opening["openings_count"]) - offered - filled
    if remaining < 0:
        remaining = 0
    changed = apply(opening, "offered_count", offered)
    changed = apply(opening, "filled_count", filled) or changed
    changed = apply(opening, "remaining_openings", remaining) or changed
    if opening["status"] == "OPEN" and remaining == 0:
        changed = apply(opening, "status", "FILLED") or changed
    elif opening["status"] == "FILLED" and remaining > 0:
        changed = apply(opening, "status", "OPEN") or changed
    if changed:
        touch(opening)
    return changed


def sync_partnership(partnership):
    """active_placement_count spans every opening of the partnership."""
    if partnership is None:
        return False
    count = len([p for p in placements_of_partnership(partnership["id"])
                 if p["employment_status"] == "ACTIVE"])
    changed = apply(partnership, "active_placement_count", count)
    if changed:
        touch(partnership)
    return changed


def sync_session(session):
    """seat_capacity == enrolled_count + remaining_seats."""
    if session is None:
        return False
    occupying = ("ENROLLED", "ATTENDED", "NO_SHOW")
    enrolled = len([e for e in enrollments_of_session(session["id"])
                    if e["status"] in occupying])
    remaining = int(session["seat_capacity"]) - enrolled
    if remaining < 0:
        remaining = 0
    changed = apply(session, "enrolled_count", enrolled)
    changed = apply(session, "remaining_seats", remaining) or changed
    if changed:
        touch(session)
    return changed


def sync_session_by_id(session_id):
    return sync_session(db.sessions.get(session_id))


def advance_stage_on_active_placement(participant):
    """POST_RELEASE -> PLACED the moment a placement of theirs becomes ACTIVE."""
    if participant is None:
        return False
    if participant["stage"] == "POST_RELEASE":
        if apply(participant, "stage", "PLACED"):
            touch(participant)
            return True
    return False


def revert_stage_on_lost_placement(participant):
    """PLACED / RETENTION -> POST_RELEASE when no active placement remains."""
    if participant is None:
        return False
    if participant["stage"] not in ("PLACED", "RETENTION"):
        return False
    if active_placement_count_of_participant(participant["id"]) != 0:
        return False
    if apply(participant, "stage", "POST_RELEASE"):
        touch(participant)
        return True
    return False


def reconcile_placement_chain(placement, waterfall=True):
    """Placement -> participant posture -> grant ledger, in that order."""
    if placement is None:
        return
    sync_placement(placement)
    participant = db.participants.get(placement["participant_id"])
    if participant is not None:
        sync_participant(participant)
    recompute_grant_by_id(placement.get("grant_id"), allow_waterfall=waterfall)


def reconcile_employment_change(placement):
    """Seat counters, partnership concurrency, money and participant posture."""
    if placement is None:
        return
    opening = opening_of_placement(placement)
    sync_opening(opening)
    sync_partnership(partnership_of_opening(opening) if opening else None)
    sync_placement(placement)
    participant = db.participants.get(placement["participant_id"])
    if participant is not None:
        sync_participant(participant)


def partnership_of(placement):
    return partnership_of_placement(placement)
