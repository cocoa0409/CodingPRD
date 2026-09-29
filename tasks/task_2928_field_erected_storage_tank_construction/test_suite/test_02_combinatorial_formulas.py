"""Composite formulas whose result depends on which operand or branch wins.

The one-foot method takes a three-way maximum where the third candidate is a
diameter table lookup; the hydrotest cost chain rounds per withdrawal before it
sums and keys its surcharge tier on the subtotal rather than the total.
"""

import pytest

from test_helpers import fixtures as X
from test_helpers.assertions import assert_money, assert_source_ledger, assert_thickness
from test_helpers.constants import (
    DISPOSAL_DISCHARGE_TO_POTW,
    DISPOSAL_HAUL_OFFSITE,
    GOVERNING_DESIGN,
    GOVERNING_MIN_NOMINAL,
    GOVERNING_TEST,
    THICKNESS_ADEQUATE,
)


class TestShellThicknessThreeWayMax:
    def test_the_design_case_wins_and_the_elevation_stack_shifts_the_head(self, api):
        """A heavy product with a corrosion allowance makes the design case govern.

        PRD: "The governing requirement, `required_thickness_in`, is the largest of
        three candidates: the rounded design-condition thickness, the rounded
        test-condition thickness, and the tank's `min_nominal_thickness_in`
        diameter floor from §3.1"

        Design: Difficulty/combinatorial_formula/shell_thickness_three_way_max_with_diameter_tier
        """
        X.set_clock(api, "2026-08-10T00:00:00Z")
        tank = X.create_tank(api, tank_tag="TK-101", product_specific_gravity=0.85,
                            corrosion_allowance_in=0.0625)
        assert_thickness(tank["min_nominal_thickness_in"], 0.250, "100 ft floor")

        bottom = X.create_course(api, tank["id"], course_number=1)
        upper = X.create_course(api, tank["id"], course_number=2)

        assert bottom["course_bottom_elevation_ft"] == pytest.approx(0.0)
        assert bottom["design_liquid_height_ft"] == pytest.approx(40.0)
        assert_thickness(bottom["required_thickness_design_in"], 0.434, "bottom design")
        assert_thickness(bottom["required_thickness_test_in"], 0.407, "bottom test")
        assert_thickness(bottom["required_thickness_in"], 0.434, "bottom governing")
        assert bottom["governing_case"] == GOVERNING_DESIGN
        assert bottom["thickness_verdict"] == THICKNESS_ADEQUATE

        assert upper["course_bottom_elevation_ft"] == pytest.approx(8.0)
        assert upper["design_liquid_height_ft"] == pytest.approx(32.0)
        assert_thickness(upper["required_thickness_design_in"], 0.358, "upper design")
        assert_thickness(upper["required_thickness_test_in"], 0.324, "upper test")
        assert_thickness(upper["required_thickness_in"], 0.358, "upper governing")
        assert upper["governing_case"] == GOVERNING_DESIGN

    def test_the_hydrostatic_test_case_wins_when_the_allowance_is_dropped(self, api):
        """A light product with no corrosion allowance puts the test case on top.

        PRD: "with no specific gravity term, because the test medium is water, and
        with **no corrosion allowance added**."

        Design: Difficulty/combinatorial_formula/shell_thickness_three_way_max_with_diameter_tier
        """
        X.set_clock(api, "2026-08-10T00:00:00Z")
        tank = X.create_tank(api, tank_tag="TK-102", product_specific_gravity=0.70,
                             corrosion_allowance_in=0.0)

        course = X.create_course(api, tank["id"], course_number=1)

        assert_thickness(course["required_thickness_design_in"], 0.306, "design case")
        assert_thickness(course["required_thickness_test_in"], 0.407, "test case")
        assert_thickness(course["required_thickness_in"], 0.407, "governing")
        assert course["governing_case"] == GOVERNING_TEST

    def test_the_diameter_tier_floor_wins_on_a_small_shallow_tank(self, api):
        """Both loading cases fall under the small-diameter nominal floor.

        PRD: "below 50 feet the floor is 0.188 inches"

        Design: Difficulty/combinatorial_formula/shell_thickness_three_way_max_with_diameter_tier
        """
        X.set_clock(api, "2026-08-10T00:00:00Z")
        tank = X.create_tank(api, tank_tag="TK-103", diameter_ft=30.0, shell_height_ft=12.0,
                             design_liquid_level_ft=12.0)
        assert_thickness(tank["min_nominal_thickness_in"], 0.188, "30 ft floor")

        course = X.create_course(api, tank["id"], course_number=1, course_width_ft=6.0,
                                 plate_thickness_in=0.250, material_spec="A36")

        assert_thickness(course["required_thickness_design_in"], 0.094, "design case")
        assert_thickness(course["required_thickness_test_in"], 0.034, "test case")
        assert_thickness(course["required_thickness_in"], 0.188, "governing")
        assert course["governing_case"] == GOVERNING_MIN_NOMINAL
        assert course["thickness_verdict"] == THICKNESS_ADEQUATE


