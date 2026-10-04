"""Corner — validations: authentication, existence, temporal and business
constraint violations mapped to their declared errors."""

import pytest

from test_helpers import (
    ApiErrorId,
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    PREP_COOK_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    validate_error,
    validate_success,
    clock_payload,
    create_restaurant_payload,
    create_assembly_line_payload,
    create_ingredient_payload,
    create_recipe_payload,
    create_hopper_payload,
    load_hopper_payload,
    create_order_payload,
    sensor_reading_payload,
    create_prep_batch_payload,
    create_refill_task_payload,
)
from prd_bench_local_runner.testing import NON_EXISTENT_UUID


class TestMissingAuthHeaders:
    def test_request_without_headers_is_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role value
        outside this declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_401
        """
        response = api.list_restaurants({})
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


class TestBodyReferencedExistence:
    def test_nonexistent_recipe_in_order_body_returns_404(self, api):
        """PRD §2.9: "Body-referenced entities exist — the `recipe_id` on a new
        order, the ingredient ids inside `portion_spec`, `customizations`, or a
        substitution pair, the `hopper_id` on a refill request, the
        `prep_batch_id` where referenced — also `ERR_NOT_FOUND`."

        Design: Corner/validations/nonexistent_recipe_in_order_body_returns_404
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        response = api.create_order(
            create_order_payload(rest["id"], NON_EXISTENT_UUID, 1), CUSTOMER_HEADERS)
        validate_error(response, ApiErrorId.ERR_NOT_FOUND)


class TestRefillStartExpiredBatch:
    def test_start_with_past_expiry_batch_rejected(self, api):
        """PRD §3.4: "Starting requires the task `READY`, its allocated batch
        still `READY` with `expires_at` strictly after now (otherwise
        `ERR_PREP_BATCH_EXPIRED`)"

        Design: Corner/validations/refill_start_with_expired_batch_rejected
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=30), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(300, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        # A queued order gives the auto FORECAST task committed demand (350 g).
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
        task = tasks[0]
        assert task["status"] == "READY"

        # Batch expired at 00:30; no sweep has run, so it is still READY.
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:45:00Z"), OPS_ADMIN_HEADERS))
        response = api.start_refill_task(task["id"], LINE_OPERATOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_PREP_BATCH_EXPIRED)
        after = get_success_data(api.get_refill_task(task["id"], LINE_OPERATOR_HEADERS))
        assert after["status"] == "READY"


class TestDailyRefillBudget:
    def test_second_manual_refill_crossing_budget_rejected(self, api):
        """PRD §2.10: "Each restaurant operates under a daily refill budget of
        50,000 grams: the sum of `allocated_grams` across `RefillTask`s created
        at that restaurant on the current logical day must stay within that
        ceiling. A manual refill request whose allocation would push the running
        total over the budget is rejected with `ERR_REFILL_BUDGET_EXCEEDED`
        (HTTP 402)."

        Design: Corner/validations/daily_refill_budget_boundary
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing_a = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        ing_b = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="B1", name="IngB", station_type="TOPPING",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        hopper_a = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing_a["id"], capacity_grams=30000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        hopper_b = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing_b["id"], capacity_grams=30000, station_slot=2,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        # Ready batches let the waterfall actually allocate each task, so the
        # allocated_grams running total the budget governs is non-zero.
        batch_a = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing_a["id"], quantity_grams=30000), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(batch_a["id"], PREP_COOK_HEADERS))
        batch_b = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing_b["id"], quantity_grams=30000), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(batch_b["id"], PREP_COOK_HEADERS))
        first = validate_success(api.create_refill_task(
            create_refill_task_payload(hopper_a["id"], mode="STANDARD"), LINE_OPERATOR_HEADERS), 201)
        # STANDARD: requested = capacity - current = 30000 - 0 = 30000, fully
        # allocated from batch_a by the waterfall.
        assert first["requested_grams"] == pytest.approx(30000, abs=0.01)
        assert first["allocated_grams"] == pytest.approx(30000, abs=0.01)
        second = api.create_refill_task(
            create_refill_task_payload(hopper_b["id"], mode="STANDARD"), LINE_OPERATOR_HEADERS)
        # 30000 allocated + 30000 requested = 60000 > 50000 budget.
        validate_error(second, ApiErrorId.ERR_REFILL_BUDGET_EXCEEDED)


