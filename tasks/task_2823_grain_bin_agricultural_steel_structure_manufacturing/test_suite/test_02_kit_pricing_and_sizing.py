"""The kit bill of materials, the eight-step price build-up, and the aeration,
drying and discharge sizing pass."""

import pytest
from test_helpers import (
    PLANNER,
    assert_dealer_order,
    assert_kit_lines_in_component_order,
    assert_order_price_buildup,
    create_design,
    dealer_headers,
    place_order,
    read_dealer,
    set_clock,
    setup_reference_data,
    validate_error,
    validate_paginated,
)


def kit_lines(api, order_id):
    """The order's bill of materials as (ordered rows, {component_code: row}, total_count)."""
    rows, meta = validate_paginated(
        api.list_kit_lines(order_id, PLANNER, {"limit": 10, "offset": 0})
    )
    assert_kit_lines_in_component_order(rows)
    return rows, {row["component_code"]: row for row in rows}, meta["total_count"]


class TestBoltPackCeilsPerCourseThenSums:
    def test_thirty_six_packs_are_emitted_because_the_ceiling_is_taken_per_course(self, api):
        """PRD §3.4: "A seam takes 18 bolts and a pack holds 250 bolts, so the plant computes
        the packs needed for a **single course** — the design's `sheets_per_course` multiplied
        by 18, divided by 250, taken up to the next whole pack — and then multiplies that
        per-course pack count by the design's `sheet_courses`."
        PRD §3.4: "The alternative reading, which multiplies sheets per course by courses first
        and only then takes the whole-pack ceiling, yields a strictly smaller pack count for
        the same bin and is **not** the plant's method. Ceiling first, multiply second."

        Design: Difficulty/combinatorial_formula/bolt_pack_count_ceils_per_course_then_sums
        """
        ref = setup_reference_data()
        design = create_design(ref)
        assert design["sheets_per_course"] == 35
        assert design["sheet_courses"] == 12
        assert design["sidewall_sheet_count"] == 420
        assert design["required_stiffener_count"] == 12

        order = place_order(ref, design)
        assert_dealer_order(order)

        rows, by_code, total = kit_lines(api, order["id"])
        pack = by_code["BOLT_PACK"]
        # ceil(35 x 18 / 250) = 3 packs per course, x 12 courses = 36.  The forbidden
        # sum-then-ceil reading is ceil(420 x 18 / 250) = 31 packs.
        assert pack["quantity"] == 36
        assert pack["quantity"] != 31
        assert pack["unit_price_cents"] == 2152
        assert pack["extended_cents"] == 77472
        assert pack["extended_cents"] - 66712 == 10760
        assert pack["weight_kg"] == pytest.approx(216.0, abs=1e-9)

        assert by_code["SIDEWALL_SHEET"]["quantity"] == 420
        assert by_code["ANCHOR_BOLT"]["quantity"] == 48
        assert total == 5
        assert "AERATION_FAN" not in by_code
        assert "UNLOAD_SYSTEM" not in by_code
        assert [row["component_code"] for row in rows] == [
            "SIDEWALL_SHEET",
            "STIFFENER",
            "ROOF_PANEL",
            "ANCHOR_BOLT",
            "BOLT_PACK",
        ]

        assert order["kit_subtotal_cents"] == 2392026
        assert order["kit_weight_kg"] == pytest.approx(6410.4, abs=1e-9)

    def test_the_coating_adder_is_rounded_per_component_before_the_quantity_multiplies_it(
        self, api
    ):
        """PRD §3.4: "The `unit_price_cents` is therefore the base price plus that rounded
        per-unit adder for steel components, and the base price alone for the other two."
        PRD §3.4: "The rounding order here is also pinned and observable: the adder is rounded
        per component code and only then multiplied by quantity through `extended_cents`,
        which is the `quantity` multiplied by the `unit_price_cents`. Multiplying an unrounded
        adder by the quantity and rounding the extended amount is the forbidden alternative."
        PRD §3.4: "A kit line is emitted only for components whose quantity is 1 or more, and
        the emitted lines appear in the fixed component order above; a gravity-discharge bin
        with no aeration therefore has five lines, not seven."

        Design: Difficulty/combinatorial_formula/bolt_pack_count_ceils_per_course_then_sums
        """
        ref = setup_reference_data()
        design = create_design(ref)
        order = place_order(ref, design)

        rows, by_code, total = kit_lines(api, order["id"])
        assert total == 5

        # G115 charges 42 cents per kilogram of galvanised steel.
        assert by_code["SIDEWALL_SHEET"]["unit_price_cents"] == 4725
        assert by_code["SIDEWALL_SHEET"]["extended_cents"] == 1984500
        assert by_code["STIFFENER"]["unit_price_cents"] == 11522
        assert by_code["ROOF_PANEL"]["unit_price_cents"] == 3995
        assert by_code["ANCHOR_BOLT"]["unit_price_cents"] == 500
        assert by_code["BOLT_PACK"]["unit_price_cents"] == 2152

        for row in rows:
            assert row["extended_cents"] == row["quantity"] * row["unit_price_cents"]
            assert row["dealer_order_id"] == order["id"]

        assert sum(row["extended_cents"] for row in rows) == order["kit_subtotal_cents"]
        assert order["kit_subtotal_cents"] == 2392026


