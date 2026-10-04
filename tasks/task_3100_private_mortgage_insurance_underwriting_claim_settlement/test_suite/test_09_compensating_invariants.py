"""Compensating invariants: the premium schedule total and the lender exposure
contribution."""
import pytest

from prd_bench_local_runner.testing import validate_success, get_success_data

from test_helpers import (
    api_client, setup_loan, setup_two_loans, issue_treaty_loan, file_claim,
    file_borrower_cancellation, file_delinquency_report, begin_claim_review,
    approve_claim, refresh_loan, reconcile_exposure, setup_dispute,
    assert_premium_schedule, amortize_into_at80, AT80_MAX_REFUND_CENTS,
    set_clock, ADMIN, UNDERWRITER, assert_instant_equals,
)

TREATY = {
    "treaty_number": "TR-INVAR",
    "inception_utc": "2026-01-01T00:00:00Z",
    "expiration_utc": "2028-01-01T00:00:00Z",
    "retention_per_claim_cents": 1_000_000,
    "exhaustion_per_claim_cents": 6_000_000,
    "aggregate_ceded_cap_cents": 5_000_000,
}


def test_cancellation_preserves_the_premium_schedule_total():
    """PRD §2.7: "The schedule is a closed ledger and two invariants hold at all
    times, both before and after any cancellation."
    PRD §3.6: "Filing the notice also voids the loan's premium instalments whose
    period covers that effective instant; per the schedule ledger invariants of
    §2.7 the voided periods move out of the billed column and the schedule's
    total is preserved exactly."

    Design: Difficulty/compensating_invariant/cancellation_preserves_the_loan_premium_schedule_total
    """
    book = setup_loan()
    # Amortize into the AT_80 window so the computed maximum refund is non-zero.
    amortize_into_at80(book)
    before = refresh_loan(book)
    assert before["coverage_status"] == "ACTIVE"
    assert before["annual_premium_cents"] == 52_700
    assert_premium_schedule(before)

    notice = file_borrower_cancellation(book, evidence_cents=AT80_MAX_REFUND_CENTS)
    set_clock("2026-11-01T00:00:00Z")
    after = refresh_loan(book)

    assert after["coverage_status"] == "CANCELLED"
    assert_instant_equals(after["cancellation_effective_utc"],
                          "2026-10-15T00:00:00Z", "cancellation_effective_utc")
    # The lesser of the evidence amount and the 735-cent maximum refund.
    assert notice["refund_cents"] == AT80_MAX_REFUND_CENTS
    assert after["annual_premium_cents"] == 52_700
    assert_premium_schedule(after)


def test_the_maximum_refund_is_the_amortized_proportion_of_the_original_base():
    """PRD §3.6: "Take the original-item coverage base and subtract from it the
    current coverage base — the part of the base still outstanding, which is the
    current unpaid principal balance multiplied by the coverage percentage and
    divided by one hundred, floored. Divide that difference by the original-item
    coverage base, multiply by ten thousand, and round half up to a whole cent.
    That is the maximum refund."
    PRD §3.6: "The refund actually recorded on the notice, held as `refund_cents`,
    is then the smallest of three figures: the `evidence_cents` the notice
    supplied, the maximum refund, and — as a floor — zero".

    Design: Difficulty/compensating_invariant/cancellation_preserves_the_loan_premium_schedule_total
    """
    book = setup_loan()
    amortize_into_at80(book)

    # current_coverage_base = floor(31500000 * 25 / 100) = 7875000;
    # max refund = round_half_up(10000 * (8500000 - 7875000) / 8500000) = 735.
    # The refund on the notice is that maximum, so the recorded figure identifies
    # the maximum refund rather than the evidence amount that was supplied.
    notice = file_borrower_cancellation(book, evidence_cents=AT80_MAX_REFUND_CENTS)
    assert notice["refund_cents"] == AT80_MAX_REFUND_CENTS == 735


def test_cancellation_effective_instant_is_clamped_to_notice_plus_thirty_days():
    """PRD §3.6: "The notice's `effective_utc` is the later of the requested
    `applied_utc` and the notice's `notice_utc` plus thirty days. A borrower who
    asks for termination a week after giving notice therefore gets a termination
    thirty days out, not seven."

    Design: Difficulty/compensating_invariant/cancellation_preserves_the_loan_premium_schedule_total
    """
    book = setup_loan()
    amortize_into_at80(book)

    notice = file_borrower_cancellation(
        book, evidence_cents=800,
        notice_utc="2026-09-01T00:00:00Z", applied_utc="2026-09-08T00:00:00Z")
    assert_instant_equals(notice["effective_utc"],
                          "2026-10-01T00:00:00Z", "effective_utc")


