"""Rating requests: intake, screening, fee allocation and withdrawal.

SCAFFOLD state_machines -> RatingRequest, PRD section 3.2.
"""

from db import base_row, db, now, touch
from errors import fail
from services import calculations, common


def create(engagement_letter_id, rated_entity_id, instrument_type, instrument_notional_cents, requested_rating_scale):
    row = base_row()
    row.update(
        {
            "engagement_letter_id": engagement_letter_id,
            "rated_entity_id": rated_entity_id,
            "instrument_type": instrument_type,
            "instrument_notional_cents": int(instrument_notional_cents or 0),
            "requested_rating_scale": requested_rating_scale,
            "received_at": now(),
            "allocated_fee_cents": 0,
            "request_status": "SUBMITTED",
        }
    )
    db.rating_requests[row["id"]] = row
    return row


def open_screening(row):
    if row["request_status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "The request must be SUBMITTED to open screening.")

    engagement = db.engagement_letters.get(row["engagement_letter_id"])
    if engagement is None:
        fail("ERR_ENGAGEMENT_NOT_FOUND")
    if engagement["status"] != "ACTIVE":
        fail("ERR_ENGAGEMENT_NOT_ACTIVE")

    entity = db.rated_entities.get(row["rated_entity_id"])
    if entity is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    methodology = common.entity_pinned_methodology(entity)
    if methodology["status"] != "PUBLISHED":
        fail("ERR_METHODOLOGY_NOT_PUBLISHED")

    allocated = calculations.allocate_fee(engagement, row)
    already_credited = calculations.credited_total(engagement["id"])
    if already_credited + allocated > int(engagement["fee_amount_cents"] or 0):
        fail("ERR_FEE_ALLOCATION_EXCEEDS_ENGAGEMENT")

    row["allocated_fee_cents"] = allocated
    row["request_status"] = "SCREENING"
    touch(row)

    engagement["fee_credited_cents"] = already_credited + allocated
    touch(engagement)
    return row


def return_to_submitted(row):
    if row["request_status"] != "SCREENING":
        fail("ERR_REQUEST_NOT_SCREENING")

    engagement = db.engagement_letters.get(row["engagement_letter_id"])
    allocated = int(row["allocated_fee_cents"] or 0)
    if engagement is not None:
        engagement["fee_reversed_cents"] = int(engagement["fee_reversed_cents"] or 0) + allocated
        engagement["fee_credited_cents"] = max(
            0, int(engagement["fee_credited_cents"] or 0) - allocated
        )
        touch(engagement)

    row["allocated_fee_cents"] = 0
    row["request_status"] = "SUBMITTED"
    touch(row)
    return row


def confirmed_clear_assignment(rating_request_id):
    rows = [
        a
        for a in db.team_assignments.values()
        if a["rating_request_id"] == rating_request_id and a["status"] == "CONFIRMED"
    ]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return rows[0] if rows else None


def confirm_team(row):
    if row["request_status"] != "SCREENING":
        fail("ERR_INVALID_STATE", "The request must be SCREENING to confirm its team.")

    assignment = confirmed_clear_assignment(row["id"])
    if assignment is None:
        fail("ERR_TEAM_NOT_CONFIRMED")
    if assignment["conflict_status"] != "CLEAR":
        fail("ERR_CONFLICT_NOT_CLEARED")

    row["request_status"] = "TEAM_CONFIRMED"
    touch(row)
    return row


def withdraw(row):
    if row["request_status"] not in ("SUBMITTED", "SCREENING", "TEAM_CONFIRMED"):
        fail("ERR_REQUEST_NOT_WITHDRAWABLE")

    engagement = db.engagement_letters.get(row["engagement_letter_id"])
    allocated = int(row["allocated_fee_cents"] or 0)
    if engagement is not None:
        engagement["fee_reversed_cents"] = int(engagement["fee_reversed_cents"] or 0) + allocated
        engagement["fee_credited_cents"] = max(
            0, int(engagement["fee_credited_cents"] or 0) - allocated
        )
        touch(engagement)

    row["allocated_fee_cents"] = 0
    row["request_status"] = "WITHDRAWN"
    touch(row)

    affected_leads = set()
    for assignment in db.team_assignments.values():
        if assignment["rating_request_id"] != row["id"]:
            continue
        if assignment["status"] in ("PROPOSED", "SCREENED", "CONFIRMED"):
            assignment["status"] = "REVOKED"
            touch(assignment)
            affected_leads.add(assignment["lead_analyst_id"])
            common.COVERAGE.pop(assignment["id"], None)

    for analyst_id in affected_leads:
        analyst = db.analysts.get(analyst_id)
        if analyst is not None:
            calculations.recompute_rotation(analyst, now())

    dissolve_committees_for_request(row["id"])
    return row


def dissolve_committees_for_request(rating_request_id):
    """CONVENED|IN_SESSION committees dissolve; their DRAFT decisions withdraw."""
    for committee in db.rating_committees.values():
        if committee["rating_request_id"] != rating_request_id:
            continue
        if committee["committee_status"] not in ("CONVENED", "IN_SESSION"):
            continue
        committee["committee_status"] = "DISSOLVED"
        touch(committee)
    for decision in db.rating_decisions.values():
        if decision["rating_request_id"] != rating_request_id:
            continue
        if decision["decision_status"] == "DRAFT":
            decision["decision_status"] = "WITHDRAWN"
            touch(decision)


def advance_after_redecision(row):
    row["request_status"] = "COMMITTEE_DECIDED"
    touch(row)
    return row


def mark_appealed(row):
    row["request_status"] = "APPEALED"
    touch(row)
    return row


def bump_occ(row):
    """Advance the request's OCC version (PRD section 2.7)."""
    from db import bump_version

    row["updated_at"] = now()
    return bump_version(row)