class TestWaterCostRoundThenSum:
    def test_each_withdrawal_is_rounded_before_the_plan_sums_them(self, api):
        """Three 125,555 gallon draws sum to a cent above the single-round figure.

        PRD: "The plan's `water_cost_usd` is then the **sum of those
        already-rounded per-withdrawal amounts**, taken over every withdrawal of
        the plan whose `status` is `RESERVED` or `CONSUMED`, processed in
        `created_at` order."

        Design: Difficulty/combinatorial_formula/water_cost_round_per_withdrawal_then_sum
        """
        X.set_clock(api, "2026-08-10T00:00:00Z")
        tank = X.create_tank(api)
        source = X.create_water_source(api)
        plan = X.create_plan(api, tank["id"], source["id"], fill_volume_gal=376665.0,
                             disposal_method=DISPOSAL_DISCHARGE_TO_POTW)

        draws = []
        for hour in (0, 6, 12):
            draws.append(
                X.reserve_withdrawal(
                    api,
                    plan["id"],
                    source["id"],
                    window_start_utc=f"2026-08-11T{hour:02d}:00:00Z",
                    window_end_utc=f"2026-08-11T{hour + 6:02d}:00:00Z",
                    rate_gpm=300.0,
                    reserved_volume_gal=125555.0,
                )
            )

        for index, draw in enumerate(draws):
            assert_money(draw["withdrawal_cost_usd"], 418.10, f"withdrawal {index}")

        plan = X.read_plan(api, plan["id"])
        assert_money(plan["water_cost_usd"], 1254.30, "water cost")
        assert plan["water_cost_usd"] != pytest.approx(1254.29, abs=1e-9)

    def test_disposal_is_priced_once_on_the_unsplit_aggregate_volume(self, api):
        """The disposal leg ignores the split and prices the whole reserved volume.

        PRD: "Disposal is priced once, on the plan's aggregate volume."

        Design: Difficulty/combinatorial_formula/water_cost_round_per_withdrawal_then_sum
        """
        X.set_clock(api, "2026-08-10T00:00:00Z")
        tank = X.create_tank(api)
        source = X.create_water_source(api)
        plan = X.create_plan(api, tank["id"], source["id"], fill_volume_gal=376665.0,
                             disposal_method=DISPOSAL_DISCHARGE_TO_POTW)
        for hour in (0, 6, 12):
            X.reserve_withdrawal(
                api,
                plan["id"],
                source["id"],
                window_start_utc=f"2026-08-11T{hour:02d}:00:00Z",
                window_end_utc=f"2026-08-11T{hour + 6:02d}:00:00Z",
                rate_gpm=300.0,
                reserved_volume_gal=125555.0,
            )

        plan = X.read_plan(api, plan["id"])
        assert_money(plan["disposal_cost_usd"], 791.00, "disposal cost")
        assert_money(plan["subtotal_usd"], 2045.30, "subtotal")

        assert_source_ledger(
            X.read_water_source(api, source["id"]),
            reserved=376665.00,
            consumed=0.00,
            available=1623335.00,
        )


class TestPermitSurchargeTierSelector:
    def _plan_with_single_large_draw(self, api):
        X.set_clock(api, "2026-08-10T00:00:00Z")
        tank = X.create_tank(api)
        source = X.create_water_source(api)
        plan = X.create_plan(api, tank["id"], source["id"], fill_volume_gal=360000.0,
                             disposal_method=DISPOSAL_HAUL_OFFSITE)
        draw = X.reserve_withdrawal(
            api,
            plan["id"],
            source["id"],
            window_start_utc="2026-08-11T00:00:00Z",
            window_end_utc="2026-08-11T20:00:00Z",
            rate_gpm=300.0,
            reserved_volume_gal=360000.0,
        )
        return X.read_plan(api, plan["id"]), draw

    def test_the_surcharge_tier_is_selected_from_the_subtotal_alone(self, api):
        """A subtotal just under 2000.00 keeps the middle band even though the total clears it.

        PRD: "The permit surcharge is then selected from the subtotal, and only
        from the subtotal, so that the surcharge is never compounded on itself."

        Design: Difficulty/combinatorial_formula/permit_surcharge_tier_keyed_on_subtotal_not_total
        """
        plan, draw = self._plan_with_single_large_draw(api)

        assert_money(draw["withdrawal_cost_usd"], 1198.80, "withdrawal cost")
        assert_money(plan["water_cost_usd"], 1198.80, "water cost")
        assert_money(plan["disposal_cost_usd"], 756.00, "disposal cost")
        assert_money(plan["subtotal_usd"], 1954.80, "subtotal")
        assert plan["permit_surcharge_pct"] == pytest.approx(0.03, abs=1e-9)

    def test_the_total_clears_the_boundary_the_tier_selector_ignores(self, api):
        """The stored total exceeds 2000.00 yet was charged at the 0.03 band.

        PRD: "`total_cost_usd` is `subtotal_usd` plus `surcharge_usd`."

        Design: Difficulty/combinatorial_formula/permit_surcharge_tier_keyed_on_subtotal_not_total
        """
        plan, _ = self._plan_with_single_large_draw(api)

        assert_money(plan["surcharge_usd"], 58.64, "surcharge")
        assert_money(plan["total_cost_usd"], 2013.44, "total")
        assert plan["total_cost_usd"] > 2000.00
        assert plan["total_cost_usd"] != pytest.approx(2052.54, abs=1e-9)
