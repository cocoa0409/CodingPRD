"""Combinatorial formulas: the tiered transfer late fee and per-line rounding
order of the sanction assessment."""
import pytest

from test_helpers import (
    ADMIN,
    QA_CREATOR,
    QA_JUDGE,
    QA_SETTLER,
    add_finding,
    api_client,
    create_active_member,
    create_transfer_payload,
    issue_review,
    list_sanctions,
    make_qa_auditor_headers,
    member_rep,
    open_review,
    register_loan,
    set_clock,
    settle_review,
    setup_settled_review,
    setup_two_member_pair,
    validate_success,
)


class TestLateFeeMarginalTiers:
    def test_twenty_days_late_spans_two_tiers_marginaly(self, api):
        """PRD §3.4: "`late_fee_cents` bills those late days marginally across
        three tiers — each late day is billed at exactly one tier's rate: days one
        through fifteen of lateness at 2,500 cents per day, days sixteen through
        thirty at 5,000 cents per day, and every day from the thirty-first onward
        at 10,000 cents per day."
        PRD §3.4: "the logical clock and the `effective_date` are each truncated
        to their calendar day, the difference in days is taken, the reporting
        grace window of ten days is subtracted, and the result is floored at zero."

        Design: Difficulty/combinatorial_formula/late_fee_marginal_tiers_mode_a
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=100000000)

        # Clock 2026-02-24, effective 2026-02-04: 20 calendar days apart,
        # minus the ten-day grace window -> 10 days late, all inside tier 1.
        set_clock("2026-02-24T00:00:00Z")
        tr = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan["id"], b["id"], loan["version"],
                    transfer_type="BENEFICIAL",
                    effective_date="2026-02-04T00:00:00Z",
                    idempotency_key="k-fee-20",
                ),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )
        assert tr["days_late"] == 10, tr
        # 10 x 2500: every late day sits in the first tier.
        assert tr["late_fee_cents"] == 25000, tr

    def test_fee_spans_tier_one_and_tier_two_marginaly(self, api):
        """PRD §3.4: "days one through fifteen of lateness at 2,500 cents per
        day, days sixteen through thirty at 5,000 cents per day, and every day
        from the thirty-first onward at 10,000 cents per day."

        Design: Difficulty/combinatorial_formula/late_fee_marginal_tiers_mode_a
        """
        set_clock("2026-01-05T00:00:00Z")
        a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
        loan = register_loan(a["id"], loan_amount_cents=100000000)

        # Clock 2026-03-12, effective 2026-02-10: 30 calendar days apart,
        # minus the ten-day window -> 20 days late; 15x2500 + 5x5000 = 62500.
        set_clock("2026-03-12T00:00:00Z")
        tr = validate_success(
            api.create_transfer(
                create_transfer_payload(
                    loan["id"], b["id"], loan["version"],
                    transfer_type="BENEFICIAL",
                    effective_date="2026-02-10T00:00:00Z",
                    idempotency_key="k-fee-62500",
                ),
                member_rep(a["id"]),
            ),
            expected_status=201,
        )
        assert tr["days_late"] == 20, tr
        # Marginal tiers: NOT 20x5000 and NOT 20x2500.
        assert tr["late_fee_cents"] == 62500, tr


class TestSanctionRoundPerLineThenSum:
    def _delta_with_three_loans_and_proven_prior(self, api):
        """Member D with 3 loans and one PAID MINOR sanction (a proven prior)."""
        set_clock("2026-01-05T00:00:00Z")
        d = create_active_member(org_id="1000002", member_type="ORIGINATOR")
        loans = [register_loan(d["id"], loan_amount_cents=40000000) for _ in range(3)]

        # First review: one MAJOR finding, settled at abatement 1.0, then paid.
        review1 = open_review(d["id"], period_start="2026-01-01T00:00:00Z",
                              period_end="2026-03-31T00:00:00Z")
        add_finding(review1["id"], loans[0]["id"], field_name="PROPERTY_STATE",
                    expected_value="TX", actual_value="TN", severity="MAJOR")
        issue_review(review1["id"])
        settle_review(review1["id"], payload={"abatement_factor": 1.0})
        sanc1 = list_sanctions(review_id=review1["id"])[0]
        validate_success(
            api.pay_sanction(sanc1["id"], member_rep(d["id"]))
        )
        return d, loans

    def test_repeat_offender_abated_lines_round_individually_before_summing(self, api):
        """PRD §3.5: "each finding on the review, taken in creation order,
        contributes one line whose base amount depends on severity — 500,000 cents
        for `CRITICAL`, 100,000 cents for `MAJOR`, 25,005 cents for `MINOR` —
        multiplied by the repeat multiplier and by the abatement factor, and
        **each line is rounded half-up to whole cents individually before any
        summation**."
        PRD §3.5: "three minor findings under repeat-offender abatement of 0.9
        produce 33,756.75 cents per line — rounded per line and summed that is
        101,271 cents, versus 101,270 under sum-then-round — and only the per-line
        order is compliant."

        Design: Difficulty/combinatorial_formula/sanction_per_line_round_then_sum_mode_b
        """
        d, loans = self._delta_with_three_loans_and_proven_prior(api)

        review2 = open_review(d["id"], period_start="2026-04-01T00:00:00Z",
                              period_end="2026-06-30T00:00:00Z")
        add_finding(review2["id"], loans[0]["id"], severity="MINOR",
                    expected_value="2026-01-05", actual_value="2026-01-07")
        add_finding(review2["id"], loans[1]["id"], severity="MINOR",
                    expected_value="2026-01-05", actual_value="2026-01-08")
        add_finding(review2["id"], loans[2]["id"], field_name="MIN", severity="MINOR",
                    expected_value="100000200000000012",
                    actual_value="100000200000000021")
        issue_review(review2["id"])
        settle_review(review2["id"], payload={"abatement_factor": 0.9})

        sanc2 = list_sanctions(review_id=review2["id"])[0]
        assert sanc2["line_count"] == 3, sanc2
        # 3 lines of round_half_up(25005 x 1.5 x 0.9) = 33757 each -> 101271.
        assert sanc2["total_amount_cents"] == 101271, sanc2
        # The sum-then-round variant would land on 101270 and is non-compliant.
        assert sanc2["total_amount_cents"] != 101270

    def test_first_offender_full_abatement_lines_sum_without_multiplier(self, api):
        """PRD §3.5: "A repeat-offender multiplier is determined from the
        member's sanction history: if the member has any prior sanction in
        `UPHELD`, `REDUCED`, or `PAID` status — proven priors — the multiplier is
        1.5; otherwise it is 1.0."

        Design: Difficulty/combinatorial_formula/sanction_per_line_round_then_sum_mode_b
        """
        set_clock("2026-01-05T00:00:00Z")
        d = create_active_member(org_id="1000002", member_type="ORIGINATOR")
        loan = register_loan(d["id"], loan_amount_cents=40000000)

        review = open_review(d["id"])
        add_finding(review["id"], loan["id"], severity="MINOR")
        issue_review(review["id"])
        settle_review(review["id"], payload={"abatement_factor": 1.0})

        sanc = list_sanctions(review_id=review["id"])[0]
        assert sanc["line_count"] == 1, sanc
        # No proven priors: multiplier 1.0, one MINOR line at base 25005.
        assert sanc["total_amount_cents"] == 25005, sanc
