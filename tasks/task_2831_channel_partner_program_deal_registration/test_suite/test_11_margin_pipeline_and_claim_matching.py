"""Multi-input formulas whose evaluation order decides the cents: the six-step channel margin
pipeline and the per-line matching of a market development fund claim."""

import pytest
from test_helpers import (
    ANALYST,
    assert_mdf_claim,
    assert_mdf_fund_conservation,
    assert_order_invoice,
    assert_order_invoice_margin_conservation,
    assert_rate_precision,
    read_allocation,
    read_claim,
    read_partner,
    read_proof,
    seed_gold_claim_with_three_verified_proofs,
    seed_gold_pinned_margin_context,
    validate_success,
)


class TestMarginBandPinnedToPreliminaryNet:
    def test_band_is_read_off_the_preliminary_net_and_the_ceiling_clamps_the_final_margin(
        self, api
    ):
        """PRD §3.6: "The volume band is a function of the preliminary net amount, and the final
        margin is a function of the band, so re-deriving the band from the final net would produce
        a different invoice."
        PRD §3.6: "Read `volume_band` off the preliminary net alone: `HIGH` when the preliminary
        net is at least 20000000 cents (two hundred thousand dollars), `MID` when it is at least
        5000000 cents (fifty thousand dollars) but below the high threshold, and `NONE` otherwise."

        Design: Difficulty/combinatorial_formula/channel_margin_band_pinned_to_preliminary_net
        """
        seed = seed_gold_pinned_margin_context()
        partner_id = seed["partner"]["id"]

        assert seed["partner"]["tier"] == "GOLD"
        assert seed["registration"]["exclusivity_start_at"] == "2026-01-05T00:00:00.000Z"
        assert seed["registration"]["exclusivity_end_at"] == "2026-04-05T00:00:00.000Z"
        assert seed["registration"]["protection_days"] == 90
        assert seed["registration"]["registration_margin_uplift_pct"] == pytest.approx(
            0.06, abs=1e-9
        )
        assert seed["spr"]["approved_extra_margin_pct"] == pytest.approx(0.02, abs=1e-9)
        assert seed["spr"]["expires_at"] == "2026-02-04T00:00:00.000Z"

        order = validate_success(
            api.create_order_invoice(
                {
                    "partner_id": partner_id,
                    "order_type": "STOCKING",
                    "list_amount_cents": 28000000,
                    "registration_id": seed["registration"]["id"],
                },
                ANALYST,
            ),
            201,
        )
        assert_order_invoice(order)

        # base 0.18 + registration 0.06 + special pricing 0.02 + stocking 0.02 = 0.28,
        # so the preliminary net is 28000000 * 0.72 = 20160000, at or above the HIGH threshold.
        assert order["volume_band"] == "HIGH"
        # 0.28 + 0.03 = 0.31 is clamped by the GOLD ceiling of 0.30.
        assert order["margin_pct"] == pytest.approx(0.3000, abs=1e-9)
        assert_rate_precision(order["margin_pct"])
        assert order["invoice_amount_cents"] == 19600000
        assert order["margin_value_cents"] == 8400000
        assert order["list_amount_cents"] == 28000000
        assert order["status"] == "PENDING"
        assert order["invoiced_at"] is None

    def test_a_band_re_derived_from_the_final_net_would_have_produced_different_cents(self, api):
        """PRD §3.6: "*Step two — the preliminary net.* Multiply `list_amount_cents` by one minus
        the preliminary margin and round half-up to a whole number of cents."
        PRD §3.6: "This figure exists only to select the band; it is never stored."

        Design: Difficulty/combinatorial_formula/channel_margin_band_pinned_to_preliminary_net
        """
        seed = seed_gold_pinned_margin_context()

        order = validate_success(
            api.create_order_invoice(
                {
                    "partner_id": seed["partner"]["id"],
                    "order_type": "STOCKING",
                    "list_amount_cents": 28000000,
                    "registration_id": seed["registration"]["id"],
                },
                ANALYST,
            ),
            201,
        )

        # The stored invoice amount of 19600000 sits below the HIGH threshold; a band re-derived
        # from it would select MID, giving margin_pct 0.2950 and invoice_amount_cents 19740000.
        assert order["invoice_amount_cents"] < 20000000
        assert order["volume_band"] == "HIGH"
        assert order["margin_pct"] != pytest.approx(0.2950, abs=1e-9)
        assert order["invoice_amount_cents"] != 19740000
        assert "preliminary_net_cents" not in order

    def test_margin_value_is_obtained_by_subtraction_so_no_cent_is_created_or_destroyed(
        self, api
    ):
        """PRD §3.6: "*Step six — the margin value.* `margin_value_cents` is `list_amount_cents`
        minus `invoice_amount_cents`, obtained by subtraction and never by a second
        multiplication, so that not a single cent is created or destroyed."

        Design: Difficulty/combinatorial_formula/channel_margin_band_pinned_to_preliminary_net
        """
        seed = seed_gold_pinned_margin_context()

        order = validate_success(
            api.create_order_invoice(
                {
                    "partner_id": seed["partner"]["id"],
                    "order_type": "STOCKING",
                    "list_amount_cents": 28000000,
                    "registration_id": seed["registration"]["id"],
                },
                ANALYST,
            ),
            201,
        )

        assert order["list_amount_cents"] == order["invoice_amount_cents"] + order["margin_value_cents"]
        assert 28000000 == 19600000 + 8400000
        assert_order_invoice_margin_conservation(order)