class TestAerationCfmNestedFactors:
    def test_all_four_airflow_factors_multiply_before_the_cap_and_the_ceiling(self, api):
        """PRD §3.5: "The base airflow is the design's `capacity_m3` multiplied by the profile's
        `aeration_cfm_per_m3_base`. The package multiplier is 0.0 for `NONE`, exactly 1.0 for
        `AERATION`, and the profile's `drying_multiplier` for `DRYING_FULL`. A depth penalty
        accounts for the resistance of a deep grain column: it is 1 plus 0.03 for every metre
        by which the design's `eave_height_m` exceeds 8.0 metres, with the excess taken as zero
        for a bin of 8.0 metres or shorter. A moisture penalty accounts for wet grain: it is 1
        plus 0.12 for every percentage point by which the design's `moisture_pct` exceeds the
        profile's `max_safe_moisture_pct`, again with the excess taken as zero when the design
        moisture is at or below the safe threshold."
        PRD §3.5: "The stored `required_fan_cfm` is that raw requirement first capped at 60000
        cubic feet per minute and only then taken up to the next whole number"

        Design: Difficulty/combinatorial_formula/aeration_cfm_nested_min_max_with_moisture_and_depth_penalties
        """
        ref = setup_reference_data()
        design = create_design(ref, eave_height_m=12.8, moisture_pct=17.5)
        assert design["capacity_m3"] == pytest.approx(1578.16, abs=1e-9)
        assert design["sheet_courses"] == 16
        assert design["sheets_per_course"] == 35
        assert design["required_stiffener_count"] == 17
        assert design["roof_panel_count"] == 42

        order = place_order(
            ref, design, aeration_package="DRYING_FULL", unload_system="POWER_SWEEP"
        )
        assert order["grain_mass_kg"] == pytest.approx(1137853.36, abs=1e-9)
        # 1578.16 x 2.5 x 4.0 x 1.144 x 1.30 = 23470.3955 -> 23471.
        assert order["required_fan_cfm"] == 23471
        # Dropping the moisture penalty alone would yield 18055; dropping the depth
        # penalty alone would yield 20517.  Both readings are falsified.
        assert order["required_fan_cfm"] not in (18055, 20517)
        assert order["drying_hours_estimate"] == 7878
        assert order["unload_rate_bph"] == 9000

        _rows, by_code, total = kit_lines(api, order["id"])
        assert total == 7
        assert by_code["AERATION_FAN"]["quantity"] == 5
        assert by_code["AERATION_FAN"]["extended_cents"] == 1425000
        assert by_code["UNLOAD_SYSTEM"]["quantity"] == 1
        assert by_code["UNLOAD_SYSTEM"]["extended_cents"] == 412000

    def test_the_drying_estimate_divides_by_the_already_ceiled_fan_demand(self, api):
        """PRD §3.5: "When there is any moisture excess, the numerator is inflated first: the
        `grain_mass_kg` is multiplied by 1 plus 0.25 for each percentage point of moisture
        excess, and that inflated mass is then divided by the same product of
        `required_fan_cfm` and 0.010 and taken up to the next whole hour."
        PRD §3.4: "the aeration fan quantity is zero when no aeration is ordered and otherwise
        the order's `required_fan_cfm` divided by the 5000 cubic-feet-per-minute rating of one
        fan unit, taken up to the next whole fan"
        PRD §3.4: "`kit_weight_kg` is the sum of the lines' `weight_kg` rounded half up to 2
        decimal places, and `kit_cube_m3` is the sum of the lines' `cube_m3` rounded half up to
        3 decimal places"

        Design: Difficulty/combinatorial_formula/aeration_cfm_nested_min_max_with_moisture_and_depth_penalties
        """
        ref = setup_reference_data()
        design = create_design(ref, eave_height_m=12.8, moisture_pct=17.5)
        order = place_order(
            ref, design, aeration_package="DRYING_FULL", unload_system="POWER_SWEEP"
        )

        # Moisture excess is 2.5 points, so the mass is inflated by 1.625 before it is
        # divided by 23471 x 0.010 and taken up to the next whole hour.
        assert order["required_fan_cfm"] == 23471
        assert order["drying_hours_estimate"] == 7878

        _rows, by_code, _total = kit_lines(api, order["id"])
        assert by_code["AERATION_FAN"]["quantity"] == 5
        assert by_code["AERATION_FAN"]["weight_kg"] == pytest.approx(600.0, abs=1e-9)
        assert by_code["AERATION_FAN"]["cube_m3"] == pytest.approx(9.5, abs=1e-9)

        assert order["kit_subtotal_cents"] == 4983960
        assert order["kit_weight_kg"] == pytest.approx(9401.4, abs=1e-9)
        assert order["kit_cube_m3"] == pytest.approx(37.129, abs=1e-9)


