"""The weekly gross-profit split: provisional variant versus final variant."""

import pytest

from test_helpers import (
    api_client, validate_success, assert_split_legs_sum_to_gross_profit,
    assert_settlement, ADMIN, reconcile_settlement, setup_settlement_with_lines,
    setup_settlement_with_rebate, get_success_data,
)


def _settlement(context):
    return get_success_data(
        api_client.get_settlement(context["settlement"]["id"], ADMIN))


class TestProvisionalVersusFinalVariant:
    """The two declared split variants divide different bases at different rates."""

    def test_provisional_variant_pays_the_trailing_average_then_the_final_variant_pays_the_real_week(self):
        """PRD §3.3: "While `provisional` is true the operator is paid against
        the provisional variant. `provisional_split_cents` is
        `provisional_gross_profit_cents` multiplied by the bare `split_pct`,
        with no tier bonus of any kind applied. The eligible percentage is
        therefore *not* used in this variant".
        PRD §3.3: "`gross_profit_cents` is the `gross_sales_cents` sum minus
        the `cost_of_goods_cents` sum, with `rebate_credit_cents` added on top."
        PRD §3.3: "`provisional_gross_profit_cents` — the figure the
        provisional variant divides — is the settlement's
        `trailing_avg_gross_profit_cents`, the operator's trailing four-week
        average, plus `rebate_credit_cents`, and it is deliberately not the
        actual week's result."

        Design: Difficulty/dual_variant_calc/settlement_provisional_split_vs_final_split_diverge
        """
        context = setup_settlement_with_rebate(
            rebate_cents=1_000_000,
            lines=[
                ("MERCHANDISE", 8_000_000, 5_600_000),
                ("FUEL", 6_000_000, 5_400_000),
                ("SERVICES", 2_000_000, 800_000),
            ],
            rebate_pass_pct=0.60,
            split_pct=0.50,
            trailing_avg=5_000_000,
        )
        settle_id = context["settlement"]["id"]

        # --- first step: OPEN -> DRAW_PAID, the provisional variant is live
        first = validate_success(
            api_client.reconcile_settlement(settle_id, ADMIN), 200)
        assert first["status"] == "DRAW_PAID"
        assert first["provisional"] is True
        assert first["rebate_credit_cents"] == pytest.approx(600_000.00, abs=0.01)
        assert first["provisional_gross_profit_cents"] == pytest.approx(5_600_000.00, abs=0.01)
        assert first["provisional_split_cents"] == pytest.approx(2_800_000.00, abs=0.01)
        # The provisional base is the trailing average, not the actual week.
        assert first["gross_profit_cents"] == pytest.approx(4_800_000.00, abs=0.01)

        # --- second step: DRAW_PAID -> RECONCILED, the final variant freezes
        final = validate_success(
            api_client.reconcile_settlement(settle_id, ADMIN), 200)
        assert final["status"] == "RECONCILED"
        assert final["provisional"] is False
        assert final["gross_profit_cents"] == pytest.approx(4_800_000.00, abs=0.01)
        assert final["eligible_split_pct"] == pytest.approx(0.50, abs=1e-9)
        assert final["franchisee_split_cents"] == pytest.approx(2_400_000.00, abs=0.01)
        assert final["franchisor_share_cents"] == pytest.approx(2_400_000.00, abs=0.01)
        # The divergence is 400,000.00, not a rounding difference.
        assert (final["franchisee_split_cents"] - final["provisional_split_cents"]
                == pytest.approx(-400_000.00, abs=0.01))

        assert_settlement(final)
        assert_split_legs_sum_to_gross_profit(final)

    def test_the_two_variants_split_different_bases_and_reconcile_to_the_split_base(self):
        """PRD §3.3: "`rebate_credit_cents` is the sum of the `flowthrough_cents`
        of the rebates just applied. `gross_profit_cents` is the
        `gross_sales_cents` sum minus the `cost_of_goods_cents` sum, with
        `rebate_credit_cents` added on top. `provisional_gross_profit_cents` —
        the figure the provisional variant divides — is the settlement's
        `trailing_avg_gross_profit_cents`, the operator's trailing four-week
        average, plus `rebate_credit_cents`".
        PRD §3.3: "`franchisor_share_cents` is whatever remains of the gross
        profit after the operator's share is taken, computed last so that the
        two shares always sum to the gross profit exactly."

        Design: Difficulty/dual_variant_calc/settlement_provisional_split_vs_final_split_diverge
        """
        context = setup_settlement_with_rebate(
            rebate_cents=1_000_000,
            lines=[
                ("MERCHANDISE", 8_000_000, 5_600_000),
                ("FUEL", 6_000_000, 5_400_000),
                ("SERVICES", 2_000_000, 800_000),
            ],
            rebate_pass_pct=0.60,
            split_pct=0.50,
            trailing_avg=5_000_000,
        )
        settle_id = context["settlement"]["id"]
        reconcile_settlement(settle_id)
        final = reconcile_settlement(settle_id)

        rebate_credit = final["rebate_credit_cents"]
        line_gross_profit = final["gross_sales_cents"] - final["cost_of_goods_cents"]

        # The final base is the realised week plus the rebate credit.
        assert final["gross_sales_cents"] == 16_000_000
        assert final["cost_of_goods_cents"] == 11_800_000
        assert line_gross_profit == 4_200_000
        assert final["gross_profit_cents"] == pytest.approx(
            line_gross_profit + rebate_credit, abs=0.01)

        # The provisional base is the trailing average plus the same rebate credit.
        assert final["provisional_gross_profit_cents"] == pytest.approx(
            final["trailing_avg_gross_profit_cents"] + rebate_credit, abs=0.01)
        assert final["provisional_gross_profit_cents"] != pytest.approx(
            final["gross_profit_cents"], abs=0.01)

        # The two legs reconcile to the base, to the cent.
        assert_split_legs_sum_to_gross_profit(final)
        assert (final["franchisee_split_cents"] + final["franchisor_share_cents"]
                == pytest.approx(final["gross_profit_cents"], abs=0.01))


