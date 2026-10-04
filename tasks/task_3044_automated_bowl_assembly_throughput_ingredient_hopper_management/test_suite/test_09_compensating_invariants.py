"""Compensating invariants: hopper mass accounting and prep-batch quantity
partitioning stay conserved across forward and compensating actions."""

import pytest

from test_helpers import (
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    PREP_COOK_HEADERS,
    SHIFT_MANAGER_HEADERS,
    assert_hopper_mass_balance,
    assert_prep_batch_quantity_invariant,
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
    create_prep_batch_payload,
)


class TestHopperMassBalanceOnFailedVerification:
    """A failed verification moves grams from dispensed to waste without
    touching current_grams; the mass partition stays conserved."""

    def test_failed_dispense_reclassified_conserving_mass(self, api):
        """PRD §2.6: "A failed verification moves the expected grams of each
        failed measurement out of `cumulative_dispensed_grams` and into
        `cumulative_waste_grams` — the dispensed mass is reclassified as waste
        and is explicitly not returned to `current_grams`."

        Design: Difficulty/compensating_invariant/hopper_mass_balance_dispense_vs_failed_verification
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
                                  calibration_coefficient=1.005), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        failed = get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 120.0}]), LINE_OPERATOR_HEADERS))
        assert failed["status"] == "QUEUED"

        h = get_success_data(api.get_hopper(hopper["id"], SHIFT_MANAGER_HEADERS))
        # dispense 100 * 1.005 = 100.5; reclassified out of dispensed, into waste.
        assert h["current_grams"] == pytest.approx(899.5, abs=0.01)
        assert h["cumulative_dispensed_grams"] == pytest.approx(0.0, abs=0.01)
        assert h["cumulative_waste_grams"] == pytest.approx(100.5, abs=0.01)
        assert h["cumulative_refilled_grams"] == pytest.approx(0.0, abs=0.01)
        assert h["initial_load_grams"] == pytest.approx(1000.0, abs=0.01)
        # Conserved: 899.5 + 0.0 + 100.5 - 0 == 1000.0.
        assert_hopper_mass_balance(h)

    def test_successful_dispense_keeps_mass_conserved(self, api):
        """PRD §3.6: "On an `AUTOMATED` route, starting assembly immediately
        debits each involved hopper: `current_grams` falls by the dispense
        amount and `cumulative_dispensed_grams` grows by it"

        Design: Difficulty/compensating_invariant/hopper_mass_balance_dispense_vs_failed_verification
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
                                  calibration_coefficient=1.005), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        completed = get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 100.5}]), LINE_OPERATOR_HEADERS))
        assert completed["status"] == "COMPLETED"

        h = get_success_data(api.get_hopper(hopper["id"], SHIFT_MANAGER_HEADERS))
        assert h["current_grams"] == pytest.approx(899.5, abs=0.01)
        assert h["cumulative_dispensed_grams"] == pytest.approx(100.5, abs=0.01)
        assert h["cumulative_waste_grams"] == pytest.approx(0.0, abs=0.01)
        assert_hopper_mass_balance(h)


class TestPrepBatchQuantityInvariantUnderCancel:
    """Cancelling a READY refill task releases its allocation; the batch's
    quantity partition returns to its pre-allocation state."""

    def _setup_allocated_task(self, api):
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
        # Queue an order so the auto FORECAST refill has committed demand.
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 350}],
                                  name="Big Bowl", base_complexity=0), OPS_ADMIN_HEADERS))
        get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        batch = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=1000), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(batch["id"], PREP_COOK_HEADERS))
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(150),
                                                   LINE_OPERATOR_HEADERS))
        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        return batch, tasks[0]

    def test_cancel_releases_allocation_restoring_available(self, api):
        """PRD §3.3: "A batch's `available_grams` is computed as `quantity_grams`
        minus `allocated_grams` minus `consumed_grams`, and the invariant that
        the quantity always equals the sum of allocated, consumed, and available
        holds at all times"
        PRD §3.4: "A `ShiftManager` may instead cancel a task in `SCHEDULED` or
        `READY`: any batch allocation is released (the batch's `allocated_grams`
        shrinks and its `version` bumps), the task becomes `CANCELLED`"

        Design: Difficulty/compensating_invariant/prep_batch_quantity_invariant_under_cancel
        """
        batch, task = self._setup_allocated_task(api)
        # FORECAST demand 350, free capacity 350 -> requested and allocated 350.
        assert task["status"] == "READY"
        assert task["allocated_grams"] == pytest.approx(350.0, abs=0.01)

        get_success_data(api.cancel_refill_task(task["id"], SHIFT_MANAGER_HEADERS))
        b = get_success_data(api.get_prep_batch(batch["id"], PREP_COOK_HEADERS))
        assert b["allocated_grams"] == pytest.approx(0.0, abs=0.01)
        assert b["consumed_grams"] == pytest.approx(0.0, abs=0.01)
        assert b["available_grams"] == pytest.approx(1000.0, abs=0.01)
        assert_prep_batch_quantity_invariant(b)

    def test_cancel_returns_hopper_to_depleted(self, api):
        """PRD §3.4: "a hopper left in `REFILL_SCHEDULED` by the cancellation
        returns to `DEPLETED` — the hopper rejoins the awaiting-refill pool,
        and a fresh request is required to refill it."

        Design: Difficulty/compensating_invariant/prep_batch_quantity_invariant_under_cancel
        """
        batch, task = self._setup_allocated_task(api)
        get_success_data(api.cancel_refill_task(task["id"], SHIFT_MANAGER_HEADERS))
        h = get_success_data(api.get_hopper(task["hopper_id"], LINE_OPERATOR_HEADERS))
        assert h["status"] == "DEPLETED"
        t = get_success_data(api.get_refill_task(task["id"], SHIFT_MANAGER_HEADERS))
        assert t["status"] == "CANCELLED"
        b = get_success_data(api.get_prep_batch(batch["id"], PREP_COOK_HEADERS))
        assert_prep_batch_quantity_invariant(b)
