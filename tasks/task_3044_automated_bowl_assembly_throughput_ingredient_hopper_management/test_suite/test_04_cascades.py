"""Transitive cascades: sensor depletion through allocation to REFILL_SCHEDULED,
and verification through quarantine to forced order reroute."""

import pytest

from test_helpers import (
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    PREP_COOK_HEADERS,
    QUALITY_LEAD_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    make_line_operator_headers,
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


class TestSensorDepletionCascade:
    """A sensor reading at or below the threshold cascades: hopper DEPLETED,
    auto refill task created, waterfall allocates from a READY batch, hopper
    lands REFILL_SCHEDULED, line posture restricted."""

    def test_sensor_reading_cascades_to_ready_refill_and_refill_scheduled_hopper(self, api):
        """PRD §3.4: "The depletion then cascades: if no `RefillTask` for this
        hopper is currently `SCHEDULED`, `READY`, or `IN_PROGRESS`, the system
        auto-creates one with `auto_created` set to true, `requested_grams` equal
        to capacity minus current, and a `desired_ready_at` produced by the
        depletion forecast; the waterfall runs immediately to try to allocate it."
        PRD §3.3: "Otherwise the task takes the first candidate: its
        `allocated_grams` becomes the smaller of its `requested_grams` and the
        batch's `available_grams` (partial allocation is allowed), its
        `prep_batch_id` is set, it transitions `SCHEDULED → READY` with its
        `version` bumped, the batch's `allocated_grams` grows by the same amount
        (bumping the batch's `version`), and the task's hopper, if `DEPLETED`,
        moves to `REFILL_SCHEDULED`."

        Design: Difficulty/transitive_cascade/sensor_depletion_cascade_sensor_to_refill_ready
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
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(300, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        # A queued order commits 100 g of forecast demand for the ingredient.
        get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        batch = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=1000), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(batch["id"], PREP_COOK_HEADERS))

        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(150),
                                                   LINE_OPERATOR_HEADERS))

        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        assert len(tasks) == 1
        task = tasks[0]
        assert task["auto_created"] is True
        # Auto refills use FORECAST: requested = min(500 - 150, 100) = 100.
        assert task["requested_grams"] == pytest.approx(100.0, abs=0.01)

        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        b = get_success_data(api.get_prep_batch(batch["id"], PREP_COOK_HEADERS))
        line_after = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        # The hopper moved through DEPLETED into REFILL_SCHEDULED via allocation.
        assert h["status"] == "REFILL_SCHEDULED"
        assert task["status"] == "READY"
        assert task["prep_batch_id"] == batch["id"]
        assert task["allocated_grams"] == pytest.approx(100.0, abs=0.01)
        assert b["allocated_grams"] == pytest.approx(100.0, abs=0.01)
        assert line_after["posture"] == "RESTRICTED"

    def test_depletion_recomputes_line_posture_to_restricted(self, api):
        """PRD §2.5: "Otherwise, if any hopper mounted on the line is in
        `QUARANTINED`, `DEPLETED`, `REFILL_SCHEDULED`, or `REFILLING` status, or
        if sanitation is overdue (the current logical time is strictly after
        `next_sanitation_due_at`), posture is `RESTRICTED`."

        Design: Difficulty/transitive_cascade/sensor_depletion_cascade_sensor_to_refill_ready
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
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(300, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        before = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert before["posture"] == "OPEN"
        # No READY batch exists, so the auto task cannot allocate; the hopper
        # stays DEPLETED and the line goes RESTRICTED.
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(150),
                                                   LINE_OPERATOR_HEADERS))
        after = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert after["posture"] == "RESTRICTED"
        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        assert h["status"] == "DEPLETED"


class TestQuarantineCascadeOrderReroute:
    """A verification that pushes drift past the threshold quarantines the
    hopper and force-reroutes queued automated orders needing the ingredient."""

    def test_quarantine_force_reroutes_queued_automated_order_to_manual_line(self, api):
        """PRD §3.6: "every `QUEUED` order on that line routed `AUTOMATED` whose
        recipe contains the hopper's ingredient — directly or via an applied
        substitution — is force-rerouted: its `route` becomes `MANUAL`, its
        `assigned_line_id` is reselected among eligible manual lines per the
        selector, and its `estimated_queue_seconds` is recomputed, with each
        affected order's `version` bumping."

        Design: Difficulty/transitive_cascade/quarantine_cascade_verification_to_order_reroute
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        manual = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="LM", line_type="MANUAL",
                                         service_rate_seconds_per_bowl=120), OPS_ADMIN_HEADERS))
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
        verifier = make_line_operator_headers("op_verifier_1")

        def run_verified_order():
            order = get_success_data(api.create_order(
                create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
            get_success_data(api.start_order_assembly(order["id"], verifier))
            return get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 104.0}]), verifier))

        run_verified_order()
        run_verified_order()
        # A queued automated order sits on the automated line when the third
        # verification crosses the drift threshold.
        waiting = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        assert waiting["route"] == "AUTOMATED"
        assert waiting["assigned_line_id"] == line["id"]
        run_verified_order()

        h = get_success_data(api.get_hopper(hopper["id"], QUALITY_LEAD_HEADERS))
        assert h["status"] == "QUARANTINED"
        rerouted = get_success_data(api.get_order(waiting["id"], CUSTOMER_HEADERS))
        assert rerouted["route"] == "MANUAL"
        assert rerouted["assigned_line_id"] == manual["id"]
        assert rerouted["estimated_queue_seconds"] == 0

    def test_quarantine_marks_line_restricted(self, api):
        """PRD §3.6: "When a hopper's `drift_pct` is not null and its absolute
        value is strictly greater than 3.0 — exactly 3.0 does not quarantine —
        the `IN_SERVICE` hopper moves to `QUARANTINED`, its line's posture
        becomes `RESTRICTED`"

        Design: Difficulty/transitive_cascade/quarantine_cascade_verification_to_order_reroute
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="LM", line_type="MANUAL",
                                         service_rate_seconds_per_bowl=120), OPS_ADMIN_HEADERS))
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
        verifier = make_line_operator_headers("op_verifier_1")
        for _ in range(3):
            order = get_success_data(api.create_order(
                create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
            get_success_data(api.start_order_assembly(order["id"], verifier))
            get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 104.0}]), verifier))
        line_after = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert line_after["posture"] == "RESTRICTED"
