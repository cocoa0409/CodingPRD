"""Engagement letters and their termination cascade.

SCAFFOLD state_machines -> EngagementLetter, PRD section 3.1.
"""

from db import base_row, days_later, db, now, parse_ts, touch
from domain import COOLING_OFF_DAYS
from errors import fail
from services import common, requests as request_service


def create(rated_entity_id, fee_amount_cents, fee_structure, fee_payer_is_issuer, signed_at):
    if fee_amount_cents is None or int(fee_amount_cents) < 0:
        fail("ERR_FEE_AMOUNT_NEGATIVE")
    row = base_row()
    row.update(
        {
            "rated_entity_id": rated_entity_id,
            "fee_amount_cents": int(fee_amount_cents),
            "fee_structure": fee_structure,
            "fee_payer_is_issuer": bool(fee_payer_is_issuer),
            "signed_at": parse_ts(signed_at),
            "cooling_off_end_at": None,
            "fee_credited_cents": 0,
            "fee_reversed_cents": 0,
            "status": "DRAFT",
        }
    )
    db.engagement_letters[row["id"]] = row
    return row


def submit(row):
    if row["status"] == "TERMINATED":
        fail("ERR_ENGAGEMENT_ALREADY_TERMINAL")
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    # PRD section 3.1 names exactly one submit precondition beyond the
    # TERMINATED guard and the DRAFT state guard: the letter is submitted for
    # signature.  The PRD attaches no ordering constraint between signed_at
    # and the logical clock, so none is enforced here.
    signed = row["signed_at"] or now()
    row["status"] = "SIGNED"
    row["cooling_off_end_at"] = days_later(signed, COOLING_OFF_DAYS)
    return touch(row)


def activate(row):
    if row["status"] == "TERMINATED":
        fail("ERR_ENGAGEMENT_ALREADY_TERMINAL")
    if row["status"] != "SIGNED":
        fail("ERR_ENGAGEMENT_NOT_SIGNED")
    cooling = row["cooling_off_end_at"]
    if cooling is None or cooling > now():
        fail("ERR_COOLING_OFF_ACTIVE")
    row["status"] = "ACTIVE"
    return touch(row)


def revert_to_draft(row):
    if row["status"] == "TERMINATED":
        fail("ERR_ENGAGEMENT_ALREADY_TERMINAL")
    # PRD §3.1: "the revert is refused with ERR_ENGAGEMENT_ALREADY_TERMINAL once
    # a RatingRequest exists under that engagement_letter_id".  This precondition
    # is checked first so that an ACTIVE letter carrying a request reports the
    # terminal-guard error rather than a bare non-SIGNED state.
    for request in db.rating_requests.values():
        if request["engagement_letter_id"] == row["id"]:
            fail("ERR_ENGAGEMENT_ALREADY_TERMINAL")
    if row["status"] != "SIGNED":
        fail("ERR_INVALID_STATE")
    row["status"] = "DRAFT"
    row["cooling_off_end_at"] = None
    return touch(row)


def terminate(row):
    """Terminate an ACTIVE letter and run the depth-four cascade."""
    if row["status"] != "ACTIVE":
        fail("ERR_ENGAGEMENT_NOT_ACTIVE")

    row["status"] = "TERMINATED"
    # PRD §3.1: "fee_reversed_cents is set equal to fee_credited_cents" — the
    # credited total itself is not restated by the PRD, so it is left as-is.
    row["fee_reversed_cents"] = int(row["fee_credited_cents"])
    touch(row)

    affected_entities = set()
    for request in list(db.rating_requests.values()):
        if request["engagement_letter_id"] != row["id"]:
            continue
        affected_entities.add(request["rated_entity_id"])
        if request["request_status"] == "PUBLISHED":
            continue
        cascade_withdraw(request)

    for entity_id in affected_entities:
        recompute_posture(db.rated_entities.get(entity_id))
    return row


def cascade_withdraw(request):
    """Hop 1..3 over one request plus the parallel committee branch."""
    request["request_status"] = "WITHDRAWN"
    request["allocated_fee_cents"] = 0
    touch(request)

    # Hop 1: every assignment on the request revokes.
    affected_leads = set()
    for assignment in db.team_assignments.values():
        if assignment["rating_request_id"] != request["id"]:
            continue
        if assignment["status"] not in ("PROPOSED", "SCREENED", "CONFIRMED"):
            continue
        assignment["status"] = "REVOKED"
        touch(assignment)
        affected_leads.add(assignment["lead_analyst_id"])
        common.COVERAGE.pop(assignment["id"], None)

    # Hop 2 and 3: lead credit and rotation eligibility recompute.
    for analyst_id in affected_leads:
        analyst = db.analysts.get(analyst_id)
        if analyst is not None:
            from services import calculations

            calculations.recompute_rotation(analyst, now())

    # Parallel branch: committees dissolve, their draft decisions withdraw.
    request_service.dissolve_committees_for_request(request["id"])
    return request


def recompute_posture(entity):
    if entity is None:
        return
    if entity.get("surveillance_posture") == "RESTRICTED":
        return
    return entity