class TestClaimMatchedPerLineThenSummed:
    def test_each_verified_line_is_rounded_before_the_total_is_summed(self, api):
        """PRD §3.7: "each document's `matched_line_cents` is its `spend_amount_cents` multiplied
        by the match rate for the partner's `tier` — 0.25 for `REGISTERED`, 0.40 for `SILVER`,
        0.50 for `GOLD`, 0.60 for `PLATINUM` — and rounded half-up to whole cents"
        PRD §3.7: "`matched_total_cents` is the exact sum of those already-rounded line figures;
        summing the raw spend and rounding once at the end is a different and wrong answer
        whenever two or more lines produce a half-cent product."

        Design: Difficulty/combinatorial_formula/mdf_claim_per_line_rounding_before_summation
        """
        seed = seed_gold_claim_with_three_verified_proofs()
        allocation = seed["allocation"]
        assert allocation["basis_revenue_cents"] == 8650000
        assert allocation["allocated_cents"] == 273000

        claim = validate_success(
            api.validate_mdf_claim(seed["claim"]["id"], {"decision": "VALIDATE"}, ANALYST)
        )
        assert_mdf_claim(claim)

        lines = [read_proof(proof["id"])["matched_line_cents"] for proof in seed["proofs"]]
        assert lines == [6173, 3395, 556]
        assert claim["matched_total_cents"] == 10124
        # Summing the raw spend first - 20245 * 0.50 = 10122.5 - and rounding once gives 10123.
        assert claim["matched_total_cents"] != 10123
        assert sum(lines) == claim["matched_total_cents"]

    def test_approved_cents_is_the_smaller_of_the_request_and_the_matched_total(self, api):
        """PRD §3.7: "`approved_cents` is then the smaller of `requested_cents` and
        `matched_total_cents`; no availability term enters this comparison, because
        `requested_cents` was already committed against the pool when the claim was filed, so the
        pool can always cover what is approved."
        PRD §3.7: "The unmatched remainder — `requested_cents` less `approved_cents` — is released
        back: `committed_cents` decreases by that remainder and `available_cents` is recomputed."

        Design: Difficulty/combinatorial_formula/mdf_claim_per_line_rounding_before_summation
        """
        seed = seed_gold_claim_with_three_verified_proofs()
        allocation_id = seed["allocation"]["id"]

        claim = validate_success(
            api.validate_mdf_claim(seed["claim"]["id"], {"decision": "VALIDATE"}, ANALYST)
        )

        assert claim["requested_cents"] == 20000
        assert claim["approved_cents"] == 10124
        assert claim["validation_state"] == "VALIDATED"
        assert claim["settlement_state"] == "UNPAID"
        assert claim["proof_round"] == 0
        assert claim["validated_by_user_id"] == ANALYST["X-User-ID"]

        allocation = read_allocation(allocation_id)
        assert allocation["committed_cents"] == 10124
        assert allocation["available_cents"] == 262876
        assert allocation["paid_cents"] == 0
        assert allocation["expired_cents"] == 0
        assert_mdf_fund_conservation(allocation)

    def test_validation_rolls_the_raw_verified_spend_into_qualified_marketing_spend(self, api):
        """PRD §3.7: "Validation finally recomputes the partner's
        `marketing_qualified_spend_cents` and `marketing_attainment_pct`; when the recomputed
        attainment reaches or exceeds 0.75 while the partner's `tier_status` is `PROBATION` with
        `standing_reason` `MARKETING_ATTAINMENT_SHORTFALL`, the partner returns to `COMPLIANT` and
        `portal_entitlement_level` is recomputed."

        Design: Difficulty/combinatorial_formula/mdf_claim_per_line_rounding_before_summation
        """
        seed = seed_gold_claim_with_three_verified_proofs()
        partner_id = seed["partner"]["id"]
        assert read_partner(partner_id)["marketing_qualified_spend_cents"] == 0

        validate_success(
            api.validate_mdf_claim(seed["claim"]["id"], {"decision": "VALIDATE"}, ANALYST)
        )

        partner = read_partner(partner_id)
        # The qualified spend is the raw verified spend, not the matched figure.
        assert partner["marketing_qualified_spend_cents"] == 20245
        assert partner["marketing_attainment_pct"] == pytest.approx(1.0, abs=1e-9)
        assert read_claim(seed["claim"]["id"])["matched_total_cents"] == 10124