class TestFreightSurchargeTierKeyedOnNetSubtotal:
    def test_the_band_follows_the_net_subtotal_even_when_the_total_crosses_the_next_edge(
        self, api
    ):
        """PRD §3.4: "The tier is keyed on `net_subtotal_cents` and never on `total_cents`, and
        `net_subtotal_cents` is fully determined at step four. The bands are half-open: a
        `net_subtotal_cents` below 2000000 selects a `freight_surcharge_pct` of 0.060; a
        `net_subtotal_cents` at or above 2000000 but below 6000000 selects 0.045; and a
        `net_subtotal_cents` at or above 6000000 selects 0.030."
        PRD §3.4: "Step six computes `freight_surcharge_cents` as the `net_subtotal_cents`
        multiplied by the selected `freight_surcharge_pct`, rounded half up to whole cents. Step
        seven sets `total_cents` to `net_subtotal_cents` plus `freight_surcharge_cents`."

        Design: Difficulty/combinatorial_formula/order_freight_surcharge_tier_keyed_on_net_subtotal_not_on_total
        """
        ref = setup_reference_data()
        design = create_design(
            ref, dealer="pinnacle", diameter_m=15.5, eave_height_m=12.0
        )
        assert design["circumference_m"] == pytest.approx(48.695, abs=1e-9)
        assert design["capacity_m3"] == pytest.approx(2545.56, abs=1e-9)
        assert design["sheet_courses"] == 15
        assert design["sheets_per_course"] == 45
        assert design["sidewall_sheet_count"] == 675
        assert design["roof_panel_count"] == 55
        assert design["required_stiffener_count"] == 20
        assert design["sheet_gauge_mm"] == pytest.approx(2.0, abs=1e-9)

        order = place_order(
            ref,
            design,
            dealer="pinnacle",
            aeration_package="DRYING_FULL",
            unload_system="SWEEP_AUGER",
        )
        assert order["kit_subtotal_cents"] == 5930660
        assert order["season_uplift_cents"] == 0
        assert order["program_discount_cents"] == 177920
        assert order["net_subtotal_cents"] == 5752740
        assert order["freight_surcharge_pct"] == pytest.approx(0.045, abs=1e-9)
        assert order["freight_surcharge_cents"] == 258873
        assert order["total_cents"] == 6011613

        # The total lands in the 0.030 band, yet the rate stays keyed on the net subtotal.
        assert order["total_cents"] >= 6000000
        assert order["net_subtotal_cents"] < 6000000
        assert order["freight_surcharge_pct"] != pytest.approx(0.030, abs=1e-9)
        assert order["freight_surcharge_cents"] != 172582
        assert order["total_cents"] != 5925322

    def test_the_deposit_and_hold_close_the_ladder_and_pricing_alone_commits_no_credit(
        self, api
    ):
        """PRD §3.4: "Step eight computes `required_deposit_cents` as twenty percent of
        `total_cents`, rounded half up to whole cents, and sets `credit_hold_cents` to
        `total_cents` minus `required_deposit_cents`. Every money step rounds independently to
        whole cents and no step consumes an unrounded intermediate from an earlier step."
        PRD §3.5: "With `SWEEP_AUGER` it is a flat 5000 bushels per hour, and with
        `POWER_SWEEP` a flat 9000 bushels per hour."
        PRD §3.4: "A fresh order begins with `production_status` `DRAFT`, `financial_status`
        `AWAITING_DEPOSIT` and `installation_readiness` `UNASSIGNED`, with `freight_load_id` and
        `installation_crew_id` both null, `deposit_paid_cents` 0, `allocated_freight_cents` 0
        and `freight_sequence` null."

        Design: Difficulty/combinatorial_formula/order_freight_surcharge_tier_keyed_on_net_subtotal_not_on_total
        """
        ref = setup_reference_data()
        design = create_design(
            ref, dealer="pinnacle", diameter_m=15.5, eave_height_m=12.0
        )
        order = place_order(
            ref,
            design,
            dealer="pinnacle",
            aeration_package="DRYING_FULL",
            unload_system="SWEEP_AUGER",
        )
        assert_order_price_buildup(order)
        assert order["required_deposit_cents"] == 1202323
        assert order["credit_hold_cents"] == 4809290
        assert order["required_fan_cfm"] == 28511
        assert order["unload_rate_bph"] == 5000

        assert order["production_status"] == "DRAFT"
        assert order["financial_status"] == "AWAITING_DEPOSIT"
        assert order["installation_readiness"] == "UNASSIGNED"
        assert order["freight_load_id"] is None
        assert order["installation_crew_id"] is None
        assert order["deposit_paid_cents"] == 0
        assert order["allocated_freight_cents"] == 0
        assert order["freight_sequence"] is None

        assert read_dealer(ref["pinnacle"]["id"])["credit_committed_cents"] == 0


