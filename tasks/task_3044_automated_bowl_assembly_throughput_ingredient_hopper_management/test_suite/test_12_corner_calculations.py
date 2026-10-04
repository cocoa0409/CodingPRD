"""Corner — calculations: throughput over a half-open window and the FEFO
refill waterfall with partial allocation."""

import pytest

from test_helpers import (
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    PREP_COOK_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    validate_success,
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
    create_prep_batch_payload,
)


class TestThroughputWindowHalfOpen:
    """Throughput counts only COMPLETED orders with completed_at inside the
    half-open window [from, to)."""

    def test_window_counts_three_excludes_boundary_completion(self, api):
        """PRD §3.9: "Management reads throughput for a restaurant by supplying
        `from_iso8601` and `to_iso8601`; the window includes orders completed at
        or after the start and strictly before the end. Only `COMPLETED` orders
        count — cancelled and in-flight orders are excluded"
        PRD §3.9: "`bowls_per_hour`, that count scaled by 3,600 seconds over the
        window length in seconds, at 2 decimal places round-half-up"

        Design: Corner/calculations/throughput_window_half_open_and_target
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=5000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(2000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))

        # O1: queued 00:00, started 00:02 (actual queue 120), completed 00:02.
        o1 = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:02:00Z"), OPS_ADMIN_HEADERS))
        get_success_data(api.start_order_assembly(o1["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.submit_order_verification(
            o1["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 100.0}]), LINE_OPERATOR_HEADERS))

        # O2: queued 00:02, started 00:03 (actual queue 60), completed 00:03.
        o2 = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:03:00Z"), OPS_ADMIN_HEADERS))
        get_success_data(api.start_order_assembly(o2["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.submit_order_verification(
            o2["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 100.0}]), LINE_OPERATOR_HEADERS))

        # O3: queued 00:03, started 00:04 (actual queue 60), completed 00:04.
        o3 = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:04:00Z"), OPS_ADMIN_HEADERS))
        get_success_data(api.start_order_assembly(o3["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.submit_order_verification(
            o3["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 100.0}]), LINE_OPERATOR_HEADERS))

        # O4 completes exactly at the window end (00:30) and must be excluded.
        o4 = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:30:00Z"), OPS_ADMIN_HEADERS))
        get_success_data(api.start_order_assembly(o4["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.submit_order_verification(
            o4["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 100.0}]), LINE_OPERATOR_HEADERS))

        reports = validate_success(api.get_throughput(
            rest["id"], SHIFT_MANAGER_HEADERS,
            params={"from_iso8601": "2026-09-01T00:00:00Z",
                    "to_iso8601": "2026-09-01T00:30:00Z"}))
        # The report carries four figures per line; this restaurant has one line.
        assert len(reports) == 1
        report = reports[0]
        assert report["line_id"] == line["id"]
        assert report["orders_completed"] == 3
        assert report["bowls_per_hour"] == pytest.approx(6.00, abs=0.01)
        # mean(120, 60, 60) = 80, within the 300-second queue target.
        assert report["avg_queue_seconds"] == 80
        assert report["queue_target_met"] is True


class TestRefillWaterfallFefo:
    """The waterfall picks the earliest-expiring batch first and permits
    partial allocation of exactly what is available."""

    def test_fefo_picks_earliest_expiring_batch_with_partial_allocation(self, api):
        """PRD §3.3: "Each task in that order is matched against candidate
        batches at the task's restaurant whose `ingredient_id` equals the task's
        ingredient, whose status is `READY`, whose `expires_at` is strictly
        after now, and whose `available_grams` is positive; candidates are
        ordered by `expires_at` ascending (first-expiry-first-out), ties broken
        by `created_at` ascending."
        PRD §3.3: "its `allocated_grams` becomes the smaller of its
        `requested_grams` and the batch's `available_grams` (partial allocation
        is allowed)"

        Design: Corner/calculations/refill_waterfall_fefo_order_and_partial_allocation
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=120), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(300, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        # A queued order commits 300 g of forecast demand for the ingredient.
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 300}],
                                  name="Big Bowl", base_complexity=0), OPS_ADMIN_HEADERS))
        get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        # b_old expires 02:00 (marked ready at 00:00, shelf 120 min).
        b_old = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=300), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(b_old["id"], PREP_COOK_HEADERS))
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(0),
                                                   LINE_OPERATOR_HEADERS))
        # b_new marked ready at 01:00, so it expires at 03:00 — strictly later.
        get_success_data(api.set_clock(clock_payload("2026-09-01T01:00:00Z"), OPS_ADMIN_HEADERS))
        b_new = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=1000), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(b_new["id"], PREP_COOK_HEADERS))

        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        assert len(tasks) == 1
        task = tasks[0]
        # FEFO: b_old (expires 02:00) is picked ahead of b_new (03:00).
        assert task["prep_batch_id"] == b_old["id"]
        assert task["status"] == "READY"
        assert task["allocated_grams"] == pytest.approx(300.0, abs=0.01)
        old_after = get_success_data(api.get_prep_batch(b_old["id"], PREP_COOK_HEADERS))
        assert old_after["available_grams"] == pytest.approx(0.0, abs=0.01)
