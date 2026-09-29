"""Dual-basis valuations and the order-sensitive money formulas of the platform.

Every capture is priced twice: a catalog-basis provisional figure struck the moment
the tray hits the scale, and a recipe-basis final figure struck when the owning
service period closes. The same underlying rows can read as an improvement on one
reduction basis and a regression on the other. The formula groups below pin the
evaluation order that makes the published worked examples come out right.
"""

import pytest

from test_helpers import (
    assert_effective_cost_selection,
    assert_recipe,
    assert_reduction_target,
    assert_settlement_breakdown,
    assert_shift,
    assert_site_cost_ledger,
    assert_timestamp_has_three_fractional_digits,
    assert_waste_entry,
    factories,
    fixtures,
    validate_paginated,
    validate_success,
)

CAPTURE_DAY = "2026-06-10"
CAPTURE_AT = "2026-06-10T10:00:00Z"
CALIBRATION_DUE = "2027-01-01T00:00:00Z"


def _priced_catalog_and_recipe_world():
    """A prep station, a 640 cents/kg food type and a published 1029 cents/kg recipe."""
    site = fixtures.create_site(name="Harbor Kitchen", site_code="HK-01", region_code="NE")
    station = fixtures.create_station(
        site["id"],
        station_code="PREP-1",
        station_kind="PREP",
        calibration_due_at=CALIBRATION_DUE,
        capture_lock_seconds=30,
    )
    food_type = fixtures.create_food_type(
        name="Braised Chicken Portion",
        category="PREPARED",
        default_cost_per_kg_cents=640,
        donation_eligible=True,
        animal_feed_eligible=True,
        compostable=True,
        donation_shelf_life_hours=24,
    )
    recipe = fixtures.create_published_recipe(recipe_code="BRZ-CHK", name="Braised Chicken Thigh")
    shift = fixtures.open_shift(
        site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=1000
    )
    return site, station, food_type, recipe, shift


