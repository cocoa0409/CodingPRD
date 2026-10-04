"""Event-driven rating actions.

SCAFFOLD state_machines -> RatingActionEvent, PRD section 3.8.
"""

from db import base_row, db, now, parse_ts
from errors import fail
from services import analysts as analyst_service
from services import surveillance


def create(surveillance_review_id, rating_decision_id, event_type, effective_at, target_grade):
    row = base_row(common=False)
    row.update(
        {
            "surveillance_review_id": surveillance_review_id,
            "rating_decision_id": rating_decision_id,
            "event_type": event_type,
            "target_grade": target_grade,
            "effective_at": parse_ts(effective_at),
            "event_status": "PENDING",
            "applied_at": None,
        }
    )
    db.rating_action_events[row["id"]] = row
    return row


def apply(row):
    review = db.surveillance_reviews.get(row["surveillance_review_id"])
    entity = db.rated_entities.get(review["rated_entity_id"]) if review else None
    if entity is not None and entity.get("surveillance_posture") == "RESTRICTED":
        fail("ERR_POSTURE_RESTRICTED")

    effective = row.get("effective_at")
    if effective is None or effective > now():
        fail("ERR_ACTION_EFFECTIVE_IN_FUTURE")

    if row["event_status"] != "PENDING":
        fail("ERR_ACTION_NOT_PENDING")

    decision = db.rating_decisions.get(row["rating_decision_id"])
    event_type = row["event_type"]

    if event_type == "UPGRADE":
        if entity is not None:
            entity["current_grade"] = row.get("target_grade") or entity.get("current_grade")
        if decision is not None:
            decision["outlook"] = "POSITIVE"
            decision["watch_status"] = "NO_WATCH"
    elif event_type == "DOWNGRADE":
        if entity is not None:
            entity["current_grade"] = row.get("target_grade") or entity.get("current_grade")
        if decision is not None:
            decision["outlook"] = "NEGATIVE"
            decision["watch_status"] = "NO_WATCH"
    elif event_type == "AFFIRM":
        if decision is not None:
            decision["outlook"] = "STABLE"
            decision["watch_status"] = "NO_WATCH"
    elif event_type == "WATCH_PLACEMENT":
        if decision is not None:
            decision["watch_status"] = "WATCH_DOWNGRADE"

    row["event_status"] = "APPLIED"
    row["applied_at"] = now()

    if decision is not None:
        from db import touch

        touch(decision)

    if entity is not None:
        watch = decision.get("watch_status") if decision else None
        if watch in ("WATCH_UPGRADE", "WATCH_DOWNGRADE"):
            analyst_service.activate_watch(entity)
        else:
            from db import touch

            touch(entity)
    return row


def cancel(row):
    if row["event_status"] != "PENDING":
        fail("ERR_ACTION_NOT_PENDING")

    effective = row.get("effective_at")
    if effective is not None and effective <= now():
        fail("ERR_ACTION_ALREADY_EFFECTIVE")

    row["event_status"] = "REVERTED"

    review = db.surveillance_reviews.get(row["surveillance_review_id"])
    if review is not None:
        review["escalation_bonus"] = int(review.get("escalation_bonus") or 0) + 25
        from db import touch

        touch(review)
        from services import calculations

        review["escalation_index"] = calculations.escalation_index(review)
    surveillance.unfill_slots_for_event(row)
    return row