class TestVerificationMeasurementSet:
    def test_missing_hopper_measurement_rejected(self, api):
        """PRD §3.6: "The measurement set must cover exactly the hopper set
        dispensed for this order: missing hoppers, extra hoppers, a negative
        `actual_grams`, or a zero `expected_grams` line are all rejected with
        `ERR_VERIFICATION_MISMATCH` (HTTP 422)."

        Design: Corner/validations/verification_measurement_set_must_match_exactly
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing_a = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="A1", name="IngA", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        ing_b = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="B1", name="IngB", station_type="TOPPING",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [
                {"ingredient_id": ing_a["id"], "target_grams": 100},
                {"ingredient_id": ing_b["id"], "target_grams": 50},
            ], name="Duo", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper_a = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing_a["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        hopper_b = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing_b["id"], capacity_grams=2000, station_slot=2,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper_a["id"], load_hopper_payload(1000, hopper_a["version"]),
                                         LINE_OPERATOR_HEADERS))
        get_success_data(api.load_hopper(hopper_b["id"], load_hopper_payload(1000, hopper_b["version"]),
                                         LINE_OPERATOR_HEADERS))
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))

        # Measurement for hopper_b is missing.
        response = api.submit_order_verification(
            order["id"],
            {"measurements": [{"hopper_id": hopper_a["id"], "actual_grams": 100.0}]},
            LINE_OPERATOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_VERIFICATION_MISMATCH)
        after = get_success_data(api.get_order(order["id"], CUSTOMER_HEADERS))
        assert after["status"] == "ASSEMBLING"
        rows = get_success_data(
            api.list_order_portion_verifications(order["id"], LINE_OPERATOR_HEADERS))
        assert rows == []


class TestCustomizationOnNonSpecIngredient:
    def test_extra_on_ingredient_not_in_recipe_rejected(self, api):
        """PRD §3.5: "`EXTRA` and `REMOVE` must reference ingredients present in
        the recipe's `portion_spec`, and `SUBSTITUTE` must name a valid
        substitution pair; duplicate customization entries for the same
        ingredient are rejected. Any violation is `ERR_INVALID_CUSTOMIZATION`
        (HTTP 422)."

        Design: Corner/validations/customization_on_non_spec_ingredient_rejected
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        ext = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="EXT", name="Extra", station_type="TOPPING",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        response = api.create_order(
            create_order_payload(
                rest["id"], recipe["id"], recipe["version"],
                customizations=[{"ingredient_id": ext["id"], "action": "EXTRA"}]),
            CUSTOMER_HEADERS)
        validate_error(response, ApiErrorId.ERR_INVALID_CUSTOMIZATION)


class TestOrderCreateUnavailableRecipe:
    def test_order_against_unavailable_recipe_rejected(self, api):
        """PRD §3.5: "The referenced recipe must exist and must be available —
        a recipe whose `is_available` is false at placement time is rejected
        with `ERR_RECIPE_UNAVAILABLE` (HTTP 422)."

        Design: Corner/validations/order_create_unavailable_recipe_rejected
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        get_success_data(api.eighty_six_ingredient(ing["id"], SHIFT_MANAGER_HEADERS))
        fresh = get_success_data(api.get_recipe(recipe["id"], CUSTOMER_HEADERS))
        response = api.create_order(
            create_order_payload(rest["id"], recipe["id"], fresh["version"]), CUSTOMER_HEADERS)
        validate_error(response, ApiErrorId.ERR_RECIPE_UNAVAILABLE)