class TestAerationDemandPenaltiesThenCeil:
    def test_a_deep_wet_rice_bin_ceils_to_eighteen_thousand_cfm_and_four_fans(self, api):
        """PRD §3.5: "The raw requirement is the base airflow multiplied by the package
        multiplier, by the depth penalty and by the moisture penalty."
        PRD §3.5: "The stored mass comes first: `grain_mass_kg` is the design's `capacity_m3`
        multiplied by the grain profile's `bulk_density_kg_per_m3`, rounded half up to 2 decimal
        places."
        PRD §3.4: "The aeration fan and the unload system carry no coating adder at all, since
        neither is galvanized sheet."

        Design: Corner/calculations/aeration_demand_multiplies_the_package_by_the_depth_and_moisture_penalties_then_ceils
        """
        ref = setup_reference_data()
        design = create_design(
            ref,
            jurisdiction="IA-CENTRAL",
            grain_profile="RICE",
            diameter_m=15.5,
            eave_height_m=15.2,
            design_wind_speed_mph=110,
            moisture_pct=17.0,
        )
        assert design["capacity_m3"] == pytest.approx(3149.38, abs=1e-9)
        assert design["moisture_factor"] == pytest.approx(1.16, abs=1e-9)
        assert design["grain_demand_kpa"] == pytest.approx(39.533, abs=1e-9)
        assert design["required_stiffener_count"] == 22
        assert design["utilization_ratio"] == pytest.approx(0.9723, abs=1e-9)
        assert design["sheet_gauge_mm"] == pytest.approx(2.0, abs=1e-9)

        order = place_order(
            ref, design, aeration_package="AERATION", unload_system="SWEEP_AUGER"
        )
        assert order["grain_mass_kg"] == pytest.approx(1823491.02, abs=1e-9)
        assert order["required_fan_cfm"] == 18138
        assert order["required_fan_cfm"] < 60000
        assert order["drying_hours_estimate"] == 20107
        assert order["unload_rate_bph"] == 5000

        _rows, by_code, total = kit_lines(api, order["id"])
        assert total == 7
        assert by_code["AERATION_FAN"]["quantity"] == 4
        assert by_code["AERATION_FAN"]["unit_price_cents"] == 285000
        assert by_code["AERATION_FAN"]["extended_cents"] == 1140000
        assert by_code["UNLOAD_SYSTEM"]["quantity"] == 1
        assert by_code["UNLOAD_SYSTEM"]["unit_price_cents"] == 412000


