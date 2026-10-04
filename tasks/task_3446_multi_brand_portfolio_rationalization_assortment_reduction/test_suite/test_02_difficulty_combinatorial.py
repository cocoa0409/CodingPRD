"""Difficulty queue: combinatorial formulas — the four-sub-score clamped
weighted composite, and the TSA early-termination penalty's pinned rounding
order (ceil months -> multiply -> round the product once).
"""
from test_helpers import (
    TEST_USERS,
    WORKED,
    api_client,
    assert_rationalization_case,
    assert_tsa,
    create_brand,
    create_item,
    create_plant,
    create_rationalization_case_payload,
    set_clock,
    setup_divestiture_closed,
    terminate_tsa,
    validate_created,
)

PM_PROPOSER = TEST_USERS["portfolio_manager_proposer_headers"]


class TestCompositeScoreMulticlamp:
    """Worked calibration fixture: brand revenue 1,000,000,000 / pl 40; item
    10,000 units, revenue 2,000, cost 1,700."""

    def _create_case(self):
        brand = create_brand(core_flag=True, private_label_share_pct=40,
                             annual_net_revenue_cents=1000000000)
        plant = create_plant(quarterly_capacity_units=1000000)
        item = create_item(brand["id"], plant["id"], annual_units=10000,
                           unit_net_revenue_cents=2000, unit_cost_cents=1700,
                           units_on_hand=0)
        resp = api_client.create_rationalization_case(
            create_rationalization_case_payload(item["id"]), PM_PROPOSER
        )
        return validate_created(resp)

    def test_composite_sub_scores_match_worked_example(self):
        """PRD §3.2: "A worked example fixes the calibration: for a brand with
        `annual_net_revenue_cents` of 1,000,000,000 and
        `private_label_share_pct` of 40, and an item with `annual_units`
        10,000, `unit_net_revenue_cents` 2,000, and `unit_cost_cents` 1,700,
        the four sub-scores come out to 80.00, 57.14, 90.00, and 63.00, the
        `composite_score` is 72.04, and the `recommendation` is `CUT`."

        Design: Difficulty/combinatorial_formula/composite_score_multiclamp_weighted_composition
        """
        case = self._create_case()
        assert_rationalization_case(case)
        assert case["volume_score"] == WORKED["COMPOSITE_VOLUME_SCORE"], (
            f"volume_score must be 100 - 10000/50000*100 = 80.00, got "
            f"{case['volume_score']}"
        )
        assert case["margin_score"] == WORKED["COMPOSITE_MARGIN_SCORE"], (
            f"margin_score must be (0.35 - 0.15)/0.35*100 half-up = 57.14, got "
            f"{case['margin_score']}"
        )
        assert case["shelf_resilience_score"] == WORKED["COMPOSITE_SHELF_SCORE"], (
            f"shelf_resilience_score must be 100 - 0.02/0.20*100 = 90.00, got "
            f"{case['shelf_resilience_score']}"
        )
        assert case["backlash_resilience_score"] == WORKED["COMPOSITE_BACKLASH_SCORE"], (
            f"backlash_resilience_score must be 90.00 * (0.5 + 0.005*40) = 63.00, "
            f"got {case['backlash_resilience_score']}"
        )

    def test_composite_score_and_recommendation_from_rounded_subscores(self):
        """PRD §3.2: "The `composite_score` is then computed **from the four
        already-rounded sub-scores** as a weighted blend — 0.30 times
        `volume_score`, plus 0.25 times `margin_score`, plus 0.20 times
        `shelf_resilience_score`, plus 0.25 times `backlash_resilience_score` —
        and the blend itself is rounded half-up to 2 decimal places."
        PRD §3.2: "a `composite_score` of at least 65 yields a recommendation
        of `CUT`; anything below 65 yields `KEEP`."

        Design: Difficulty/combinatorial_formula/composite_score_multiclamp_weighted_composition
        """
        case = self._create_case()
        # 0.30*80.00 + 0.25*57.14 + 0.20*90.00 + 0.25*63.00 = 72.035 -> 72.04
        assert case["composite_score"] == WORKED["COMPOSITE_SCORE"], (
            f"composite from ROUNDED sub-scores must be 72.04, got "
            f"{case['composite_score']}"
        )
        assert case["recommendation"] == "CUT", (
            f"composite 72.04 >= 65 must recommend CUT, got {case['recommendation']}"
        )
        assert case["case_status"] == "SCORED"
        assert case["decider_user_id"] is None


