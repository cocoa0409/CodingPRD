"""Multi-input formulas: match score, per-demand forecast rounding, discount pass."""

import pytest

from test_helpers import (
    ApprovalStatus,
    ApprovalTier,
    AssignmentStatus,
    ForecastBasis,
    assert_hiring_forecast,
    fixtures,
)
from test_helpers.constants import INSTANT_AUG_03, SYSTEM_AUTO_USER_ID


class TestMatchScoreSixInputs:
    @staticmethod
    def _pool(api):
        """Ada, who scores on every component, next to two expensive peers."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        ada = fixtures.hire(
            api,
            world,
            full_name="Ada Byron",
            proficiency_level=4,
            cost_rate_usd_per_hour=120.00,
            standard_bill_rate_usd_per_hour=300.00,
            travel_max_nights_per_week=3,
            development_goal_skill_id=world["skill"]["id"],
            industry_experience=[{"industry_code": "RETAIL", "years": 5.0}],
            assertion_kwargs={
                "certification_code": "AWS_SA_PRO",
                "certification_expires_on": "2027-01-31",
            },
        )
        turing = fixtures.hire(
            api,
            world,
            full_name="Alan Turing",
            proficiency_level=5,
            cost_rate_usd_per_hour=300.00,
            standard_bill_rate_usd_per_hour=500.00,
            travel_max_nights_per_week=3,
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            client_name="Acme Retail",
            min_proficiency_level=3,
            required_fte=2.00,
            win_probability_pct=60,
            start_date="2026-08-03",
            end_date="2026-08-28",
            industry_code="RETAIL",
            onsite_nights_per_week=2,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=240.00,
        )
        return world, ada, turing, demand

    def test_five_weighted_components_plus_the_certification_bonus(self, api):
        """PRD §3.5: "The components are then combined at fixed weights: the skill
        component at 0.35, the industry component at 0.15, the development-goal
        component at 0.15, the travel component at 0.20 and the cost component at
        0.15 — five weights summing to exactly 1.00. To that sum a certification
        bonus of 0.10 is added whenever the reference assertion carries a
        `certification_code` and its `assertion_status` is `ACTIVE`, and nothing is
        added otherwise."

        Design: Difficulty/combinatorial_formula/match_score_six_input_nonlinear_with_cost_clamp
        """
        _, ada, turing, demand = self._pool(api)

        assert ada["assertion"]["assertion_status"] == "ACTIVE"

        ada_assignment = fixtures.propose_assignment(
            api,
            ada["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        turing_assignment = fixtures.propose_assignment(
            api,
            turing["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )

        # 0.35*0.8000 + 0.15*1.0000 + 0.15*1.0000 + 0.20*0.6000 + 0.15*0.5200
        # = 0.7780, plus the 0.10 certification bonus.
        assert ada_assignment["match_score"] == pytest.approx(0.8780, abs=0.00005)
        # 0.35*1.0000 + 0.15*0.0000 + 0.15*0.0000 + 0.20*0.6000 + 0.15*0.0000
        # = 0.4700, with no bonus because the assertion carries no certification.
        assert turing_assignment["match_score"] == pytest.approx(0.4700, abs=0.00005)
        assert ada_assignment["match_score"] - turing_assignment[
            "match_score"
        ] == pytest.approx(0.4080, abs=0.00005)

        # A proposal reserves nothing, so neither score came from a side effect.
        assert ada_assignment["status"] == AssignmentStatus.PROPOSED
        assert turing_assignment["status"] == AssignmentStatus.PROPOSED

    def test_the_cost_component_clamps_below_at_zero_not_into_negatives(self, api):
        """PRD §3.5: "The cost component is the demand's
        `standard_rate_usd_per_hour` less the consultant's
        `cost_rate_usd_per_hour`, divided by that same standard rate, clamped below
        at 0.0000 and above at 1.0000 — the lower clamp meaning every consultant
        costing at or above the demand's standard rate scores identically here."

        Design: Difficulty/combinatorial_formula/match_score_six_input_nonlinear_with_cost_clamp
        """
        world, _, turing, demand = self._pool(api)
        at_the_rate = fixtures.hire(
            api,
            world,
            full_name="Even Money",
            proficiency_level=5,
            cost_rate_usd_per_hour=250.00,
            standard_bill_rate_usd_per_hour=500.00,
            travel_max_nights_per_week=3,
        )

        above = fixtures.propose_assignment(
            api,
            turing["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        exactly_at = fixtures.propose_assignment(
            api,
            at_the_rate["consultant"]["id"],
            demand["id"],
            allocation_pct=50.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )

        # 300.00 is above the 250.00 standard rate and 250.00 is exactly on it:
        # the raw ratios are -0.2000 and 0.0000, and both land on 0.0000.
        assert exactly_at["match_score"] == pytest.approx(0.4700, abs=0.00005)
        assert above["match_score"] == pytest.approx(
            exactly_at["match_score"], abs=0.00005
        )


class TestForecastPerDemandRounding:
    @staticmethod
    def _three_quarter_fte_demands(api):
        """Three 0.25 FTE demands at a 33 percent win probability, no supply."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        demands = []
        for client in ("Tail One", "Tail Two", "Tail Three"):
            demands.append(
                fixtures.qualified_demand(
                    api,
                    world,
                    staffing_mode=None,
                    client_name=client,
                    required_fte=0.25,
                    win_probability_pct=33,
                    start_date="2026-09-01",
                    end_date="2026-12-15",
                    standard_rate_usd_per_hour=250.00,
                    requested_rate_usd_per_hour=250.00,
                )
            )
        return world, demands

    def test_each_demand_rounds_before_the_sum_so_the_total_is_zero_point_two_four(
        self, api
    ):
        """PRD §3.9: "That per-demand rounding is normative and observable: three
        demands of 0.25 FTE each at a 33 percent win probability contribute 0.08
        apiece for a total of 0.24, not the 0.25 that summing the raw products and
        rounding once would report."

        Design: Difficulty/combinatorial_formula/forecast_round_per_opportunity_then_sum
        """
        _, demands = self._three_quarter_fte_demands(api)

        for demand in demands:
            assert demand["weighted_fte"] == pytest.approx(0.08, abs=0.005)

        forecast = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-01",
            horizon_end_on="2026-12-31",
            basis=ForecastBasis.WEIGHTED,
        )
        assert_hiring_forecast(forecast)

        assert forecast["weighted_demand_fte"] == pytest.approx(0.24, abs=0.005)
        # 0.2475 summed first and rounded once would have reported 0.25.
        assert forecast["weighted_demand_fte"] != pytest.approx(0.25, abs=0.001)
        assert forecast["internal_supply_fte"] == pytest.approx(0.00, abs=0.005)
        assert forecast["external_supply_fte"] == pytest.approx(0.00, abs=0.005)
        assert forecast["gap_fte"] == pytest.approx(0.24, abs=0.005)

    def test_the_ceiling_runs_on_the_already_rounded_gap(self, api):
        """PRD §3.9: "A gap of 0.24 FTE therefore still recommends one hire, and a
        gap of 1.30 FTE recommends two, because 1.30 divided by 0.85 is 1.5294 and
        the ceiling of that is 2."

        Design: Difficulty/combinatorial_formula/forecast_round_per_opportunity_then_sum
        """
        _, _ = self._three_quarter_fte_demands(api)

        small_gap = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-01",
            horizon_end_on="2026-12-31",
            basis=ForecastBasis.WEIGHTED,
        )
        # ceil(0.24 / 0.85) is 1; rounding 0.2824 to the nearest whole number
        # would have reported 0.
        assert small_gap["gap_fte"] == pytest.approx(0.24, abs=0.005)
        assert small_gap["recommended_hires"] == 1

    def test_a_one_point_three_gap_recommends_two_hires(self, api):
        """PRD §3.9: "The `recommended_hires` figure is 0 whenever `gap_fte` is 0.00
        or negative, and otherwise `gap_fte` divided by the 0.85 expected yield per
        hire, **rounded up to the next whole number** — half a recruit cannot be
        hired."

        Design: Difficulty/combinatorial_formula/forecast_round_per_opportunity_then_sum
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        certain = fixtures.qualified_demand(
            api,
            world,
            staffing_mode=None,
            client_name="Certain Bank",
            required_fte=1.00,
            win_probability_pct=100,
            start_date="2026-09-01",
            end_date="2026-12-15",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        coin_flip = fixtures.qualified_demand(
            api,
            world,
            staffing_mode=None,
            client_name="Coin Flip Retail",
            required_fte=0.60,
            win_probability_pct=50,
            start_date="2026-09-01",
            end_date="2026-12-15",
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )

        assert certain["weighted_fte"] == pytest.approx(1.00, abs=0.005)
        assert coin_flip["weighted_fte"] == pytest.approx(0.30, abs=0.005)

        forecast = fixtures.create_forecast(
            api,
            skill_code="CLOUD_ARCH",
            geography_code="NA",
            horizon_start_on="2026-08-01",
            horizon_end_on="2026-12-31",
            basis=ForecastBasis.WEIGHTED,
        )
        assert forecast["weighted_demand_fte"] == pytest.approx(1.30, abs=0.005)
        assert forecast["gap_fte"] == pytest.approx(1.30, abs=0.005)
        assert forecast["recommended_hires"] == 2


class TestDiscountSinglePassOrdering:
    @staticmethod
    def _staffed_demand_at_the_margin_floor(api):
        """A 200.00-cost consultant confirmed at the list rate of 250.00, which is
        exactly the 20.00 percent margin floor."""
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        staff = fixtures.hire(
            api,
            world,
            full_name="Pricey Principal",
            proficiency_level=4,
            cost_rate_usd_per_hour=200.00,
            standard_bill_rate_usd_per_hour=400.00,
            travel_max_nights_per_week=3,
        )
        demand = fixtures.qualified_demand(
            api,
            world,
            min_proficiency_level=3,
            required_fte=1.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )
        assignment = fixtures.confirmed_assignment(
            api,
            staff["consultant"]["id"],
            demand["id"],
            allocation_pct=100.00,
            start_date="2026-08-03",
            end_date="2026-08-29",
        )
        return world, staff, demand, assignment

    def test_the_fiscal_override_runs_before_the_auto_approval_step(self, api):
        """PRD §3.7: "The sixth step is a fiscal override: when
        `projected_margin_pct` is below the 20.00 percent margin floor and
        `required_tier` is not already `L2_FINANCE`, the tier is rewritten to
        `L2_FINANCE` and `tier_escalated` is set to true; otherwise `tier_escalated`
        stays false."

        Design: Difficulty/combinatorial_formula/discount_tier_escalation_single_pass_evaluation_order
        """
        _, _, demand, _ = self._staffed_demand_at_the_margin_floor(api)

        approval = fixtures.request_discount(
            api,
            demand["id"],
            240.00,
            decision_note="small trim to win the renewal",
        )

        assert approval["standard_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)
        assert approval["discount_pct"] == pytest.approx(4.00, abs=0.01)
        assert approval["provisional_realization_pct"] == pytest.approx(96.00, abs=0.01)
        # A CONFIRMED assignment exists, so the mix-weighted variant reads the real
        # 200.00 staffed cost rather than the level-floor proxy.
        assert approval["blended_cost_rate_usd_per_hour"] == pytest.approx(
            200.00, abs=0.01
        )
        assert approval["projected_margin_pct"] == pytest.approx(16.67, abs=0.01)
        # A 4.00 percent discount alone routes to NONE; the fiscal override rewrites it.
        assert approval["required_tier"] == ApprovalTier.L2_FINANCE
        assert approval["tier_escalated"] is True
        assert approval["status"] == ApprovalStatus.PENDING
        assert approval["decided_by_user_id"] is None
        assert approval["revision_count"] == 0

    def test_an_escalated_request_leaves_the_demands_rate_cascade_alone(self, api):
        """PRD §3.7: "The ordering of those last two steps is the whole point of the
        design. A four-percent discount that projects a 16.67 percent margin is
        escalated to `L2_FINANCE` by the sixth step and therefore does **not**
        auto-approve at the seventh, even though its discount alone would have needed
        no approval whatsoever."

        Design: Difficulty/combinatorial_formula/discount_tier_escalation_single_pass_evaluation_order
        """
        _, _, demand, assignment = self._staffed_demand_at_the_margin_floor(api)

        fixtures.request_discount(
            api,
            demand["id"],
            240.00,
            decision_note="small trim to win the renewal",
        )

        after = fixtures.read_demand(api, demand["id"])
        assert after["approved_rate_usd_per_hour"] is None
        assert after["effective_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)
        assert after["booked_realization_pct"] == pytest.approx(100.00, abs=0.01)

        still_pinned = fixtures.read_assignment(api, assignment["id"])
        assert still_pinned["bill_rate_usd_per_hour"] == pytest.approx(250.00, abs=0.01)

    def test_the_same_discount_auto_approves_under_the_level_floor_proxy(self, api):
        """PRD §3.7: "The seventh step decides the row's `status`: when
        `required_tier` came out of the sixth step as `NONE`, the approval is created
        already `APPROVED` with `decided_by_user_id` set to the literal string
        `SYSTEM_AUTO` and the demand's full rate cascade is applied immediately; in
        every other case the row is created `PENDING`."

        Design: Difficulty/combinatorial_formula/discount_tier_escalation_single_pass_evaluation_order
        """
        world = fixtures.base_world(api, clock=INSTANT_AUG_03)
        demand = fixtures.qualified_demand(
            api,
            world,
            min_proficiency_level=3,
            required_fte=1.00,
            standard_rate_usd_per_hour=250.00,
            requested_rate_usd_per_hour=250.00,
        )

        approval = fixtures.request_discount(api, demand["id"], 240.00)

        # No CONFIRMED or ACTIVE assignment exists, so the level-floor proxy for
        # min_proficiency_level 3 supplies 80.00 and the margin clears the floor.
        assert approval["discount_pct"] == pytest.approx(4.00, abs=0.01)
        assert approval["blended_cost_rate_usd_per_hour"] == pytest.approx(80.00, abs=0.01)
        assert approval["projected_margin_pct"] == pytest.approx(66.67, abs=0.01)
        assert approval["required_tier"] == ApprovalTier.NONE
        assert approval["tier_escalated"] is False
        assert approval["status"] == ApprovalStatus.APPROVED
        assert approval["decided_by_user_id"] == SYSTEM_AUTO_USER_ID

        cascaded = fixtures.read_demand(api, demand["id"])
        assert cascaded["approved_rate_usd_per_hour"] == pytest.approx(240.00, abs=0.01)
        assert cascaded["effective_rate_usd_per_hour"] == pytest.approx(240.00, abs=0.01)
        assert cascaded["booked_realization_pct"] == pytest.approx(96.00, abs=0.01)
