"""Boundary precision on the draw headroom and the empty carrying-cost set (PRD 3.4, 3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, setup_funded_program, get_loan, get_program, program_summary,
    create_advance, approve_advance, TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
UW = TEST_USERS["underwriter_headers"]


def _headroom_scenario():
    """A funded program whose capacity-derived principal reserves the 150-bps fee."""
    sc = setup_funded_program(
        variant="OPTIMISTIC", interest_rate_bps=800,
        income_cents=30_000_000,
        departing={"address": "25 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "26 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    return sc


def test_advance_at_exactly_the_headroom_is_accepted(api):
    """PRD section 3.4: "The remaining drawable amount is the loan's `principal_cents` minus
    its `outstanding_principal_cents` minus that debit."

    PRD section 3.4: "An advance is acceptable when its `amount_cents` is greater than zero
    and is at most that remaining amount; the boundary is inclusive, so an advance for
    exactly the remaining amount is accepted."

    Design: Difficulty/boundary_precision_check/advance_headroom_exact_boundary
    """
    reset_clock()
    sc = _headroom_scenario()
    loan = sc["loan"]
    # capacity 40000000 * 9000 // 10000 = 36000000; fee debit 36000000 * 150 // 10000 = 540000
    assert loan["principal_cents"] == 36_000_000
    headroom = loan["principal_cents"] - loan["outstanding_principal_cents"] - (
        loan["principal_cents"] * 150 // 10000
    )
    assert headroom == 35_460_000

    advance = create_advance(sc["program"]["id"], loan["id"], "CARRYING_COST", headroom)
    approved = validate_success(api.approve_bridge_advance(
        advance["id"], UW), 200)
    assert approved["status"] == "APPROVED", "an advance at exactly the headroom is accepted"
    assert approved["amount_cents"] == headroom


def test_advance_one_cent_above_the_headroom_is_refused(api):
    """PRD section 3.4: "A request beyond it is refused with `ERR_NO_CAPACITY`."

    PRD section 3.4: "The same ceiling governs the disbursement step and the disbursement
    of repair funds."

    Design: Difficulty/boundary_precision_check/advance_headroom_exact_boundary
    """
    reset_clock()
    sc = _headroom_scenario()
    loan = sc["loan"]
    headroom = loan["principal_cents"] - loan["outstanding_principal_cents"] - (
        loan["principal_cents"] * 150 // 10000
    )

    # The at-boundary advance is allowed to exist untouched; the over-boundary one is refused.
    at_boundary = create_advance(sc["program"]["id"], loan["id"], "CARRYING_COST", headroom)
    validate_success(api.approve_bridge_advance(at_boundary["id"], UW), 200)

    # PRD section 3.4: "A request beyond it is refused with `ERR_NO_CAPACITY`."  The
    # headroom ceiling governs the request itself, so the refusal lands on the advance
    # request rather than on a later approval.
    res = api.create_bridge_advance(
        {"bridge_program_id": sc["program"]["id"], "interim_loan_id": loan["id"],
         "purpose": "CARRYING_COST", "amount_cents": headroom + 1}, COORD)
    validate_error(res, ApiErrorId.ERR_NO_CAPACITY.value, expected_status=422)


def test_empty_carrying_cost_set_reports_zero_outstanding(api):
    """PRD section 3.9: "Whichever way it is computed, only the buckets whose carrying costs
    are still unpaid contribute to the `outstanding_carrying_cost_cents` a program reports."

    Design: Difficulty/boundary_precision_check/empty_carrying_cost_set_yields_zero
    """
    reset_clock()
    sc = setup_funded_program(
        income_cents=30_000_000,
        departing={"address": "26 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    summary = program_summary(sc["program"]["id"])
    assert summary["outstanding_carrying_cost_cents"] == 0, (
        "no carrying costs exist, so nothing is outstanding"
    )


def test_empty_carrying_cost_set_yields_zero_true_cost(api):
    """PRD section 3.9: "The true cost counts what has actually happened: the program's
    `outstanding_carrying_cost_cents` plus interest computed on the loan's
    `outstanding_principal_cents` at the loan's rate over the whole calendar months that
    have actually elapsed between the loan's origination and the logical clock."

    Design: Difficulty/boundary_precision_check/empty_carrying_cost_set_yields_zero
    """
    reset_clock()
    sc = setup_funded_program(
        income_cents=30_000_000,
        departing={"address": "27 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    loan = get_loan(sc["loan"]["id"])
    assert loan["outstanding_principal_cents"] == 0, "no draws have been made"
    summary = program_summary(sc["program"]["id"])
    assert summary["true_cost_cents"] == 0, "no outstanding principal and no carrying costs"