class TestTsaPenaltyNestedRounding:
    def _setup_active_tsa_with_fee_120010(self):
        """Non-core brand divested; TSA ACTIVE with fee 120,010 cents and
        window 2026-09-01..2027-09-01 (close at the default clock, which equals
        the TSA start date — the boundary is inclusive)."""
        _, _, tsa = setup_divestiture_closed(
            tsa_monthly_fee_cents=120010,
            tsa_start_date="2026-09-01T00:00:00Z",
            tsa_end_date="2027-09-01T00:00:00Z",
            brand_overrides={"annual_net_revenue_cents": 800000000,
                             "private_label_share_pct": 20},
            divestiture_overrides={"expected_close_date": "2026-10-01T00:00:00Z"},
        )
        assert tsa["tsa_status"] == "ACTIVE", "Setup failed: TSA must be ACTIVE after close"
        return tsa

    def test_tsa_penalty_pinned_rounding_order_worked_example(self):
        """PRD §3.5: "A worked example anchors the arithmetic end to end: a TSA
        starting 2026-09-01 and ending 2027-09-01, terminated at logical time
        2027-06-15, has 78 days remaining, which is 3 penalty months, and at a
        120,010-cent fee the posted penalty is 90,008 cents."
        PRD §3.5: "The alternative order — rounding a per-month penalty first
        and then multiplying — is forbidden, because it yields different cents:
        a `monthly_fee_cents` of 120,010 with 3 months remaining produces a
        penalty of 90,008 cents under the pinned order, versus 90,009 under the
        forbidden one."

        Design: Difficulty/combinatorial_formula/tsa_penalty_nested_rounding_order
        """
        tsa = self._setup_active_tsa_with_fee_120010()
        set_clock("2027-06-15T00:00:00Z")
        terminated = terminate_tsa(tsa["id"])
        assert_tsa(terminated)
        assert terminated["tsa_status"] == "TERMINATED"
        assert terminated["early_termination_penalty_cents"] == WORKED["TSA_PENALTY_WORKED_CENTS"], (
            f"ceil(78/30)=3 months; round_half_up(3 * 120010 * 0.25) = 90008 "
            f"(forbidden per-month order would give 90009), got "
            f"{terminated['early_termination_penalty_cents']}"
        )

    def test_tsa_penalty_single_month_half_cent_rounds_up(self):
        """PRD §3.5: "Otherwise, step one: the months remaining are the days
        remaining divided by 30 days per penalty month and rounded **up** to a
        whole number of months. Step two: that month count is multiplied by the
        TSA's `monthly_fee_cents` and by the penalty rate of 0.25 (25 percent).
        Step three: the product is rounded half-up to integer cents — and this
        rounding happens exactly once, on the product."
        PRD §2.6: "a fractional part of exactly one-half of the final kept
        digit rounds away from zero".

        Design: Difficulty/combinatorial_formula/tsa_penalty_nested_rounding_order
        """
        tsa = self._setup_active_tsa_with_fee_120010()
        # 2027-08-13 -> 2027-09-01 is 19 days remaining; ceil(19/30) = 1 month;
        # 1 * 120010 * 0.25 = 30002.5 -> half-up on the product = 30003.
        set_clock("2027-08-13T00:00:00Z")
        terminated = terminate_tsa(tsa["id"])
        assert terminated["early_termination_penalty_cents"] == 30003, (
            f"1 month * 120010 * 0.25 = 30002.5 must round half-up to 30003, "
            f"got {terminated['early_termination_penalty_cents']}"
        )
        assert terminated["tsa_status"] == "TERMINATED"