class TestFinalVariantEvaluationOrder:
    """The final variant's pinned order is observable on the settlement."""

    def test_final_variant_adds_the_rebate_credit_to_line_gross_profit_and_caps_at_the_bare_split(self):
        """PRD §3.3: "`gross_profit_cents` is the `gross_sales_cents` sum minus
        the `cost_of_goods_cents` sum, with `rebate_credit_cents` added on top."
        PRD §3.3: "The tier bonus is 0.02 when the settlement's gross profit
        reaches at least 20,000,000 cents, 0.01 when it reaches at least
        10,000,000 cents, and 0.00 otherwise".
        PRD §3.3: "`franchisor_share_cents` is whatever remains of the gross
        profit after the operator's share is taken, computed last so that the
        two shares always sum to the gross profit exactly."

        Design: Corner/calculations/gross_profit_split_final_variant_matches_the_pinned_evaluation_order
        """
        context = setup_settlement_with_rebate(
            rebate_cents=2_000_000,
            lines=[
                ("MERCHANDISE", 6_000_000, 4_500_000),
                ("SERVICES", 2_000_000, 1_400_000),
            ],
            split_pct=0.55,
            rebate_pass_pct=0.50,
            trailing_avg=1_000_000,
        )
        settle_id = context["settlement"]["id"]
        reconcile_settlement(settle_id)
        final = reconcile_settlement(settle_id)

        assert final["gross_sales_cents"] == 8_000_000
        assert final["cost_of_goods_cents"] == 5_900_000
        assert final["rebate_credit_cents"] == pytest.approx(1_000_000.00, abs=0.01)
        # line gross profit 2,100,000.00 plus the 1,000,000.00 rebate credit
        assert final["gross_profit_cents"] == pytest.approx(3_100_000.00, abs=0.01)
        # 3,100,000.00 sits below the 10,000,000 mid threshold: no tier bonus
        assert final["eligible_split_pct"] == pytest.approx(0.55, abs=1e-9)
        assert final["eligible_split_pct"] != pytest.approx(0.57, abs=1e-9)
        assert final["franchisee_split_cents"] == pytest.approx(1_705_000.00, abs=0.01)
        assert final["franchisor_share_cents"] == pytest.approx(1_395_000.00, abs=0.01)
        assert (final["franchisee_split_cents"] + final["franchisor_share_cents"]
                == pytest.approx(final["gross_profit_cents"], abs=0.01))

    def test_reconcile_recomputes_the_split_legs_so_they_sum_exactly_to_the_base(self):
        """PRD §3.3: "`franchisee_split_cents` is the gross profit multiplied by
        `eligible_split_pct`; `franchisor_share_cents` is whatever remains of the
        gross profit after the operator's share is taken, computed last so that
        the two shares always sum to the gross profit exactly."
        PRD §3.3: "The eligible share carried in `eligible_split_pct` is the
        `split_pct` plus a tier bonus, and the result is capped at 0.75".

        Design: Corner/endpoints/reconcile_side_effects_recompute_split_legs_in_the_pinned_order
        """
        context = setup_settlement_with_lines(
            lines=[("MERCHANDISE", 7_000_000, 5_000_000)],
            split_pct=0.735,
            rebate_pass_pct=1.0,
            trailing_avg=1_000_000,
        )
        settle_id = context["settlement"]["id"]
        reconcile_settlement(settle_id)
        final = reconcile_settlement(settle_id)

        assert final["gross_profit_cents"] == pytest.approx(2_000_000.00, abs=0.01)
        # No tier bonus below the mid threshold.
        assert final["eligible_split_pct"] == pytest.approx(0.735, abs=1e-9)
        assert final["franchisee_split_cents"] == pytest.approx(1_470_000.00, abs=0.01)
        assert final["franchisor_share_cents"] == pytest.approx(530_000.00, abs=0.01)
        assert final["franchisor_share_cents"] == pytest.approx(
            final["gross_profit_cents"] - final["franchisee_split_cents"], abs=0.01)
        assert final["provisional"] is False