class TestWasteEntryValuationBases:
    """A capture priced on the catalog basis, then repriced on its recipe basis at close."""

    def test_provisional_valuation_ignores_the_recipe_while_the_period_is_open(self):
        """At capture time only the catalog basis is applied and the final basis is unstruck.

        PRD Coverage:
        "`provisional_cost_cents` is that product taken against `catalog_cost_basis_cents`, ignoring recipe attribution entirely."
        "`final_cost_cents` stays null while the owning service period is `OPEN`, and so does `valuation_delta_cents`."
        "`effective_cost_cents` — the figure that actually feeds every site, baseline and rollup total — is `final_cost_cents` when that field is non-null and `provisional_cost_cents` otherwise, so at capture time it equals the provisional figure."

        Design: Difficulty/dual_variant_calc/waste_entry_valuation_catalog_provisional_versus_recipe_final_delta
        """
        site, station, food_type, recipe, shift = _priced_catalog_and_recipe_world()

        entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=2450,
            loss_reason="TRIM",
            recipe_id=recipe["id"],
            captured_at=CAPTURE_AT,
        )

        assert_waste_entry(entry)
        assert entry["catalog_cost_basis_cents"] == 640
        assert entry["recipe_cost_basis_cents"] == 1029
        assert entry["provisional_cost_cents"] == 1568
        assert entry["final_cost_cents"] is None
        assert entry["valuation_delta_cents"] is None
        assert entry["effective_cost_cents"] == 1568
        assert_effective_cost_selection(entry)

        site_now = fixtures.read_site(site["id"])
        assert site_now["total_captured_weight_grams"] == 2450
        assert site_now["valued_waste_cost_cents"] == 1568

    def test_closing_the_period_strikes_the_recipe_basis_and_records_the_delta(self):
        """The published worked example: 1568 provisional, 2521 final, a 953 cent delta.

        PRD Coverage:
        "The final figure uses the recipe basis when the capture has one: `final_cost_cents` is the capture's kilogram weight — `weight_grams` divided by 1000, exact and unrounded — multiplied by `recipe_cost_basis_cents` and rounded half up to a whole number of cents, when `recipe_cost_basis_cents` is not null; when it is null the same multiplication is performed against `catalog_cost_basis_cents`, so a capture with no recipe attribution finishes with a final figure identical to its provisional one."
        "`valuation_delta_cents` is `final_cost_cents` minus `provisional_cost_cents`."
        "Take 2450 grams of a food type priced at 640 cents per kilogram, attributed to a recipe whose published cost is 1029 cents per kilogram. The provisional valuation is 1568 cents; the final valuation is 2521 cents; the recorded `valuation_delta_cents` is 953 cents."

        Design: Difficulty/dual_variant_calc/waste_entry_valuation_catalog_provisional_versus_recipe_final_delta
        """
        site, station, food_type, recipe, shift = _priced_catalog_and_recipe_world()
        entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=2450,
            loss_reason="TRIM",
            recipe_id=recipe["id"],
            captured_at=CAPTURE_AT,
        )

        fixtures.close_shift(shift["id"])

        settled = fixtures.read_entry(entry["id"])
        assert settled["provisional_cost_cents"] == 1568
        assert settled["final_cost_cents"] == 2521
        assert settled["valuation_delta_cents"] == 953
        assert settled["effective_cost_cents"] == 2521
        assert_effective_cost_selection(settled)
        assert settled["status"] == "RECORDED"

    def test_site_ledger_switches_from_the_provisional_to_the_final_figure_at_close(self):
        """The site's valued cost follows the effective figure across the close, gram totals untouched.

        PRD Coverage:
        "`valued_waste_cost_cents` is the sum of `effective_cost_cents` over exactly that same set of captures"
        "`effective_cost_cents` — the figure that actually feeds every site, baseline and rollup total — is `final_cost_cents` when that field is non-null and `provisional_cost_cents` otherwise, so at capture time it equals the provisional figure."

        Design: Difficulty/dual_variant_calc/waste_entry_valuation_catalog_provisional_versus_recipe_final_delta
        """
        site, station, food_type, recipe, shift = _priced_catalog_and_recipe_world()
        entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=2450,
            loss_reason="TRIM",
            recipe_id=recipe["id"],
            captured_at=CAPTURE_AT,
        )

        before = fixtures.read_site(site["id"])
        assert_site_cost_ledger(before, [fixtures.read_entry(entry["id"])])
        assert before["valued_waste_cost_cents"] == 1568

        fixtures.close_shift(shift["id"])

        after = fixtures.read_site(site["id"])
        assert after["valued_waste_cost_cents"] == 2521
        assert after["total_captured_weight_grams"] == 2450
        assert_site_cost_ledger(after, [fixtures.read_entry(entry["id"])])


def _june_baseline_against_july_performance():
    """June: 3000 g over 250 meals, certified. July: 2700 g over 200 meals, closed."""
    site = fixtures.create_site(name="Harbor Kitchen", site_code="HK-01", region_code="NE")
    station = fixtures.create_station(
        site["id"],
        station_code="PREP-1",
        station_kind="PREP",
        calibration_due_at=CALIBRATION_DUE,
        capture_lock_seconds=30,
    )
    food_type = fixtures.create_food_type(
        name="Braised Chicken Portion",
        category="PREPARED",
        default_cost_per_kg_cents=640,
        donation_eligible=True,
        animal_feed_eligible=True,
        compostable=True,
        donation_shelf_life_hours=24,
    )
    june = fixtures.open_shift(site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=250)
    for grams, reason, at in (
        (1200, "TRIM", "2026-06-10T10:00:00Z"),
        (1000, "TRIM", "2026-06-10T10:05:00Z"),
        (800, "SPOILAGE", "2026-06-10T10:10:00Z"),
    ):
        fixtures.capture_entry(
            station["id"], june["id"], food_type["id"], weight_grams=grams, loss_reason=reason, captured_at=at
        )
    fixtures.close_shift(june["id"])

    july = fixtures.open_shift(site["id"], shift_date="2026-07-10", shift_code="AM", meals_served=200)
    for grams, at in ((1500, "2026-07-10T10:00:00Z"), (1200, "2026-07-10T10:05:00Z")):
        fixtures.capture_entry(
            station["id"], july["id"], food_type["id"], weight_grams=grams, loss_reason="TRIM", captured_at=at
        )
    fixtures.close_shift(july["id"])

    baseline = fixtures.open_baseline(site["id"], start_date="2026-06-01", end_date="2026-06-30")
    fixtures.submit_baseline(site["id"], baseline["id"])
    certified = fixtures.certify_baseline(baseline["id"])

    absolute = fixtures.propose_target(
        site["id"],
        baseline["id"],
        fixtures.read_site(site["id"])["version"],
        basis="ABSOLUTE",
        target_reduction_pct=10.00,
        window_start="2026-07-01",
        window_end="2026-07-31",
    )
    absolute = fixtures.activate_target(absolute["id"])
    intensity = fixtures.propose_target(
        site["id"],
        baseline["id"],
        fixtures.read_site(site["id"])["version"],
        basis="INTENSITY",
        target_reduction_pct=10.00,
        window_start="2026-07-01",
        window_end="2026-07-30",
    )
    intensity = fixtures.activate_target(intensity["id"])
    return site, certified, absolute, intensity


