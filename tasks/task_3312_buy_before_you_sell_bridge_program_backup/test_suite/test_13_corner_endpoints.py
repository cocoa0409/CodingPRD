"""Response envelope, synthesized settlements and the settlement rollup (PRD 2.2, 3.9, 3.11)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, assert_disbursement,
    reset_clock, setup_funded_program, drawn_advance, record_settlement, get_loan,
    create_homeowner_payload, TEST_USERS, is_iso8601_timestamp,
)

COORD = TEST_USERS["coordinator_headers"]


def test_successful_create_carries_the_standard_envelope(api):
    """PRD section 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."

    PRD section 2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/endpoints/success_envelope_carries_meta_and_object_type
    """
    reset_clock()
    res = api.create_homeowner(
        create_homeowner_payload(full_name="Env H", email="env.h@x.com"), COORD)
    assert res.status_code == 201
    body = res.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_"), "request ids start with req_"
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert isinstance(body["data"], dict)
    assert body["data"]["id"]


def _program_with_drawn_down_payment():
    sc = setup_funded_program(
        variant="CONSERVATIVE", income_cents=30_000_000,
        departing={"address": "35 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    drawn_advance(sc["program"]["id"], sc["loan"]["id"], "DOWN_PAYMENT", 8_000_000)
    loan = get_loan(sc["loan"]["id"])
    assert loan["outstanding_principal_cents"] == 8_000_000, "Setup failed: draw not applied"
    sc["loan"] = loan
    return sc


def test_exercising_a_backup_offer_synthesizes_a_resale_settlement(api):
    """PRD section 3.9: "A successful exercise sets the property's `listing_status` to
    `SOLD_TO_PROGRAM` and its `program_inventory_flag` to true, pauses the linked listing —
    moving it to `PAUSED` and its `marketing_status` to `STOPPED` — stamps the offer's
    `exercised_at` from the logical clock, and records a settlement entry of kind `RESALE`."

    Design: Corner/endpoints/cascade_created_disbursement_discoverable_by_filter
    """
    from test_helpers import (build_qualified_household, create_qualification,
                              approve_qualification, enroll_bridge_program, fund_program,
                              go_live_departing, draft_backup_offer, issue_backup_offer)
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "33 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="OPTIMISTIC", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program, loan = fund_program(bp["id"])
    sc["program"], sc["loan"] = program, loan
    go_live_departing(sc)
    # A coordinator other than the exerciser issues the offer: PRD 2.1 forbids the
    # issuing coordinator from exercising it (ERR_SOD_BACKUP_APPROVER).
    offer = draft_backup_offer(sc, offer_price_cents=61_000_000, as_user_id="coord-issuer-1")
    issued = issue_backup_offer(offer["id"], as_user_id="coord-issuer-1")

    exercised = validate_success(api.exercise_backup_offer(
        offer["id"], {"expected_backup_offer_version": issued["version"]}, COORD), 200)
    assert exercised["status"] == "EXERCISED"

    prop = validate_success(api.get_property(sc["departing"]["id"], COORD), 200)
    assert prop["listing_status"] == "SOLD_TO_PROGRAM"

    res = api.list_disbursements(COORD, params={"bridge_program_id": program["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1, "the exercise synthesized exactly one settlement entry"
    assert data[0]["source_kind"] == "RESALE"


def test_resale_settlement_applies_the_amount_to_the_loan_principal(api):
    """PRD section 3.9: "once applied it is split three ways, into the portion
    `applied_to_principal_cents`, the portion `applied_to_interest_cents`, and the
    `remainder_cents` left once principal and interest are satisfied."

    Design: Corner/endpoints/resale_disbursement_applies_principal_to_loan
    """
    reset_clock()
    sc = _program_with_drawn_down_payment()
    settlement = record_settlement(sc["program"]["id"], "RESALE", 3_000_000)
    assert_disbursement(settlement)
    assert settlement["applied_to_principal_cents"] == 3_000_000

    loan = get_loan(sc["loan"]["id"])
    assert loan["outstanding_principal_cents"] == 5_000_000, "8000000 drawn minus 3000000 applied"


def test_settlement_summary_rolls_up_applied_principal_and_entry_count(api):
    """PRD section 3.11: "The platform also exposes an aggregate read across all programs,
    reporting `total_applied_to_principal_cents`, `total_applied_to_interest_cents`,
    `remainder_cents` and `entry_count`, optionally scoped to a single program."

    Design: Corner/endpoints/disbursements_summary_aggregates_settlements
    """
    reset_clock()
    sc = _program_with_drawn_down_payment()
    record_settlement(sc["program"]["id"], "RESALE", 1_000_000)

    summary = validate_success(api.get_disbursements_summary(
        COORD, params={"bridge_program_id": sc["program"]["id"]}), 200)
    assert summary["total_applied_to_principal_cents"] == 1_000_000
    assert summary["entry_count"] == 1