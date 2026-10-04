"""Surveillance reviews and analyst calendar slots.

SCAFFOLD state_machines -> SurveillanceReview / ReviewSlot,
PRD section 3.7.
"""

from db import base_row, days_later, db, now, parse_ts, touch
from domain import (
    POST_BUFFER_MINUTES,
    PRE_BUFFER_MINUTES,
    cycle_months_for,
)
from errors import fail
from services import calculations, common


OPEN_STATUSES = ("SCHEDULED", "OVERDUE", "ESCALATED", "IN_PROGRESS")


def cycle_months(entity):
    return cycle_months_for(entity.get("revenue_band"))


def create_row(rated_entity_id, rating_decision_id, review_type, review_due_at, review_status="SCHEDULED"):
    entity = db.rated_entities.get(rated_entity_id)
    row = base_row()
    row.update(
        {
            "rated_entity_id": rated_entity_id,
            "rating_decision_id": rating_decision_id,
            "review_type": review_type,
            "review_cycle_months": cycle_months(entity) if entity else None,
            "review_due_at": parse_ts(review_due_at) if not hasattr(review_due_at, "tzinfo") else review_due_at,
            "overdue_days": 0,
            "escalation_index": 0,
            "review_status": review_status,
        }
    )
    db.surveillance_reviews[row["id"]] = row
    _sweep(row)
    row["escalation_index"] = calculations.escalation_index(row)
    return row


def create(rated_entity_id, rating_decision_id, review_type, review_due_at):
    return create_row(rated_entity_id, rating_decision_id, review_type, review_due_at)


def _overdue_days(row):
    due = row.get("review_due_at")
    if due is None:
        return 0
    seconds = (now() - due).total_seconds()
    if seconds <= 0:
        return 0
    from decimal import Decimal, ROUND_HALF_UP

    return int(Decimal(seconds / 86400.0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _sweep(row):
    """Automatic SCHEDULED -> OVERDUE -> ESCALATED progression (idempotent)."""
    overdue = _overdue_days(row)
    row["overdue_days"] = overdue

    if row["review_status"] == "SCHEDULED" and overdue > 0:
        row["review_status"] = "OVERDUE"

    if row["review_status"] == "OVERDUE" and overdue >= 30:
        row["review_status"] = "ESCALATED"
        # The escalation bonus is earned once and survives later recomputes.
        row["escalation_bonus"] = int(row.get("escalation_bonus") or 0) + 25
        entity = db.rated_entities.get(row["rated_entity_id"])
        if entity is not None and entity.get("surveillance_posture") != "RESTRICTED":
            entity["surveillance_posture"] = "ACTIVE_WATCH"
            touch(entity)
            calculations.apply_posture_floor(entity["id"])

    if row.get("escalation_bonus") is None:
        row["escalation_bonus"] = 0
    if row.get("posture_floor") is None:
        row["posture_floor"] = 0
    row["escalation_index"] = calculations.escalation_index(row)
    return row


def _refresh(row):
    row["overdue_days"] = _overdue_days(row)
    return row


def refresh_on_read(row):
    """Recompute the derived priority fields on read (PRD section 3.7)."""
    if row["review_status"] in ("COMPLETED",):
        return row
    _sweep(row)
    return row


def start(row):
    entity = db.rated_entities.get(row["rated_entity_id"])
    if entity is not None and entity.get("surveillance_posture") == "RESTRICTED":
        fail("ERR_POSTURE_RESTRICTED")
    if row["review_status"] not in ("SCHEDULED", "OVERDUE", "ESCALATED"):
        fail("ERR_SURVEILLANCE_NOT_STARTABLE")
    row["review_status"] = "IN_PROGRESS"
    return touch(row)


def complete(row):
    if row["review_status"] != "IN_PROGRESS":
        fail("ERR_SURVEILLANCE_NOT_IN_PROGRESS")
    row["review_status"] = "COMPLETED"
    touch(row)

    entity = db.rated_entities.get(row["rated_entity_id"])
    if entity is not None:
        cycle = int(row.get("review_cycle_months") or cycle_months(entity))
        create_row(
            rated_entity_id=row["rated_entity_id"],
            rating_decision_id=row["rating_decision_id"],
            review_type=row["review_type"],
            review_due_at=days_later(now(), 30 * cycle),
            review_status="SCHEDULED",
        )
    return row


def reopen(row):
    if row["review_status"] != "COMPLETED":
        fail("ERR_INVALID_STATE", "The review must be COMPLETED to reopen.")
    grounded = any(
        e["surveillance_review_id"] == row["id"] and e["event_type"] == "WITHDRAWAL"
        for e in db.rating_action_events.values()
    )
    if not grounded:
        fail("ERR_SURVEILLANCE_REOPEN_NOT_GROUNDED")
    row["review_status"] = "IN_PROGRESS"
    touch(row)
    _unfill_slots(row)
    return row


def _unfill_slots(review_row):
    """A slot unfills automatically when its review is reopened."""
    for slot in db.review_slots.values():
        if slot["surveillance_review_id"] != review_row["id"]:
            continue
        if slot["status"] == "BOOKED":
            slot["status"] = "UNFILLED"
            touch(slot)


def unfill_slots_for_event(event):
    for slot in db.review_slots.values():
        if slot["surveillance_review_id"] != event["surveillance_review_id"]:
            continue
        if slot["status"] == "BOOKED":
            slot["status"] = "UNFILLED"
            touch(slot)


# ---------------------------------------------------------------------------
# ReviewSlot
# ---------------------------------------------------------------------------
def create_slot(analyst_id, surveillance_review_id, slot_start, slot_end):
    start_at = parse_ts(slot_start)
    end_at = parse_ts(slot_end)
    if _slot_overlap(analyst_id, start_at, end_at):
        fail("ERR_REVIEW_SLOT_OVERLAP")

    row = base_row()
    row.update(
        {
            "analyst_id": analyst_id,
            "surveillance_review_id": surveillance_review_id,
            "slot_start": start_at,
            "slot_end": end_at,
            "pre_buffer_minutes": PRE_BUFFER_MINUTES,
            "post_buffer_minutes": POST_BUFFER_MINUTES,
            "status": "BOOKED",
        }
    )
    db.review_slots[row["id"]] = row
    return row


def _slot_overlap(analyst_id, start_at, end_at):
    if start_at is None:
        return False
    from datetime import timedelta

    new_start = start_at - timedelta(minutes=PRE_BUFFER_MINUTES)
    new_end = (end_at or start_at) + timedelta(minutes=POST_BUFFER_MINUTES)
    for other in db.review_slots.values():
        if other["analyst_id"] != analyst_id:
            continue
        if other["status"] != "BOOKED":
            continue
        other_start = other["slot_start"]
        if other_start is None:
            continue
        other_end = other["slot_end"] or other_start
        blocked_start = other_start - timedelta(minutes=int(other["pre_buffer_minutes"]))
        blocked_end = other_end + timedelta(minutes=int(other["post_buffer_minutes"]))
        if new_start < blocked_end and blocked_start < new_end:
            return True
    return False


def cancel_slot(row):
    if row["status"] != "BOOKED":
        fail("ERR_SLOT_NOT_BOOKED")
    row["status"] = "CANCELLED"
    return touch(row)