class TestReductionBasisDisagreement:
    """Both reduction arms are computed on every target; only the basis decides attainment."""

    def test_absolute_basis_reads_a_ten_percent_improvement_and_attains(self):
        """3000 grams down to 2700 is +10.00 percent absolute, which inclusively meets the target.

        PRD Coverage:
        "`absolute_reduction_pct` is the baseline grams minus the performance grams, divided by the baseline grams, multiplied by 100 and rounded half up to 2 decimal places; it is null when the frozen `baseline_waste_grams` is 0."
        "`effective_reduction_pct` is the absolute figure when `basis` is `ABSOLUTE` and the intensity figure when `basis` is `INTENSITY`."
        "`attainment_state` then holds `ACHIEVED_PENDING` when three conditions all hold — `effective_reduction_pct` is not null, it has reached `target_reduction_pct` or more with the comparison inclusive, and the diversion floor is satisfied — and `BEHIND` in every other case."

        Design: Difficulty/dual_variant_calc/reduction_attainment_absolute_versus_intensity_disagree_on_same_data
        """
        site, certified, absolute, intensity = _june_baseline_against_july_performance()

        stored = fixtures.read_target(absolute["id"])
        assert_reduction_target(stored)
        assert stored["status"] == "ACTIVE"
        assert stored["basis"] == "ABSOLUTE"
        assert stored["performance_waste_grams"] == 2700
        assert stored["performance_meals_served"] == 200
        assert stored["performance_intensity_kg_per_1k_meals"] == pytest.approx(13.500, abs=0.01)
        assert stored["absolute_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert stored["intensity_reduction_pct"] == pytest.approx(-12.50, abs=0.01)
        assert stored["effective_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert stored["attainment_state"] == "ACHIEVED_PENDING"

    def test_intensity_basis_reads_a_regression_on_the_very_same_rows(self):
        """12.000 up to 13.500 is -12.50 percent, so the same data misses an intensity target.

        PRD Coverage:
        "`intensity_reduction_pct` is the frozen baseline intensity minus the performance intensity, divided by the frozen baseline intensity, multiplied by 100 and rounded half up to 2 decimal places; it is null whenever either intensity is null."
        "Consider a baseline of 3000 grams over 250 meals, an intensity of 12.000, against a performance window of 2700 grams over 200 meals, an intensity of 13.500. Measured absolutely the site improved by 10.00 percent; measured by intensity it regressed by 12.50 percent. With a `target_reduction_pct` of 10.00, an `ABSOLUTE` target is attained on exactly the same underlying rows on which an `INTENSITY` target is missed."

        Design: Difficulty/dual_variant_calc/reduction_attainment_absolute_versus_intensity_disagree_on_same_data
        """
        site, certified, absolute, intensity = _june_baseline_against_july_performance()

        assert intensity["status"] == "ACTIVE"
        assert intensity["basis"] == "INTENSITY"
        assert intensity["absolute_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert intensity["intensity_reduction_pct"] == pytest.approx(-12.50, abs=0.01)
        assert intensity["effective_reduction_pct"] == pytest.approx(-12.50, abs=0.01)
        assert intensity["attainment_state"] == "BEHIND"

        assert certified["baseline_waste_grams"] == 3000
        assert certified["baseline_meals_served"] == 250
        assert certified["baseline_intensity_kg_per_1k_meals"] == pytest.approx(12.000, abs=0.01)

    def test_side_by_side_reads_differ_only_in_basis_effective_figure_and_state(self, api, platform_admin_headers):
        """Both computed reads expose both arms; neither target supersedes the other.

        PRD Coverage:
        "A dedicated computed read exposes both results side by side for one target, returning its `target_id`, `basis`, the frozen `baseline_waste_grams` and `baseline_intensity_kg_per_1k_meals`, the live `performance_waste_grams`, `performance_meals_served` and `performance_intensity_kg_per_1k_meals`, both `absolute_reduction_pct` and `intensity_reduction_pct`, the selected `effective_reduction_pct`, the configured `target_reduction_pct` and `min_diversion_rate_pct`, the site's current diversion rate as `site_diversion_rate_pct`, and the resulting `attainment_state`."

        Design: Difficulty/dual_variant_calc/reduction_attainment_absolute_versus_intensity_disagree_on_same_data
        """
        site, certified, absolute, intensity = _june_baseline_against_july_performance()

        absolute_view = fixtures.read_attainment(absolute["id"])
        intensity_view = fixtures.read_attainment(intensity["id"])

        for view in (absolute_view, intensity_view):
            assert view["baseline_waste_grams"] == 3000
            assert view["baseline_intensity_kg_per_1k_meals"] == pytest.approx(12.000, abs=0.01)
            assert view["performance_waste_grams"] == 2700
            assert view["performance_meals_served"] == 200
            assert view["performance_intensity_kg_per_1k_meals"] == pytest.approx(13.500, abs=0.01)
            assert view["absolute_reduction_pct"] == pytest.approx(10.00, abs=0.01)
            assert view["intensity_reduction_pct"] == pytest.approx(-12.50, abs=0.01)
            assert view["target_reduction_pct"] == pytest.approx(10.00, abs=0.01)
            assert view["min_diversion_rate_pct"] == pytest.approx(0.00, abs=0.01)

        assert absolute_view["target_id"] == absolute["id"]
        assert absolute_view["basis"] == "ABSOLUTE"
        assert absolute_view["effective_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert absolute_view["attainment_state"] == "ACHIEVED_PENDING"
        assert intensity_view["target_id"] == intensity["id"]
        assert intensity_view["basis"] == "INTENSITY"
        assert intensity_view["effective_reduction_pct"] == pytest.approx(-12.50, abs=0.01)
        assert intensity_view["attainment_state"] == "BEHIND"

        rows, meta = validate_paginated(
            api.list_reduction_targets(platform_admin_headers, site_id=site["id"])
        )
        assert meta["total_count"] == 2
        assert sorted(row["status"] for row in rows) == ["ACTIVE", "ACTIVE"]


def _worked_example_ingredients():
    """2.5 kg at 1201 with 0.20 trim loss, 1.5 kg at 407, 0.5 kg at 999."""
    return [
        factories.recipe_ingredient("chicken thigh", 2.5, 1201, 0.20),
        factories.recipe_ingredient("mirepoix", 1.5, 407, 0.00),
        factories.recipe_ingredient("cream", 0.5, 999, 0.00),
    ]


class TestRecipeCostingRoundingOrder:
    """Whole-cent rounding happens per line, before the integers are summed and divided."""

    def test_per_line_rounding_yields_4114_cents_and_1029_cents_per_kilogram(self, api, platform_admin_headers):
        """Rounding the three lines first gives 3003 + 611 + 500, which divides to 1029, not 1028.

        PRD Coverage:
        "Second, `total_ingredient_cost_cents` is the plain integer sum of those already-rounded per-line cent figures. Third, `usable_yield_kg` is the sum of the per-line usable kilograms, rounded half up to 3 decimal places once, at the end. Fourth, `cost_per_kg_cents` is `total_ingredient_cost_cents` divided by that rounded `usable_yield_kg`, rounded half up to a whole number of cents."
        "Consider a recipe of three lines: 2.5 kilograms at 1201 cents per kilogram with a trim loss of 0.20, 1.5 kilograms at 407 cents per kilogram with no trim loss, and 0.5 kilograms at 999 cents per kilogram with no trim loss. Rounding each line first gives 3003, 611 and 500 cents, summing to 4114 cents against a usable yield of 4.000 kilograms, which divides to 1028.5 and rounds to a `cost_per_kg_cents` of 1029."
        "A recipe always begins in `DRAFT` and its `status` may only ever hold `DRAFT` or `PUBLISHED`. While it is `DRAFT`, `published_cost_per_kg_cents` and `published_at` are both null and no capture may reference it."

        Design: Difficulty/combinatorial_formula/recipe_cost_per_kg_rounds_per_line_before_summing
        """
        payload = factories.create_recipe_payload(
            ingredients=_worked_example_ingredients(),
            recipe_code="BRZ-CHK",
            name="Braised Chicken Thigh",
        )

        recipe = validate_success(api.create_recipe(payload, platform_admin_headers), 201)

        assert_recipe(recipe)
        assert recipe["status"] == "DRAFT"
        assert recipe["total_ingredient_cost_cents"] == 4114
        assert recipe["usable_yield_kg"] == pytest.approx(4.000, abs=0.01)
        assert recipe["cost_per_kg_cents"] == 1029
        assert recipe["published_cost_per_kg_cents"] is None
        assert recipe["published_at"] is None
        assert recipe["version"] == 1

    def test_publication_freezes_the_per_line_rounded_figure(self):
        """Publication carries the 1029 figure over verbatim and leaves the components intact.

        PRD Coverage:
        "On success the recipe's freshly computed `cost_per_kg_cents` is frozen into `published_cost_per_kg_cents`, `published_at` is stamped with the current logical clock, and the recipe's `version` is incremented by 1."

        Design: Difficulty/combinatorial_formula/recipe_cost_per_kg_rounds_per_line_before_summing
        """
        draft = fixtures.create_recipe(
            ingredients=_worked_example_ingredients(),
            recipe_code="BRZ-CHK",
            name="Braised Chicken Thigh",
        )

        published = fixtures.publish_recipe(draft["id"])

        assert_recipe(published)
        assert published["status"] == "PUBLISHED"
        assert published["published_cost_per_kg_cents"] == 1029
        assert published["cost_per_kg_cents"] == 1029
        assert published["total_ingredient_cost_cents"] == 4114
        assert published["version"] == draft["version"] + 1

        reread = fixtures.read_recipe(draft["id"])
        assert reread["total_ingredient_cost_cents"] == 4114
        assert reread["usable_yield_kg"] == pytest.approx(4.000, abs=0.01)
        assert reread["cost_per_kg_cents"] == 1029
        assert reread["published_cost_per_kg_cents"] == 1029


def _dispatched_compost_load_of_240_kilograms():
    """240000 staged grams on a 2000 gram container, behind a 52000/1800 rate card."""
    site = fixtures.create_site(name="Harbor Kitchen", site_code="HK-01", region_code="NE")
    station = fixtures.create_station(
        site["id"],
        station_code="PREP-1",
        station_kind="PREP",
        calibration_due_at=CALIBRATION_DUE,
        capture_lock_seconds=30,
    )
    food_type = fixtures.create_food_type(
        name="Braised Chicken Portion",
        category="PREPARED",
        default_cost_per_kg_cents=640,
        donation_eligible=True,
        animal_feed_eligible=True,
        compostable=True,
        donation_shelf_life_hours=24,
    )
    hauler = fixtures.create_approved_hauler(
        name="Green Loop Compost",
        channels=["COMPOST"],
        rate_cents_per_tonne=52000,
        stop_fee_cents=1800,
        capacity_kg_per_pickup=500,
        max_concurrent_pickups=1,
    )
    shift = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=5000)
    entries = [
        fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=120000,
            loss_reason="SPOILAGE",
            captured_at=at,
        )
        for at in ("2026-06-10T10:00:00Z", "2026-06-10T10:05:00Z")
    ]
    consignment = fixtures.open_consignment(
        site["id"],
        hauler["id"],
        channel="COMPOST",
        pickup_window_start="2026-06-11T08:00:00Z",
        pickup_window_end="2026-06-11T10:00:00Z",
        container_tare_grams=2000,
    )
    for entry in entries:
        fixtures.add_line(site["id"], consignment["id"], entry["id"], 120000)
    fixtures.stage_consignment(site["id"], consignment["id"])
    consignment = fixtures.dispatch_consignment(site["id"], consignment["id"])
    return site, hauler, consignment


class TestSettlementSurchargeTier:
    """The surcharge tier is read from the base haul fee, never from the subtotal it feeds."""

    def test_seven_step_pass_prices_the_haul_at_15688_cents(self):
        """A base fee of 14800 sits in the middle tier even though the subtotal clears 15000.

        PRD Coverage:
        "**Step one**: `net_weight_grams` is the submitted `gross_weight_grams` minus the consignment's `container_tare_grams`. **Step two**: `billable_tonnes` is those net grams divided by one million — the number of grams in a metric tonne — rounded half up to 4 decimal places. **Step three**: `base_haul_fee_cents` is `billable_tonnes` multiplied by the hauler's `rate_cents_per_tonne`, rounded half up to a whole number of cents, and then increased by the hauler's flat `stop_fee_cents`."
        "**Step four** selects the fuel surcharge tier **from `base_haul_fee_cents` alone**: `fuel_surcharge_pct` is 0.00 when the base fee is below 5000 cents, 0.06 when the base fee is at least 5000 cents and below 15000 cents, and 0.09 when the base fee has reached 15000 cents or more; `fuel_surcharge_cents` is `base_haul_fee_cents` multiplied by that rate, rounded half up to a whole number of cents."
        "**Step five**: `settlement_subtotal_cents` is `base_haul_fee_cents` plus `fuel_surcharge_cents`."
        "The tier is keyed on the base fee, never on the subtotal and never on the total, so the correct answer here is 15688 cents."

        Design: Difficulty/combinatorial_formula/hauler_ticket_surcharge_tier_keyed_on_base_fee_not_on_subtotal
        """
        site, hauler, consignment = _dispatched_compost_load_of_240_kilograms()

        ticket = fixtures.submit_ticket(
            hauler["id"],
            consignment["id"],
            252000,
            ticket_number="GLC-9001",
            ticket_date="2026-06-11",
        )

        assert_settlement_breakdown(
            ticket,
            net_weight_grams=250000,
            billable_tonnes=0.2500,
            base_haul_fee_cents=14800,
            fuel_surcharge_pct=0.06,
            fuel_surcharge_cents=888,
            settlement_subtotal_cents=15688,
            variance_pct=4.17,
            variance_credit_cents=0,
            settlement_total_cents=15688,
        )
        assert ticket["status"] == "SUBMITTED"

    def test_a_variance_of_four_point_one_seven_percent_earns_no_credit(self):
        """250000 net against 240000 staged is 4.17 percent, which does not clear the tolerance.

        PRD Coverage:
        "**Step six** measures the scale disagreement: `variance_pct` is the absolute difference between `net_weight_grams` and the consignment's frozen `staged_weight_grams`, divided by that `staged_weight_grams`, multiplied by 100 and rounded half up to 2 decimal places; `variance_credit_cents` is 10 percent of `settlement_subtotal_cents`, rounded half up to a whole number of cents, when `variance_pct` is **strictly greater** than a 5.00 percent tolerance, and 0 otherwise — a variance of exactly 5.00 percent earns no credit."
        "**Step seven**: `settlement_total_cents` is `settlement_subtotal_cents` minus `variance_credit_cents`."

        Design: Difficulty/combinatorial_formula/hauler_ticket_surcharge_tier_keyed_on_base_fee_not_on_subtotal
        """
        site, hauler, consignment = _dispatched_compost_load_of_240_kilograms()

        ticket = fixtures.submit_ticket(
            hauler["id"],
            consignment["id"],
            252000,
            ticket_number="GLC-9001",
            ticket_date="2026-06-11",
        )

        assert ticket["variance_pct"] == pytest.approx(4.17, abs=0.01)
        assert ticket["variance_credit_cents"] == 0
        assert ticket["settlement_total_cents"] == ticket["settlement_subtotal_cents"]

    def test_filing_the_ticket_moves_only_the_settlement_dimension(self):
        """The frozen staged weight the variance was measured against is left exactly as it was.

        PRD Coverage:
        "On success the ticket is created with `status` `SUBMITTED`, which may only ever hold `SUBMITTED`, `ACCEPTED` or `DISPUTED`, with `dispute_note` and `accepted_at` null, and the consignment's `settlement_status` advances to `TICKET_SUBMITTED` from either `UNBILLED` or `DISPUTED` while `logistics_status` stays `DISPATCHED` untouched; the consignment's `version` is incremented by 1."
        "On success `staged_at` is stamped with the current logical clock, `staged_weight_grams` is frozen for the later ticket variance comparison, no further line may be added or deleted, and `version` is incremented by 1."

        Design: Difficulty/combinatorial_formula/hauler_ticket_surcharge_tier_keyed_on_base_fee_not_on_subtotal
        """
        site, hauler, consignment = _dispatched_compost_load_of_240_kilograms()
        assert consignment["staged_weight_grams"] == 240000

        fixtures.submit_ticket(
            hauler["id"],
            consignment["id"],
            252000,
            ticket_number="GLC-9001",
            ticket_date="2026-06-11",
        )

        after = fixtures.read_consignment(consignment["id"])
        assert after["settlement_status"] == "TICKET_SUBMITTED"
        assert after["logistics_status"] == "DISPATCHED"
        assert after["staged_weight_grams"] == 240000
        assert after["version"] == consignment["version"] + 1


def _site_targeting_ten_kilograms_per_thousand_meals(station_specs):
    """A site whose intensity target is 10.000, with the given stations installed ACTIVE."""
    site = fixtures.create_site(
        name="Harbor Kitchen",
        site_code="HK-01",
        region_code="NE",
        target_intensity_kg_per_1k_meals=10.000,
    )
    stations = [
        fixtures.create_station(
            site["id"],
            station_code=code,
            station_kind=kind,
            calibration_due_at=CALIBRATION_DUE,
            capture_lock_seconds=30,
        )
        for code, kind in station_specs
    ]
    food_type = fixtures.create_food_type(
        name="Braised Chicken Portion",
        category="PREPARED",
        default_cost_per_kg_cents=640,
        donation_eligible=True,
        animal_feed_eligible=True,
        compostable=True,
        donation_shelf_life_hours=24,
    )
    return site, stations, food_type


class TestShiftLeaderboardScore:
    """Three interacting terms, a capped penalty and a threshold bonus produce one figure."""

    def test_all_three_terms_combine_to_eighty_two_point_five(self):
        """An excess of 2.000, a half-reporting site and a full pre-consumer share give 82.5.

        PRD Coverage:
        "The **intensity excess** is the amount by which the period's `waste_intensity_kg_per_1k_meals` exceeds the site's `target_intensity_kg_per_1k_meals`, floored at zero so a period that beat its target scores no excess; a null intensity, which happens when `meals_served` is 0, is treated as zero excess."
        "The **compliance penalty** is the shortfall in station reporting — one minus `capture_compliance_pct` — multiplied by a weight of 25.0 points, so a period where every active station reported loses nothing and a period where none did loses the full 25.0."
        "The **pre-consumer bonus** is a flat 3.0 points, awarded when `pre_consumer_share_pct` is not null and has reached 0.60 or more, and zero otherwise; catching waste before it reaches a plate is what the bonus rewards."
        "The raw score is 100 minus the intensity penalty, minus the compliance penalty, plus the bonus. That raw figure is then clamped into the range from 0 to 100 inclusive — first floored at 0, then capped at 100 — and rounded half up to 1 decimal place to become `leaderboard_score`."

        Design: Difficulty/combinatorial_formula/shift_leaderboard_score_weights_penalty_cap_and_conditional_bonus
        """
        site, stations, food_type = _site_targeting_ten_kilograms_per_thousand_meals(
            [("PREP-1", "PREP"), ("LINE-1", "HOT_LINE")]
        )
        prep = stations[0]
        shift = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=250)
        for grams, reason, at in (
            (1200, "TRIM", "2026-06-10T10:00:00Z"),
            (1000, "TRIM", "2026-06-10T10:05:00Z"),
            (800, "SPOILAGE", "2026-06-10T10:10:00Z"),
        ):
            fixtures.capture_entry(
                prep["id"], shift["id"], food_type["id"], weight_grams=grams, loss_reason=reason, captured_at=at
            )

        closed = fixtures.close_shift(shift["id"])

        assert_shift(closed)
        assert closed["status"] == "CLOSED"
        assert closed["shift_waste_grams"] == 3000
        assert closed["waste_intensity_kg_per_1k_meals"] == pytest.approx(12.000, abs=0.01)
        assert closed["capture_compliance_pct"] == pytest.approx(0.5000, abs=0.01)
        assert closed["pre_consumer_share_pct"] == pytest.approx(1.0000, abs=0.01)
        assert closed["leaderboard_score"] == pytest.approx(82.5, abs=0.01)
        assert closed["closed_at"].startswith("2026-08-01T00:00:00")
        assert_timestamp_has_three_fractional_digits(closed["closed_at"])

    def test_a_gross_overshoot_stops_losing_points_at_sixty(self):
        """An excess of 190.000 would cost 760 points, but the penalty is capped at 60.0.

        PRD Coverage:
        "The **intensity penalty** is that excess multiplied by 4.0 points per kilogram per thousand meals, then capped so it can never exceed 60.0 points however far the period overshot."
        "`capture_compliance_pct`, which is the number of distinct stations that reported on this period divided by the number of the site's `ACTIVE` stations, rounded half up to 4 decimal places, and fixed at 1.0000 when the site has no `ACTIVE` stations at all."

        Design: Difficulty/combinatorial_formula/shift_leaderboard_score_weights_penalty_cap_and_conditional_bonus
        """
        site, stations, food_type = _site_targeting_ten_kilograms_per_thousand_meals([("PREP-1", "PREP")])
        shift = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=100)
        fixtures.capture_entry(
            stations[0]["id"],
            shift["id"],
            food_type["id"],
            weight_grams=20000,
            loss_reason="TRIM",
            captured_at=CAPTURE_AT,
        )

        closed = fixtures.close_shift(shift["id"])

        assert closed["waste_intensity_kg_per_1k_meals"] == pytest.approx(200.000, abs=0.01)
        assert closed["capture_compliance_pct"] == pytest.approx(1.0000, abs=0.01)
        assert closed["pre_consumer_share_pct"] == pytest.approx(1.0000, abs=0.01)
        assert closed["leaderboard_score"] == pytest.approx(43.0, abs=0.01)

    def test_a_purely_post_consumer_period_forfeits_the_conditional_bonus(self):
        """A pre-consumer share of 0.0000 is below the threshold, so only the 8.0 penalty lands.

        PRD Coverage:
        "The **pre-consumer bonus** is a flat 3.0 points, awarded when `pre_consumer_share_pct` is not null and has reached 0.60 or more, and zero otherwise; catching waste before it reaches a plate is what the bonus rewards."
        "The raw score is 100 minus the intensity penalty, minus the compliance penalty, plus the bonus. That raw figure is then clamped into the range from 0 to 100 inclusive — first floored at 0, then capped at 100 — and rounded half up to 1 decimal place to become `leaderboard_score`."

        Design: Difficulty/combinatorial_formula/shift_leaderboard_score_weights_penalty_cap_and_conditional_bonus
        """
        site, stations, food_type = _site_targeting_ten_kilograms_per_thousand_meals([("DISH-1", "DISH_RETURN")])
        shift = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=1000)
        fixtures.capture_entry(
            stations[0]["id"],
            shift["id"],
            food_type["id"],
            weight_grams=12000,
            loss_reason="PLATE_WASTE",
            captured_at=CAPTURE_AT,
        )

        closed = fixtures.close_shift(shift["id"])

        assert closed["waste_intensity_kg_per_1k_meals"] == pytest.approx(12.000, abs=0.01)
        assert closed["pre_consumer_share_pct"] == pytest.approx(0.0000, abs=0.01)
        assert closed["capture_compliance_pct"] == pytest.approx(1.0000, abs=0.01)
        assert closed["leaderboard_score"] == pytest.approx(92.0, abs=0.01)
