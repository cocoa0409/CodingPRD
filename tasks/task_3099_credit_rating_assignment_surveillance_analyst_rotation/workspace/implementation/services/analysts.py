"""Analysts: onboarding, departure and look-back reviews.

SCAFFOLD state_machines -> Analyst, LookBackReview, PRD sections 3.3 and 3.9.
"""

from db import base_row, db, days_later, now, parse_ts, touch
from datetime import timedelta
from domain import LOOKBACK_BLOCKING_MONTHS, MONTH_DAYS
from errors import fail
from services import common


def create(full_name, primary_sector, analyst_tier, independence_declared_at):
    row = base_row()
    row.update(
        {
            "full_name": full_name,
            "primary_sector": primary_sector,
            "analyst_tier": analyst_tier,
            "independence_declared_at": parse_ts(independence_declared_at),
            "first_assignment_at": None,
            "last_lead_assignment_at": None,
            "consecutive_lead_months": 0,
            "rotation_eligible": True,
            "is_departed": False,
            "departed_to_entity_id": None,
            # Internal bookkeeping only — never emitted in the response shape.
            "departure_date": None,
        }
    )
    db.analysts[row["id"]] = row
    return row


def depart(row, departed_to_entity_id, departure_date):
    row["is_departed"] = True
    row["departed_to_entity_id"] = departed_to_entity_id
    row["departure_date"] = parse_ts(departure_date)
    return touch(row)


def in_lookback_window(analyst):
    """True when the analyst left for a rated issuer in the last 24 months."""
    if not analyst.get("is_departed"):
        return False
    if not analyst.get("departed_to_entity_id"):
        return False
    departed_at = analyst.get("departure_date")
    if departed_at is None:
        return True
    window = days_later(departed_at, LOOKBACK_BLOCKING_MONTHS * MONTH_DAYS)
    return now() <= window


# ---------------------------------------------------------------------------
# LookBackReview
# ---------------------------------------------------------------------------
def create_lookback(analyst_id, departed_to_entity_id, departure_date, lookback_period_months):
    row = base_row()
    row.update(
        {
            "analyst_id": analyst_id,
            "departed_to_entity_id": departed_to_entity_id,
            "departure_date": parse_ts(departure_date),
            "lookback_period_months": int(lookback_period_months or 0),
            "affected_decisions_count": 0,
            "review_status": "INITIATED",
        }
    )
    db.look_back_reviews[row["id"]] = row
    return row


def start_lookback(row):
    if row["review_status"] != "INITIATED":
        fail("ERR_INVALID_STATE", "The look-back review must be INITIATED to start.")
    analyst = db.analysts.get(row["analyst_id"])
    if analyst is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if analyst.get("departure_date") is None and row.get("departure_date") is None:
        fail("ERR_LOOKBACK_NOT_GROUNDED")

    departure = row.get("departure_date") or analyst.get("departure_date")
    window_start = departure - _lookback_span(row)
    count = 0
    for decision in db.rating_decisions.values():
        if decision["decision_status"] != "PUBLISHED":
            continue
        published = decision.get("published_at")
        if published is None:
            continue
        if published < window_start or published > departure:
            continue
        if _analyst_appeared(row["analyst_id"], decision):
            count += 1
    row["affected_decisions_count"] = count
    row["review_status"] = "IN_PROGRESS"
    return touch(row)


def _lookback_span(row):
    """The look-back window length, in the scaffold's 30-day months."""
    return timedelta(days=MONTH_DAYS * int(row.get("lookback_period_months") or 0))


def _analyst_appeared(analyst_id, decision):
    """Did the analyst lead, support or vote on this decision?"""
    for assignment in db.team_assignments.values():
        if assignment["rating_request_id"] != decision["rating_request_id"]:
            continue
        if analyst_id in (assignment["lead_analyst_id"], assignment["support_analyst_id"]):
            return True
    committee = common.primary_committee_for_request(decision["rating_request_id"])
    if committee is not None:
        for vote in db.committee_votes.values():
            if vote["rating_committee_id"] == committee["id"] and vote["analyst_id"] == analyst_id:
                return True
    return False


def close_lookback(row):
    if row["review_status"] != "IN_PROGRESS":
        fail("ERR_LOOKBACK_NOT_IN_PROGRESS")
    row["review_status"] = "CLOSED"

    # Flag the departed analyst's surviving assignments for re-screening and
    # move the joined issuer's posture to ACTIVE_WATCH (PRD section 3.9).
    for assignment in db.team_assignments.values():
        if assignment["lead_analyst_id"] != row["analyst_id"] and assignment[
            "support_analyst_id"
        ] != row["analyst_id"]:
            continue
        request = db.rating_requests.get(assignment["rating_request_id"])
        if request is None:
            continue
        decision = common.any_decision_for_request(request["id"])
        if decision is None or decision["decision_status"] != "PUBLISHED":
            continue
        if assignment["status"] == "CONFIRMED":
            assignment["conflict_status"] = "POTENTIAL"
            touch(assignment)

    entity = db.rated_entities.get(row["departed_to_entity_id"])
    if entity is not None:
        activate_watch(entity)
    return touch(row)


def activate_watch(entity):
    """Move an entity's surveillance_posture to ACTIVE_WATCH and floor reviews."""
    from services import calculations

    if entity.get("surveillance_posture") == "RESTRICTED":
        return entity
    entity["surveillance_posture"] = "ACTIVE_WATCH"
    touch(entity)
    calculations.apply_posture_floor(entity["id"])
    return entity