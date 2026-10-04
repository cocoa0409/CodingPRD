"""Combinatorial formula: final settlement composition, rounding order, tier snapshot."""

from test_helpers import (
    setup_settlement_scenario,
    complete,
    get_driver,
)


class TestSettlementComposition:
    def test_settlement_composes_tier_bonus_surcharges_and_capped_penalties(self, api):
        """PRD §3.6: "Second, `tier_bonus_cents` is a percentage of the gross determined
        by the tier snapshot `tier_at_accept`, never the driver's live tier: `STANDARD`
        earns no bonus, `PLUS` earns 500 basis points (5 percent), and `PREMIER` earns
        1000 basis points (10 percent) of gross, rounded half-up."
        PRD §3.6: "Fourth, penalties are counted: 200 cents for each delivered package
        that was late, 150 cents for each delivered package with a non-compliant photo,
        and 500 cents for each package returned to the station. Fifth, the penalty total
        is capped at half of the gross plus tier bonus, rounded half-up, so
        `penalties_cents` is the smaller of the raw penalties and that cap. Finally,
        `final_pay_cents` is gross plus tier bonus plus surcharges minus the capped
        penalties."

        Design: Difficulty/combinatorial_formula/settlement_composes_tier_bonus_surcharges_capped_penalties
        """
        (
            _station,
            _driver,
            _vehicle,
            _block,
            assignment,
            _packages,
            _provisional,
        ) = setup_settlement_scenario()

        ps = complete(assignment["id"])

        assert ps["gross_cents"] == 7500  # round_half_up(6000 * 12500 / 10000)
        assert ps["tier_bonus_cents"] == 750  # PREMIER 1000 bp of gross
        assert ps["surcharges_cents"] == 621  # 78 + 233 + 310
        # raw penalties 200 + 150 = 350 < cap round_half_up(0.5 * 8250) = 4125
        assert ps["penalties_cents"] == 350
        assert ps["final_pay_cents"] == 8521

    def test_settlement_components_reconcile_to_final(self, api):
        """PRD §3.6: "Finally, `final_pay_cents` is gross plus tier bonus plus
        surcharges minus the capped penalties."

        Design: Difficulty/combinatorial_formula/settlement_composes_tier_bonus_surcharges_capped_penalties
        """
        (
            _station,
            _driver,
            _vehicle,
            _block,
            assignment,
            _packages,
            _provisional,
        ) = setup_settlement_scenario()

        ps = complete(assignment["id"])

        assert (
            ps["final_pay_cents"]
            == ps["gross_cents"]
            + ps["tier_bonus_cents"]
            + ps["surcharges_cents"]
            - ps["penalties_cents"]
        )
        assert ps["final_pay_cents"] == 8521


class TestSurchargeRoundingOrder:
    def test_surcharges_rounded_per_package_then_summed(self, api):
        """PRD §2.6: "Every multiplication that produces a money figure is rounded
        half-up to the nearest whole cent, and the rounding point is pinned by the rule
        that owns it — in particular, package handling surcharges are rounded per
        package before summation, never on the aggregate weight."
        PRD §3.6: "Third, `surcharges_cents` is a per-package handling surcharge: for
        each package with status `DELIVERED`, the billable weight in kilograms is
        multiplied by 155 cents per kilogram and rounded half-up per package, and those
        per-package amounts are summed. Rounding per package before summing is pinned;
        rounding the aggregate weight would produce a different total."

        Design: Difficulty/combinatorial_formula/surcharge_rounding_per_package_then_sum
        """
        (
            _station,
            _driver,
            _vehicle,
            _block,
            assignment,
            _packages,
            _provisional,
        ) = setup_settlement_scenario()

        ps = complete(assignment["id"])

        # Per-package round-half-up: 0.5kg -> 78, 1.5kg -> 233, 2.0kg -> 310; sum 621.
        # Aggregate-then-round would give round_half_up(4.0 * 155) = 620.
        assert ps["surcharges_cents"] == 621, (
            f"per-package rounding must give 621, got {ps['surcharges_cents']}"
        )
        assert ps["surcharges_cents"] != 620

    def test_surcharge_rounding_divergence_pins_pinned_order(self, api):
        """PRD §3.6: "Rounding per package before summing is pinned; rounding the
        aggregate weight would produce a different total."

        Design: Difficulty/combinatorial_formula/surcharge_rounding_per_package_then_sum
        """
        (
            _station,
            _driver,
            _vehicle,
            _block,
            assignment,
            _packages,
            _provisional,
        ) = setup_settlement_scenario()

        ps = complete(assignment["id"])

        # 78 + 233 + 310 == 621; the 1.5kg package's 232.5 rounds up to 233.
        assert ps["surcharges_cents"] == 621


class TestTierSnapshotBreaksPayRatingCircle:
    def test_bonus_uses_accept_time_tier_snapshot_not_live_tier(self, api):
        """PRD §3.6: "Second, `tier_bonus_cents` is a percentage of the gross determined
        by the tier snapshot `tier_at_accept`, never the driver's live tier: `STANDARD`
        earns no bonus, `PLUS` earns 500 basis points (5 percent), and `PREMIER` earns
        1000 basis points (10 percent) of gross, rounded half-up. The tier actually
        applied is recorded on the statement as `tier_applied`."
        PRD §2.8: "Work already accepted keeps the tier snapshot taken at acceptance."

        Design: Difficulty/combinatorial_formula/tier_snapshot_breaks_pay_rating_circle
        """
        (
            _station,
            driver,
            _vehicle,
            _block,
            assignment,
            _packages,
            _provisional,
        ) = setup_settlement_scenario()

        ps = complete(assignment["id"])
        profile = get_driver(driver["id"])

        # The completion event scores 500 - 100 - 150 = 350; the rolling average
        # becomes round_half_up((500 + 350) / 2) = 425 (< 430), demoting the live tier.
        assert profile["rating_score_x100"] == 425
        assert profile["rating_tier"] == "STANDARD"
        # Yet the statement's bonus was computed from the PREMIER snapshot.
        assert ps["tier_applied"] == "PREMIER"
        assert ps["tier_bonus_cents"] == 750
        assert ps["final_pay_cents"] == 8521

    def test_completion_recomputes_live_tier_after_settlement_uses_snapshot(self, api):
        """PRD §3.3: "acceptance freezes two snapshots onto the new assignment:
        `surge_multiplier_snapshot_bp` copies the block's `surge_multiplier_bp` at that
        moment, and `tier_at_accept` copies the driver's `rating_tier`."

        Design: Difficulty/combinatorial_formula/tier_snapshot_breaks_pay_rating_circle
        """
        (
            _station,
            driver,
            _vehicle,
            _block,
            assignment,
            _packages,
            _provisional,
        ) = setup_settlement_scenario()

        assert assignment["tier_at_accept"] == "PREMIER"

        ps = complete(assignment["id"])
        profile = get_driver(driver["id"])

        # Live tier degraded by the new 350-point event; statement kept the snapshot.
        assert profile["rating_tier"] == "STANDARD"
        assert ps["tier_applied"] == "PREMIER"