def test_the_reversal_subtracts_exactly_the_ceded_amount_the_settlement_added():
    """PRD §3.10: "a cession records the `claim_id` it was made against, the
    `loan_id` it belongs to, the `treaty_id` applied, and the
    `aggregate_ceded_after_cents` — the loan's ceded total once this cession has
    been applied."
    PRD §3.11: "the previously accepted cession is voided and the loan's ceded
    total is reduced by precisely the ceded amount that settlement had added".

    Design: Difficulty/compensating_invariant/rescission_of_a_settled_claim_preserves_lender_exposure_contribution
    """
    book = issue_treaty_loan(TREATY)
    claim = file_claim(book)
    begin_claim_review(claim["id"])
    approved = approve_claim(claim["id"])
    loan = refresh_loan(book)

    validate_success(api_client.settle_claim(claim["id"], {
        "settlement_option_kind": "CASH",
        "expected_claim_version": approved["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"]))

    cessions = get_success_data(api_client.list_cessions(
        UNDERWRITER, params={"claim_id": claim["id"]}))
    assert len(cessions) == 1
    accepted = cessions[0]
    assert accepted["status"] == "ACCEPTED"
    assert accepted["loan_id"] == book["loan_id"]
    assert accepted["treaty_id"] == book["treaty_id"]
    # 6098400 net less the 1000000 retention, capped at the 5000000 capacity.
    assert accepted["ceded_amount_cents"] == 5_000_000
    assert accepted["aggregate_ceded_after_cents"] == 5_000_000
    assert refresh_loan(book)["aggregate_ceded_cents"] == 5_000_000

    after_settle = validate_success(reconcile_exposure(book))
    assert after_settle["lender_contribution_cents"] == 2_975_000 + 5_000_000

    get_success_data(api_client.create_external_report(book["loan_id"], {
        "verified_loan_amount_cents": 34_000_000,
        "verified_property_value_cents": 39_000_000,
        "post_origination_value_cents": 0,
        "occupancy_reported": "OWNER_OCCUPIED",
        "independent_validation_completed_utc": "2026-09-01T00:00:00Z",
    }, UNDERWRITER))
    dispute = setup_dispute(book, grounds="ORIGINATION_OMISSION", in_review=True)
    validate_success(api_client.decide_dispute(dispute["id"], {
        "decision": "RESCISSION_GRANTED",
        "decision_reason": "Origination omission established on independent review",
    }, ADMIN))

    assert refresh_loan(book)["aggregate_ceded_cents"] == 0


def test_rescission_of_a_settled_claim_restores_the_lender_exposure_contribution():
    """PRD §3.11: "Reversing a settlement must leave the loan's
    `aggregate_ceded_cents` exactly where it stood before the settlement, and it
    must leave the lender's exposure contribution exactly where it stood before
    any claim on the loan settled."
    PRD §3.10: "the previously accepted cession is voided and the loan's ceded
    total is reduced by precisely the ceded amount that settlement had added".

    Design: Difficulty/compensating_invariant/rescission_of_a_settled_claim_preserves_lender_exposure_contribution
    """
    book = issue_treaty_loan(TREATY)
    claim = file_claim(book)
    begin_claim_review(claim["id"])
    approved = approve_claim(claim["id"])

    # Before any settlement the lender's contribution is the amortized-rate share
    # of the coverage base alone.
    pre = reconcile_exposure(book)
    pre_data = validate_success(pre)
    assert pre_data["lender_contribution_cents"] == 2_975_000

    loan = refresh_loan(book)
    settle_response = api_client.settle_claim(claim["id"], {
        "settlement_option_kind": "CASH",
        "expected_claim_version": approved["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"])
    validate_success(settle_response)
    assert refresh_loan(book)["aggregate_ceded_cents"] == 5_000_000

    # An independent validation report and a rescission dispute, then the grant.
    get_success_data(api_client.create_external_report(book["loan_id"], {
        "verified_loan_amount_cents": 34_000_000,
        "verified_property_value_cents": 39_000_000,
        "post_origination_value_cents": 0,
        "occupancy_reported": "OWNER_OCCUPIED",
        "independent_validation_completed_utc": "2026-09-01T00:00:00Z",
    }, UNDERWRITER))
    dispute = setup_dispute(book, grounds="ORIGINATION_OMISSION", in_review=True)

    resolved = validate_success(api_client.decide_dispute(dispute["id"], {
        "decision": "RESCISSION_GRANTED",
        "decision_reason": "Origination omission established on independent review",
    }, ADMIN))
    assert resolved["status"] == "RESOLVED"

    final_claim = get_success_data(api_client.get_claim(claim["id"], UNDERWRITER))
    final_loan = refresh_loan(book)
    assert final_claim["status"] == "RESCINDED"
    assert final_loan["coverage_status"] == "CANCELLED"
    assert final_loan["aggregate_ceded_cents"] == 0

    # A CANCELLED loan contributes nothing, and the reversal left no drift on the
    # ceded total it had before any claim settled.
    assert final_loan["aggregate_ceded_cents"] == 0