class TestSettlementReadExposesBothVariants:
    """A settlement that has only reached DRAW_PAID reports both variants at once."""

    def test_get_reports_the_provisional_fields_as_live_and_the_final_base_alongside_them(self):
        """PRD §3.3: "While `provisional` is true the operator is paid against
        the provisional variant. `provisional_split_cents` is
        `provisional_gross_profit_cents` multiplied by the bare `split_pct`".
        PRD §3.3: "`gross_profit_cents` is the `gross_sales_cents` sum minus the
        `cost_of_goods_cents` sum, with `rebate_credit_cents` added on top."
        PRD §3.3: "`provisional` flag is true" on the settlement that has just opened.

        Design: Corner/endpoints/settlement_get_surfaces_derived_provisional_and_final_fields_together
        """
        context = setup_settlement_with_lines(
            lines=[("FUEL", 5_000_000, 4_200_000)],
            split_pct=0.50,
            rebate_pass_pct=1.0,
            trailing_avg=9_000_000,
        )
        settle_id = context["settlement"]["id"]
        reconcile_settlement(settle_id)

        read = validate_success(
            api_client.get_settlement(settle_id, ADMIN), 200)
        assert read["status"] == "DRAW_PAID"
        assert read["provisional"] is True
        assert read["provisional_gross_profit_cents"] == pytest.approx(9_000_000.00, abs=0.01)
        assert read["provisional_split_cents"] == pytest.approx(4_500_000.00, abs=0.01)
        # The realised week is already visible while the provisional variant is live.
        assert read["gross_profit_cents"] == pytest.approx(800_000.00, abs=0.01)
        # The provisional payout is the figure the operator is paid against here.
        assert read["net_settlement_cents"] == pytest.approx(
            read["provisional_split_cents"] - read["shrink_charge_cents"]
            - read["waste_charge_cents"] - read["draw_recovery_cents"], abs=0.01)