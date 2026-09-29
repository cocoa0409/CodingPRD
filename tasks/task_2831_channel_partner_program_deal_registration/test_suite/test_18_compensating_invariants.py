"""Two conserved quantities probed through the operations that most nearly break them: the
per-invoice margin decomposition under a credit memo, and the fund ledger under a claw-back."""

import pytest
from test_helpers import (
    ANALYST,
    assert_mdf_fund_conservation,
    assert_order_invoice_margin_conservation,
    create_and_invoice_order,
    read_allocation,
    read_claim,
    read_invoice,
    read_partner,
    read_proof,
    seed_gold_claim_with_verified_proof,
    seed_gold_distributor,
    set_clock,
    validate_claim,
    validate_success,
)


class TestCreditMemoPreservesMarginConservation:
    def test_a_credit_memo_transfers_cents_without_touching_the_list_amount(self, api):
        """PRD §3.6: "On success the order moves `INVOICED → CREDITED`: `credit_memo_cents` records
        the credit, `invoice_amount_cents` is reduced by it, `margin_value_cents` is re-derived as
        `list_amount_cents` minus the new `invoice_amount_cents`, `margin_pct` is re-derived as
        `margin_value_cents` divided by `list_amount_cents` rounded half-up to four decimal places,
        `credit_reason` is recorded, the partner's `trailing_revenue_cents` is recomputed, and the
        order's `version` advances by 1."
        PRD §3.6: "A credit memo is a pure transfer of cents out of `invoice_amount_cents` and into
        `margin_value_cents` that never touches `list_amount_cents`."

        Design: Difficulty/compensating_invariant/credit_memo_preserves_per_invoice_margin_conservation
        """
        seed = seed_gold_distributor()
        partner_id = seed["partner"]["id"]

        set_clock("2026-01-20T00:00:00.000Z")
        order = create_and_invoice_order(
            partner_id, order_type="DROP_SHIP", list_amount_cents=12_000_000
        )
        assert order["margin_pct"] == pytest.approx(0.1950, abs=1e-9)
        assert order["invoice_amount_cents"] == 9660000
        assert order["margin_value_cents"] == 2340000
        assert order["list_amount_cents"] == 12000000 == 9660000 + 2340000
        assert_order_invoice_margin_conservation(order)

        credited = validate_success(
            api.issue_credit_memo(
                order["id"],
                {"credit_memo_cents": 500000, "credit_reason": "post-ship price adjustment"},
                ANALYST,
            )
        )

        assert credited["status"] == "CREDITED"
        assert credited["credit_memo_cents"] == 500000
        assert credited["credit_reason"] == "post-ship price adjustment"
        assert credited["invoice_amount_cents"] == 9160000
        assert credited["margin_value_cents"] == 2840000
        assert credited["margin_pct"] == pytest.approx(0.2367, abs=1e-9)
        assert credited["list_amount_cents"] == 12000000 == 9160000 + 2840000
        assert credited["margin_value_cents"] - order["margin_value_cents"] == 500000
        assert_order_invoice_margin_conservation(credited)

    def test_the_credit_leaves_the_tier_ceiling_intact_and_is_subtracted_from_revenue_once(
        self, api
    ):
        """PRD §3.6: "Because `invoice_amount_cents` is already net of every credit memo applied so
        far, the rollup must not subtract `credit_memo_cents` a second time."
        PRD §3.6: "It must also leave the order inside the tier's margin ceiling: the effective
        margin after the credit — the list amount minus the reduced invoice amount, divided by the
        list amount, rounded half-up to four decimal places — must be at or below the ceiling for
        the partner's `tier`, or `ERR_MARGIN_CEILING_EXCEEDED`."

        Design: Difficulty/compensating_invariant/credit_memo_preserves_per_invoice_margin_conservation
        """
        seed = seed_gold_distributor()
        partner_id = seed["partner"]["id"]

        set_clock("2026-01-20T00:00:00.000Z")
        order = create_and_invoice_order(
            partner_id, order_type="DROP_SHIP", list_amount_cents=12_000_000
        )
        assert read_partner(partner_id)["trailing_revenue_cents"] == 18310000

        credited = validate_success(
            api.issue_credit_memo(
                order["id"],
                {"credit_memo_cents": 500000, "credit_reason": "post-ship price adjustment"},
                ANALYST,
            )
        )
        # 0.2367 sits under the GOLD ceiling of 0.30, so the memo is admissible.
        assert credited["margin_pct"] <= 0.30

        assert read_partner(partner_id)["trailing_revenue_cents"] == 17810000

        untouched = read_invoice(seed["seed_invoice"]["id"])
        assert untouched["invoice_amount_cents"] == 8650000
        assert untouched["margin_value_cents"] == 1350000
        assert untouched["credit_memo_cents"] == 0