class TestSeasonUpliftPrecedesProgramDiscount:
    def test_the_preferred_discount_is_taken_on_the_uplifted_subtotal(self, api):
        """PRD §3.4: "Step three computes `program_discount_cents` as the sum of
        `kit_subtotal_cents` and `season_uplift_cents`, multiplied by the dealership's program
        rate and rounded half up to whole cents, where the rate is zero for `BASE`, three
        percent for `PREFERRED` and six percent for `ELITE`."
        PRD §3.4: "Step two computes `season_uplift_cents` as the `kit_subtotal_cents`
        multiplied by the season rate and rounded half up to whole cents, where the rate is
        negative five percent for `PRESEASON` — a genuine discount for buying before harvest —
        positive seven percent for `HARVEST_PEAK`, and zero for `OFFSEASON`; a preseason order
        therefore carries a negative `season_uplift_cents`."

        Design: Corner/calculations/season_uplift_is_applied_before_the_program_discount_is_taken
        """
        ref = setup_reference_data()
        alpha_design = create_design(ref)
        pinnacle_design = create_design(ref, dealer="pinnacle")

        set_clock("2026-10-05T00:00:00Z")
        harvest = place_order(ref, alpha_design, order_season="HARVEST_PEAK")
        assert harvest["kit_subtotal_cents"] == 2392026
        assert harvest["season_uplift_cents"] == 167442
        assert harvest["program_discount_cents"] == 0
        assert harvest["net_subtotal_cents"] == 2559468
        assert harvest["freight_surcharge_pct"] == pytest.approx(0.045, abs=1e-9)
        assert harvest["freight_surcharge_cents"] == 115176
        assert harvest["total_cents"] == 2674644
        assert harvest["required_deposit_cents"] == 534929
        assert harvest["credit_hold_cents"] == 2139715
        assert_order_price_buildup(harvest)

        set_clock("2026-03-10T00:00:00Z")
        preseason = place_order(
            ref, pinnacle_design, dealer="pinnacle", order_season="PRESEASON"
        )
        assert preseason["kit_subtotal_cents"] == 2392026
        assert preseason["season_uplift_cents"] == -119601
        # The discount is three percent of the uplifted 2272425, not of the bare subtotal.
        assert preseason["program_discount_cents"] == 68173
        assert preseason["program_discount_cents"] != 71761
        assert preseason["net_subtotal_cents"] == 2204252
        assert preseason["freight_surcharge_pct"] == pytest.approx(0.045, abs=1e-9)
        assert preseason["freight_surcharge_cents"] == 99191
        assert preseason["total_cents"] == 2303443
        assert preseason["required_deposit_cents"] == 460689
        assert preseason["credit_hold_cents"] == 1842754
        assert_order_price_buildup(preseason)


