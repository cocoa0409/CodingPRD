"""Initial states and transitions with no declared outgoing arc (PRD 3.6, 3.9, 2.11)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, draft_listing,
    TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]


def test_a_freshly_drafted_listing_begins_in_draft(api):
    """PRD section 3.6: "A listing is drafted against the `departing_property_id` and a
    `bridge_program_id` with a `list_price_cents`, opening `DRAFT` with a
    `marketing_status` of `NOT_STARTED`."

    Design: Corner/state_machines/listing_initial_state_is_draft
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "7 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)

    listing = draft_listing(sc["departing"]["id"], bp["id"], list_price_cents=44_000_000)
    assert listing["status"] == "DRAFT"
    assert listing["marketing_status"] == "NOT_STARTED"
    assert listing["offer_count"] == 0


def test_exercising_a_drafted_backup_offer_is_a_state_error(api):
    """PRD section 3.9: "A coordinator exercises a `BackupOffer` that is `ISSUED` or
    `EXTENDED`"

    PRD section 2.11: "a resource that is not in a state from which the requested transition
    is declared is refused with `ERR_INVALID_STATE` before any economic check runs"

    Design: Corner/state_machines/backup_offer_exercise_from_draft_returns_invalid_state
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "9 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)

    offer = validate_success(api.create_backup_offer(
        {"departing_property_id": sc["departing"]["id"], "bridge_program_id": bp["id"],
         "offer_price_cents": 61_000_000, "window_days": 30,
         "window_start": "2026-09-01T00:00:00Z"}, COORD), 201)
    assert offer["status"] == "DRAFT"

    res = api.exercise_backup_offer(
        offer["id"], {"expected_backup_offer_version": offer["version"]}, COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = validate_success(api.get_backup_offer(offer["id"], COORD), 200)
    assert after["status"] == "DRAFT", "a drafted offer cannot be exercised"