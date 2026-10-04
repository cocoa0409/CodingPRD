"""Dual-variant calculations: the same entity yields two divergent metrics."""

import pytest

from test_helpers import (
    ApiErrorId,
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    SHIFT_MANAGER_HEADERS,
    PREP_COOK_HEADERS,
    get_success_data,
    validate_success,
    create_prep_batch_payload,
    create_restaurant_payload,
    create_assembly_line_payload,
    create_ingredient_payload,
    create_recipe_payload,
    create_hopper_payload,
    load_hopper_payload,
    clock_payload,
    create_order_payload,
    submit_verification_payload,
    sensor_reading_payload,
    create_hopper_payload as hopper_payload,
)


class TestQueueTimeEstimatedVsActual:
    """Order queue metrics: the ESTIMATED variant at creation and the ACTUAL
    variant measured at the final start-assembly diverge for the same order."""

    def test_estimated_zero_when_no_earlier_queued_order(self, api):
        """PRD §3.5: "At placement, `estimated_queue_seconds` is the count of
        `QUEUED` orders on the assigned line whose `queue_entered_at` is strictly
        earlier than this order's — ties broken by `created_at` ascending, the
        order itself excluded — multiplied by the line's
        `service_rate_seconds_per_bowl`."

        Design: Difficulty/dual_variant_calc/queue_time_estimated_vs_actual_variants
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
            create_hopper_payload(line["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))

        # An earlier order is created and fully completed BEFORE the subject order.
        early = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(early["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.submit_order_verification(
            early["id"], submit_verification_payload([{"hopper_id": hopper["id"], "actual_grams": 100.0}]),
            LINE_OPERATOR_HEADERS))

        get_success_data(api.set_clock(clock_payload("2026-09-01T00:02:00Z"), OPS_ADMIN_HEADERS))
        subject = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        # The earlier order is already COMPLETED, so zero QUEUED orders are ahead.
        assert subject["estimated_queue_seconds"] == 0

    def test_actual_measured_from_queue_entered_to_final_start(self, api):
        """PRD §3.5: "The `actual_queue_seconds`, null until then, is measured on
        the successful start-assembly that ultimately leads to completion: the
        seconds from `queue_entered_at` to `started_at`."

        Design: Difficulty/dual_variant_calc/queue_time_estimated_vs_actual_variants
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
            create_hopper_payload(line["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))

        get_success_data(api.set_clock(clock_payload("2026-09-01T00:02:00Z"), OPS_ADMIN_HEADERS))
        subject = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        assert subject["actual_queue_seconds"] is None

        get_success_data(api.set_clock(clock_payload("2026-09-01T00:04:00Z"), OPS_ADMIN_HEADERS))
        started = get_success_data(api.start_order_assembly(subject["id"], LINE_OPERATOR_HEADERS))
        assert started["actual_queue_seconds"] == 120
        # Same order, two variants: ESTIMATED 0 (no earlier QUEUED orders at
        # placement) versus ACTUAL 120 (final wall wait).
        assert subject["estimated_queue_seconds"] == 0
        assert started["actual_queue_seconds"] != subject["estimated_queue_seconds"]


class TestPrepBatchWasteLiveVsExpired:
    """The same PrepBatch row reports a different waste figure while live than
    after the expire sweep reclassifies its available remainder."""

    def _setup_batch_after_refill(self, api):
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=60), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(300, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        batch = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=1000), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(batch["id"], PREP_COOK_HEADERS))
        # Queue an order committing 500 g of forecast demand so the auto refill
        # (FORECAST mode) requests min(500 - 0, 500) = 500 g.
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 500}],
                                  name="Big Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(0),
                                                   LINE_OPERATOR_HEADERS))
        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        task = tasks[0]
        get_success_data(api.start_refill_task(task["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.complete_refill_task(task["id"], LINE_OPERATOR_HEADERS))
        return rest, ing, batch

    def test_live_variant_reports_zero_waste(self, api):
        """PRD §3.3: "while the batch is live (`IN_PREP` or `READY`), `waste_pct`
        treats the available remainder as usable and computes whatever quantity
        is neither consumed, allocated, nor available — which under the
        invariant is zero — over the quantity"

        Design: Difficulty/dual_variant_calc/prep_batch_waste_live_vs_expired_variants
        """
        _, _, batch = self._setup_batch_after_refill(api)
        live = get_success_data(api.get_prep_batch(batch["id"], PREP_COOK_HEADERS))
        # Auto refill requested capacity - current = 500 - 0 = 500; the batch
        # covered it fully, so consumed is 500 and available is 500.
        assert live["status"] == "READY"
        assert live["consumed_grams"] == pytest.approx(500, abs=0.01)
        assert live["allocated_grams"] == pytest.approx(0, abs=0.01)
        assert live["available_grams"] == pytest.approx(500, abs=0.01)
        assert live["waste_pct"] == pytest.approx(0.00, abs=0.01)

    def test_expired_variant_reclassifies_available_remainder_as_waste(self, api):
        """PRD §3.3: "once the batch is `EXPIRED`, the remaining `available_grams`
        are reclassified as waste, and `waste_pct_expired` is the available
        remainder over the quantity."

        Design: Difficulty/dual_variant_calc/prep_batch_waste_live_vs_expired_variants
        """
        _, _, batch = self._setup_batch_after_refill(api)
        get_success_data(api.set_clock(clock_payload("2026-09-01T01:30:00Z"), OPS_ADMIN_HEADERS))
        sweep = get_success_data(api.expire_sweep_prep_batches(SHIFT_MANAGER_HEADERS))
        assert sweep["expired_count"] == 1
        expired = get_success_data(api.get_prep_batch(batch["id"], PREP_COOK_HEADERS))
        assert expired["status"] == "EXPIRED"
        # Same consumed/available fields, different variant: 500 / 1000 = 50.00.
        assert expired["consumed_grams"] == pytest.approx(500, abs=0.01)
        assert expired["available_grams"] == pytest.approx(500, abs=0.01)
        assert expired["waste_pct_expired"] == pytest.approx(50.00, abs=0.01)
