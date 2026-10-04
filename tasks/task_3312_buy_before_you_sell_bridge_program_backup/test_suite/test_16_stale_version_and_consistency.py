"""Stale-version (optimistic concurrency) rejection and immediate consistency (PRD 2.9, 3.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, setup_funded_program, drawn_advance, get_loan, get_program,
    record_carrying_cost, make_homeowner_headers, TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]


def test_repayment_with_a_stale_loan_version_is_refused(api):
    """PRD section 2.9: "posting a repayment against an interim loan, which requires
    `expected_interim_loan_version`"

    PRD section 2.9: "If the supplied value does not equal the parent's current `version`,
    the request is refused with `ERR_STALE_VERSION` and an HTTP status of 412."

    Design: Corner/validations/stale_version_on_repayment_returns_412
    """
    reset_clock()
    sc = setup_funded_program(
        income_cents=30_000_000,
        departing={"address": "23 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    # First draw moves the loan to DRAWN.
    drawn_advance(sc["program"]["id"], sc["loan"]["id"], "DOWN_PAYMENT", 2_000_000)
    observed = get_loan(sc["loan"]["id"])
    stale_version = observed["version"]

    # A second disbursement advances the loan version again.
    drawn_advance(sc["program"]["id"], sc["loan"]["id"], "CARRYING_COST", 500_000)
    assert get_loan(sc["loan"]["id"])["version"] > stale_version

    res = api.post_repayment(
        sc["loan"]["id"],
        {"amount_cents": 1_000_000, "expected_interim_loan_version": stale_version},
        make_homeowner_headers(sc["homeowner"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
    assert get_loan(sc["loan"]["id"])["status"] == "DRAWN", "the loan is untouched by the refusal"


def test_repayment_with_the_current_loan_version_is_accepted(api):
    """PRD section 2.9: "The offered version is the client's claim about the parent's
    `version` at the moment it read the record, and a mismatch means that claim is no longer
    true."

    PRD section 3.5: "A repayment carries an `amount_cents` and, because it moves a balance
    another writer may have just changed, an `expected_interim_loan_version` that must equal
    the loan's current `version`"

    Design: Corner/validations/stale_version_on_repayment_returns_412
    """
    reset_clock()
    sc = setup_funded_program(
        income_cents=30_000_000,
        departing={"address": "23 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    drawn_advance(sc["program"]["id"], sc["loan"]["id"], "DOWN_PAYMENT", 2_000_000)
    current = get_loan(sc["loan"]["id"])

    paid = validate_success(api.post_repayment(
        sc["loan"]["id"],
        {"amount_cents": 100_000, "expected_interim_loan_version": current["version"]},
        make_homeowner_headers(sc["homeowner"]["id"])), 200)
    assert paid["status"] == "REPAYING"


def test_recording_a_carrying_cost_is_immediately_visible_on_the_program(api):
    """PRD section 3.3: "it carries two counters that are derived rather than supplied:
    `outstanding_carrying_cost_cents`, which is the sum of the unpaid carrying costs attached
    to the program and is recomputed on every change to any of them"

    PRD section 3.9: "Every time a carrying cost is created or repaid, the program's
    `outstanding_carrying_cost_cents` is recomputed"

    Design: Corner/consistency_model/immediate_consistency_of_carrying_cost
    """
    reset_clock()
    sc = setup_funded_program(
        income_cents=30_000_000,
        departing={"address": "51 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    record_carrying_cost(sc["program"]["id"], "DEPARTING_TAX", 500_000,
                         due_date="2026-10-01T00:00:00Z")
    program = get_program(sc["program"]["id"])
    assert program["outstanding_carrying_cost_cents"] == 500_000, (
        "the write is visible on the very next read, with no reconciliation step"
    )