class TestClaimRejectRestoresBucketConservation:
    def test_a_file_validate_reject_round_trip_returns_the_pool_to_its_exact_prior_balance(
        self, api
    ):
        """PRD §3.7: "At every observable instant `allocated_cents` equals the sum of the four
        buckets, and neither `available_cents` nor `committed_cents` may ever go negative."
        PRD §3.8: "Read as a ledger, the whole fund system has exactly six movements, each a pure
        transfer between two buckets: filing a claim moves `requested_cents` from available to
        committed; validating moves the unmatched remainder from committed back to available;
        rejecting moves back to available either the previous `approved_cents` (when the claim had
        been validated) or the full `requested_cents` (when it had not); paying moves
        `approved_cents` from committed to paid; writing off moves `approved_cents` from committed
        to expired; and closing the period moves what remains from committed to available to
        expired in cascade C's pinned order."

        Design: Difficulty/compensating_invariant/claim_reject_restores_mdf_fund_bucket_conservation
        """
        seed = seed_gold_claim_with_verified_proof()
        allocation_id = seed["allocation"]["id"]
        claim_id = seed["claim"]["id"]

        filed = read_allocation(allocation_id)
        assert filed["allocated_cents"] == 273000
        assert (filed["committed_cents"], filed["paid_cents"], filed["expired_cents"]) == (
            20000,
            0,
            0,
        )
        assert filed["available_cents"] == 253000
        assert_mdf_fund_conservation(filed)

        validated_claim = validate_claim(claim_id, "VALIDATE")
        assert validated_claim["matched_total_cents"] == 6000
        assert validated_claim["approved_cents"] == 6000
        after_validate = read_allocation(allocation_id)
        assert after_validate["committed_cents"] == 6000
        assert after_validate["available_cents"] == 267000
        assert_mdf_fund_conservation(after_validate)

        validate_success(
            api.validate_mdf_claim(
                claim_id,
                {"decision": "REJECT", "rejection_reason": "activity ineligible on review"},
                ANALYST,
            )
        )

        restored = read_allocation(allocation_id)
        assert restored["allocated_cents"] == 273000
        assert restored["committed_cents"] == 0
        assert restored["paid_cents"] == 0
        assert restored["expired_cents"] == 0
        assert restored["available_cents"] == 273000
        assert 273000 == 0 + 0 + 0 + 273000
        assert_mdf_fund_conservation(restored)

    def test_the_claw_back_returns_money_to_available_and_never_to_expired(self, api):
        """PRD §3.7: "`available_cents` is unspoken-for money and is always `allocated_cents` less
        `committed_cents` less `paid_cents` less `expired_cents`; `committed_cents` is money
        reserved by claims that are neither settled nor rejected; `paid_cents` is money actually
        disbursed to the partner; and `expired_cents` is money burned, either by closing the period
        or by writing a claim off."
        PRD §3.7: "From `SUBMITTED → REJECTED` and from `PROOF_REQUESTED → REJECTED` the behaviour
        is identical: `approved_cents` is set to 0, the reason is recorded, `validated_by_user_id`
        is set to the acting analyst, `committed_cents` decreases by the claim's full
        `requested_cents`, `available_cents` is recomputed, and the claim's `version` advances
        by 1."

        Design: Difficulty/compensating_invariant/claim_reject_restores_mdf_fund_bucket_conservation
        """
        seed = seed_gold_claim_with_verified_proof()
        allocation_id = seed["allocation"]["id"]
        claim_id = seed["claim"]["id"]
        partner_id = seed["partner"]["id"]

        validate_claim(claim_id, "VALIDATE")
        assert read_allocation(allocation_id)["expired_cents"] == 0

        clawed_back = validate_success(
            api.validate_mdf_claim(
                claim_id,
                {"decision": "REJECT", "rejection_reason": "activity ineligible on review"},
                ANALYST,
            )
        )
        assert clawed_back["validation_state"] == "REJECTED"
        assert clawed_back["approved_cents"] == 0
        assert clawed_back["rejection_reason"] == "activity ineligible on review"
        assert clawed_back["settlement_state"] == "UNPAID"
        assert read_allocation(allocation_id)["expired_cents"] == 0

        # The row keeps its verification and its matched line; only the numerator contribution goes.
        proof = read_proof(seed["proof"]["id"])
        assert proof["verified"] is True
        assert proof["matched_line_cents"] == 6000

        partner = read_partner(partner_id)
        assert partner["marketing_qualified_spend_cents"] == 0
        assert partner["marketing_attainment_pct"] == pytest.approx(1.0, abs=1e-9)
        assert partner["tier_status"] == "COMPLIANT"
        assert read_claim(claim_id)["validation_state"] == "REJECTED"
