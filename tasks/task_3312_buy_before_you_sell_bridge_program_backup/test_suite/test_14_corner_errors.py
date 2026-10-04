"""Refusal conditions from the error catalogue (PRD 3.1, 3.6, 3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, create_departing_and_new, make_property,
    setup_funded_program, drawn_advance, record_carrying_cost, get_loan,
    go_live_departing, draft_listing, complete_repairs, setup_referral,
    make_homeowner_headers, TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]


def test_final_repayment_is_blocked_while_a_carrying_cost_is_unpaid(api):
    """PRD section 3.5: "A final repayment may not be posted while the program's
    `outstanding_carrying_cost_cents` is anything but zero — the carrying costs must be
    cleared first, and the attempt is refused with `ERR_CARRYING_COST_UNPAID`."

    Design: Corner/errors/carrying_cost_unpaid_blocks_loan_settlement
    """
    reset_clock()
    sc = setup_funded_program(
        income_cents=30_000_000,
        departing={"address": "39 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    drawn_advance(sc["program"]["id"], sc["loan"]["id"], "DOWN_PAYMENT", 2_000_000)
    record_carrying_cost(sc["program"]["id"], "DEPARTING_TAX", 500_000,
                         due_date="2026-10-01T00:00:00Z")
    loan = get_loan(sc["loan"]["id"])
    assert loan["status"] == "DRAWN"
    full_balance = loan["outstanding_principal_cents"] + loan["accrued_interest_cents"]

    res = api.post_repayment(
        loan["id"],
        {"amount_cents": full_balance, "expected_interim_loan_version": loan["version"]},
        make_homeowner_headers(sc["homeowner"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CARRYING_COST_UNPAID.value, expected_status=422)
    assert get_loan(loan["id"])["status"] == "DRAWN", "the loan was not settled"


def test_a_partial_repayment_leaves_the_carrying_cost_block_untouched(api):
    """PRD section 3.5: "A payment strictly smaller than the sum of the loan's
    `outstanding_principal_cents` and `accrued_interest_cents` reduces principal, recomputes
    interest and puts the loan in `REPAYING`."

    Design: Corner/errors/carrying_cost_unpaid_blocks_loan_settlement
    """
    reset_clock()
    sc = setup_funded_program(
        income_cents=30_000_000,
        departing={"address": "39 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    drawn_advance(sc["program"]["id"], sc["loan"]["id"], "DOWN_PAYMENT", 2_000_000)
    record_carrying_cost(sc["program"]["id"], "DEPARTING_TAX", 500_000,
                         due_date="2026-10-01T00:00:00Z")
    loan = get_loan(sc["loan"]["id"])

    paid = validate_success(api.post_repayment(
        loan["id"],
        {"amount_cents": 100_000, "expected_interim_loan_version": loan["version"]},
        make_homeowner_headers(sc["homeowner"]["id"])), 200)
    assert paid["status"] == "REPAYING", "a partial repayment is not a settlement attempt"


def test_qualification_cannot_pair_a_household_with_a_new_kind_departing_slot(api):
    """PRD section 3.2: "Both referenced properties must belong to the household named in the
    record"

    PRD section 3.11: "the home being counted for equity and put up for marketing must be a
    `DEPARTING` property, and the home being purchased must be a `NEW` one."

    Design: Corner/errors/property_kind_mismatch_rejected
    """
    reset_clock()
    h = validate_success(api.create_homeowner(
        {"full_name": "Err H2", "email": "err.h2@x.com", "credit_score": 700,
         "household_income_cents": 30_000_000}, COORD), 201)
    make_property(h["id"], "DEPARTING", "41 Def Way",
                        appraised_value_cents=60_000_000, mortgage_payoff_cents=30_000_000)
    new = make_property(h["id"], "NEW", "42 Def Way")

    # The departing slot is pointed at the NEW-kind property.
    res = api.create_qualification(
        {"homeowner_id": h["id"], "departing_property_id": new["id"],
         "new_property_id": new["id"], "target_purchase_price_cents": 30_000_000,
         "variant_used": "CONSERVATIVE"}, COORD)
    validate_error(res, ApiErrorId.ERR_PROPERTY_KIND_MISMATCH.value, expected_status=422)


def test_closing_a_sale_without_a_recorded_offer_is_refused(api):
    """PRD section 3.6: "Closing the sale is a distinct step and requires that the listing's
    `offer_count` is at least one and the property is `UNDER_CONTRACT`; a close attempted
    without a recorded offer is refused with `ERR_LISTING_OFFER_REQUIRED`."

    Design: Corner/errors/listing_offer_required_for_close_sale
    """
    reset_clock()
    sc = setup_funded_program(
        variant="OPTIMISTIC", income_cents=30_000_000,
        departing={"address": "43 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    live = go_live_departing(sc)["listing"]
    assert live["offer_count"] == 0

    res = api.close_sale_listing(live["id"], COORD)
    validate_error(res, ApiErrorId.ERR_LISTING_OFFER_REQUIRED.value, expected_status=422)


def test_recording_an_offer_under_contract_allows_the_sale_to_close(api):
    """PRD section 3.6: "Doing so raises the listing's `offer_count` by one, sets the
    property's `listing_status` to `UNDER_CONTRACT`, and — importantly for the guarantee —
    extends the linked backup offer if that offer is currently `ISSUED`"

    Design: Corner/errors/listing_offer_required_for_close_sale
    """
    reset_clock()
    sc = setup_funded_program(
        variant="OPTIMISTIC", income_cents=30_000_000,
        departing={"address": "43 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    live = go_live_departing(sc)["listing"]
    under = validate_success(api.under_contract_listing(live["id"], COORD), 200)
    assert under["offer_count"] == 1
    prop = validate_success(api.get_property(sc["departing"]["id"], COORD), 200)
    assert prop["listing_status"] == "UNDER_CONTRACT"

    closed = validate_success(api.close_sale_listing(live["id"], COORD), 200)
    assert closed["status"] == "CLOSED"