class TestUnloadRateSelection:
    def test_gravity_floors_on_capacity_while_the_powered_systems_are_flat_constants(
        self, api
    ):
        """PRD §3.5: "With `GRAVITY`, the `unload_rate_bph` is the design's `capacity_m3`
        multiplied by 3 bushels per hour per cubic metre and taken **down** to the next whole
        number. With `SWEEP_AUGER` it is a flat 5000 bushels per hour, and with `POWER_SWEEP` a
        flat 9000 bushels per hour."
        PRD §3.5: "When the design moisture excess over the profile's safe threshold is exactly
        zero, the estimate is the `grain_mass_kg` divided by the product of `required_fan_cfm`
        and a drying rate of 0.010 kilograms per cubic-foot-per-minute per hour, taken up to the
        next whole hour."
        PRD §3.4: "the unload system quantity is zero for a gravity discharge and 1 for either
        powered option"

        Design: Corner/calculations/unload_rate_floors_for_gravity_and_is_a_flat_constant_for_the_powered_systems
        """
        ref = setup_reference_data()
        design = create_design(ref)
        assert design["capacity_m3"] == pytest.approx(1216.25, abs=1e-9)

        gravity = place_order(ref, design, aeration_package="AERATION")
        sweep = place_order(
            ref, design, aeration_package="AERATION", unload_system="SWEEP_AUGER"
        )
        powered = place_order(
            ref, design, aeration_package="AERATION", unload_system="POWER_SWEEP"
        )

        # 1216.25 x 3 = 3648.75, taken down to 3648.
        assert gravity["unload_rate_bph"] == 3648
        assert sweep["unload_rate_bph"] == 5000
        assert powered["unload_rate_bph"] == 9000

        for order in (gravity, sweep, powered):
            assert order["required_fan_cfm"] == 3187
            assert order["drying_hours_estimate"] == 27516

        assert gravity["kit_subtotal_cents"] == 2677026
        assert gravity["kit_subtotal_cents"] == 2392026 + 285000
        assert gravity["kit_weight_kg"] == pytest.approx(6530.4, abs=1e-9)
        assert gravity["kit_cube_m3"] == pytest.approx(20.35, abs=1e-9)

        _rows, by_code, total = kit_lines(api, gravity["id"])
        assert total == 6
        assert "UNLOAD_SYSTEM" not in by_code
        assert by_code["AERATION_FAN"]["quantity"] == 1

        for order in (sweep, powered):
            assert order["kit_subtotal_cents"] == 3089026
            assert order["kit_subtotal_cents"] == gravity["kit_subtotal_cents"] + 412000
            assert order["kit_weight_kg"] == pytest.approx(6870.4, abs=1e-9)
            assert order["kit_cube_m3"] == pytest.approx(23.75, abs=1e-9)
            _r, codes, count = kit_lines(api, order["id"])
            assert count == 7
            assert codes["AERATION_FAN"]["quantity"] == 1
            assert codes["UNLOAD_SYSTEM"]["quantity"] == 1


class TestSaturatedAerationIsRejected:
    def test_a_raw_requirement_above_the_cap_is_refused_and_never_persisted(self, api):
        """PRD §3.5: "Whenever the `aeration_package` is `AERATION` or `DRYING_FULL`, the
        **uncapped** raw requirement must not exceed 60000 cubic feet per minute; an order whose
        raw requirement exceeds the cap is rejected with `ERR_AERATION_UNDERSIZED`, so a
        saturated `required_fan_cfm` is never persisted. An order with `aeration_package` `NONE`
        is exempt from this check entirely."
        PRD §3.5: "With `NONE` the package multiplier is zero, so `required_fan_cfm` is 0."
        PRD §3.5: "The `drying_hours_estimate` is a whole number of hours and branches on
        whether the grain is wet at all. With `NONE` it is 0."

        Design: Corner/validations/aeration_package_that_needs_more_than_the_maximum_fan_bank_is_rejected_at_order_time
        """
        ref = setup_reference_data()
        design = create_design(
            ref,
            jurisdiction="IA-CENTRAL",
            grain_profile="RICE",
            diameter_m=15.5,
            eave_height_m=15.2,
            design_wind_speed_mph=110,
            moisture_pct=17.0,
        )
        assert design["capacity_m3"] == pytest.approx(3149.38, abs=1e-9)

        # 3149.38 x 3.2 x 5.5 x 1.216 x 1.48 = 99754.62109184, well past the 60000 cap.
        validate_error(
            api.create_dealer_order(
                {
                    "dealer_id": ref["alpha"]["id"],
                    "bin_design_id": design["id"],
                    "order_season": "OFFSEASON",
                    "aeration_package": "DRYING_FULL",
                    "unload_system": "SWEEP_AUGER",
                },
                dealer_headers(ref),
            ),
            "ERR_AERATION_UNDERSIZED",
            422,
        )

        aerated = place_order(
            ref, design, aeration_package="AERATION", unload_system="SWEEP_AUGER"
        )
        assert aerated["required_fan_cfm"] == 18138

        bare = place_order(ref, design)
        assert bare["required_fan_cfm"] == 0
        assert bare["drying_hours_estimate"] == 0
        _rows, by_code, _total = kit_lines(api, bare["id"])
        assert "AERATION_FAN" not in by_code

        _data, meta = validate_paginated(
            api.list_dealer_orders(
                PLANNER, {"bin_design_id": design["id"], "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
