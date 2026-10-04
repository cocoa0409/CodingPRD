"""Boundary precision: numeric thresholds tested on both sides."""

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


class TestDepletionThresholdExactly200:
    """A reading at or below 200 grams declares depletion; above it only
    re-baselines the hopper."""

    def test_201_keeps_in_service_then_200_depletes(self, api):
        """PRD §3.4: "A reading strictly above 200 grams simply re-baselines
        `current_grams` to `grams_reading` — the sensor overwrites the
        dispense-derived bookkeeping — bumps the hopper's `version`, and
        recomputes the line posture; the hopper stays `IN_SERVICE`. A reading
        at or below 200 grams — exactly 200 triggers — declares depletion"

        Design: Difficulty/boundary_precision_check/depletion_threshold_exactly_200_grams
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
            create_hopper_payload(line["id"], ing["id"], capacity_grams=1000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(500, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        at_201 = get_success_data(api.report_sensor_reading(
            hopper["id"], sensor_reading_payload(201), LINE_OPERATOR_HEADERS))
        assert at_201["status"] == "IN_SERVICE"
        assert at_201["current_grams"] == pytest.approx(201, abs=0.01)
        assert not get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))

        at_200 = get_success_data(api.report_sensor_reading(
            hopper["id"], sensor_reading_payload(200), LINE_OPERATOR_HEADERS))
        assert at_200["status"] == "DEPLETED"
        assert at_200["current_grams"] == pytest.approx(200, abs=0.01)
        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        assert len(tasks) == 1
        assert tasks[0]["auto_created"] is True

    def test_zero_reading_depletes_and_rebaselines(self, api):
        """PRD §3.4: "A reading at or below 200 grams — exactly 200 triggers —
        declares depletion: `current_grams` is set to the reading, the hopper
        moves `IN_SERVICE → DEPLETED`, and the line's posture is recomputed"

        Design: Difficulty/boundary_precision_check/depletion_threshold_exactly_200_grams
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
            create_hopper_payload(line["id"], ing["id"], capacity_grams=1000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(500, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        at_0 = get_success_data(api.report_sensor_reading(
            hopper["id"], sensor_reading_payload(0), LINE_OPERATOR_HEADERS))
        assert at_0["status"] == "DEPLETED"
        assert at_0["current_grams"] == pytest.approx(0, abs=0.01)


class TestPortionToleranceExactly5Pct:
    """Variance at most 5.0 passes; above fails."""

    def _setup(self, api):
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
            create_hopper_payload(line["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        return rest, recipe, hopper

    def test_variance_plus_5_00_passes(self, api):
        """PRD §2.7: "Each verification yields a `result` of `PASS` when the
        absolute value of `variance_pct` is at most 5.0, and `FAIL` otherwise."

        Design: Difficulty/boundary_precision_check/portion_tolerance_exactly_5pct_passes
        """
        rest, recipe, hopper = self._setup(api)
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        verified = get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 105.0}]), LINE_OPERATOR_HEADERS))
        assert verified["status"] == "COMPLETED"
        rows = get_success_data(
            api.list_order_portion_verifications(order["id"], LINE_OPERATOR_HEADERS))
        assert rows[0]["result"] == "PASS"
        assert rows[0]["variance_pct"] == pytest.approx(5.00, abs=0.01)

    def test_variance_plus_5_10_fails_and_requeues(self, api):
        """PRD §3.6: "When any verification is `FAIL` and the order's
        `remake_count` is still below 3, the order returns `VERIFICATION → QUEUED`:
        `remake_count` increments"

        Design: Difficulty/boundary_precision_check/portion_tolerance_exactly_5pct_passes
        """
        rest, recipe, hopper = self._setup(api)
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        failed = get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 105.1}]), LINE_OPERATOR_HEADERS))
        assert failed["status"] == "QUEUED"
        assert failed["remake_count"] == 1
        rows = get_success_data(
            api.list_order_portion_verifications(order["id"], LINE_OPERATOR_HEADERS))
        assert rows[0]["result"] == "FAIL"
        assert rows[0]["variance_pct"] == pytest.approx(5.10, abs=0.01)
