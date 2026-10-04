"""Combinatorial formulas: pinned rounding order and pinned evaluation order."""

import pytest

from test_helpers import (
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    get_success_data,
    clock_payload,
    create_restaurant_payload,
    create_assembly_line_payload,
    create_ingredient_payload,
    create_recipe_payload,
    create_hopper_payload,
    load_hopper_payload,
    create_order_payload,
    submit_verification_payload,
    sensor_reading_payload,
)


class TestDispenseRoundingOrderPinned:
    """Per-line rounding to 0.1 g happens first; the order total is the exact
    sum of already-rounded lines and is never re-rounded."""

    def test_total_is_sum_of_per_line_rounded_amounts(self, api):
        """PRD §2.6: "Per-ingredient dispense amounts are rounded to 1 decimal
        place using round-half-up at the moment of dispensing, per portion line;
        an order's `expected_total_grams` is the exact sum of those
        already-rounded per-line amounts and is never re-rounded."

        Design: Difficulty/combinatorial_formula/dispense_rounding_order_pinned_per_line_then_sum
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        ing_a = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="A1", name="IngA", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        ing_b = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="B1", name="IngB", station_type="TOPPING",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [
                {"ingredient_id": ing_a["id"], "target_grams": 5},
                {"ingredient_id": ing_b["id"], "target_grams": 5},
            ], name="Duo", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper_a = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing_a["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.05), OPS_ADMIN_HEADERS))
        hopper_b = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing_b["id"], capacity_grams=500, station_slot=2,
                                  calibration_coefficient=1.05), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper_a["id"], load_hopper_payload(100, hopper_a["version"]),
                                         LINE_OPERATOR_HEADERS))
        get_success_data(api.load_hopper(hopper_b["id"], load_hopper_payload(100, hopper_b["version"]),
                                         LINE_OPERATOR_HEADERS))
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        verified = get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload([
                {"hopper_id": hopper_a["id"], "actual_grams": 5.3},
                {"hopper_id": hopper_b["id"], "actual_grams": 5.3},
            ]), LINE_OPERATOR_HEADERS))
        # 5 * 1.05 = 5.25 -> 5.3 per line; sum of rounded lines = 10.6,
        # NOT 10.5 from rounding the unrounded sum once.
        assert verified["expected_total_grams"] == pytest.approx(10.6, abs=1e-9)
        assert verified["status"] == "COMPLETED"

    def test_rounding_half_up_applies_per_portion_line(self, api):
        """PRD §2.6: "Per-ingredient dispense amounts are rounded to 1 decimal
        place using round-half-up at the moment of dispensing, per portion line"

        Design: Difficulty/combinatorial_formula/dispense_rounding_order_pinned_per_line_then_sum
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        ing_a = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="A1", name="IngA", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing_a["id"], "target_grams": 5}],
                                  name="Solo", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper_a = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing_a["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.05), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper_a["id"], load_hopper_payload(100, hopper_a["version"]),
                                         LINE_OPERATOR_HEADERS))
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        verified = get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload([
                {"hopper_id": hopper_a["id"], "actual_grams": 5.3},
            ]), LINE_OPERATOR_HEADERS))
        # 5 * 1.05 = 5.25 rounds half-up to 5.3 on the single line.
        assert verified["expected_total_grams"] == pytest.approx(5.3, abs=1e-9)


class TestDepletionForecastEvaluationOrder:
    """FORECAST requested grams are computed with the CURRENT calibration
    coefficient, then capped against free capacity."""

    def test_forecast_requested_grams_uses_current_coefficient(self, api):
        """PRD §3.4: "Under `FORECAST` mode — which auto-created refills always
        use — `requested_grams` is the smaller of capacity minus current and the
        committed queued demand for that ingredient on the line: the sum, over
        `QUEUED` orders on the line whose post-customization recipe needs the
        ingredient, of each order's dispense amount for it, at 1 decimal place
        round-half-up."

        Design: Difficulty/combinatorial_formula/depletion_forecast_circular_dependency_pinned_order
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.05), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(400, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(60),
                                                   LINE_OPERATOR_HEADERS))
        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        task = tasks[0]
        assert task["auto_created"] is True
        # Queued demand at the current coefficient: 100 * 1.05 = 105.0;
        # free capacity 440, so min() keeps the demand figure.
        assert task["requested_grams"] == pytest.approx(105.0, abs=0.01)

    def test_forecast_with_zero_committed_demand_requests_zero(self, api):
        """PRD §3.4: "`FORECAST` can therefore be strictly smaller than
        `STANDARD` for identical hopper state, and zero committed demand yields
        a `requested_grams` of zero — the task is still created."

        Design: Difficulty/combinatorial_formula/depletion_forecast_circular_dependency_pinned_order
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.05), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(400, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        # No queued order: committed demand is zero.
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(60),
                                                   LINE_OPERATOR_HEADERS))
        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        task = tasks[0]
        assert task["auto_created"] is True
        assert task["requested_grams"] == pytest.approx(0, abs=0.01)
