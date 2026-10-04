"""Corner — cross-cutting layers: optimistic concurrency, derived posture
reconciliation, drift threshold boundary, and queue-estimate tie-breaking."""

import pytest

from test_helpers import (
    ApiErrorId,
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    QUALITY_LEAD_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    make_line_operator_headers,
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
    submit_verification_payload,
    sensor_reading_payload,
)


class TestOccStaleRecipeVersion:
    def test_stale_expected_recipe_version_rejected_fresh_accepted(self, api):
        """PRD §2.8: "Placing an order requires the client to supply
        `expected_recipe_version`, the `version` of the `Recipe` the client last
        observed. If the recipe's current `version` has advanced since — because
        another writer modified its `portion_spec`, or an eighty-six, restore,
        or substitution transition recomputed `is_available` and bumped the
        version — the create is rejected with `ERR_STALE_RECIPE_VERSION`
        (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_stale_recipe_version_on_order_create
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="LA", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
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
        # Advance the recipe version twice via an eighty-six/restore round-trip.
        get_success_data(api.eighty_six_ingredient(ing["id"], SHIFT_MANAGER_HEADERS))
        get_success_data(api.restore_ingredient(ing["id"], SHIFT_MANAGER_HEADERS))
        fresh = get_success_data(api.get_recipe(recipe["id"], CUSTOMER_HEADERS))
        assert fresh["version"] != recipe["version"]

        stale = api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS)
        validate_error(stale, ApiErrorId.ERR_STALE_RECIPE_VERSION)

        accepted = validate_success(api.create_order(
            create_order_payload(rest["id"], recipe["id"], fresh["version"]), CUSTOMER_HEADERS), 201)
        assert accepted["recipe_id"] == recipe["id"]


class TestOccStaleHopperVersion:
    def test_stale_expected_hopper_version_rejected(self, api):
        """PRD §2.8: "Loading a hopper requires the client to supply
        `expected_hopper_version`, the `version` of the `Hopper` the client last
        observed. If the hopper's current `version` has advanced since — because
        another writer completed a load, or a sensor reading re-baselined
        `current_grams` — the load is rejected with `ERR_STALE_HOPPER_VERSION`
        (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_stale_hopper_version_on_load
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        stale_version = hopper["version"]

        first = validate_success(api.load_hopper(
            hopper["id"], load_hopper_payload(500, stale_version), LINE_OPERATOR_HEADERS))
        assert first["version"] == stale_version + 1
        # A sensor reading re-baselines and bumps the version again.
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(100),
                                                   LINE_OPERATOR_HEADERS))
        response = api.load_hopper(
            hopper["id"], load_hopper_payload(500, stale_version), LINE_OPERATOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_STALE_HOPPER_VERSION)


class TestDerivedPostureReconciliation:
    def test_posture_open_restricted_open_across_sensor_and_reload(self, api):
        """PRD §2.5: "Posture is recomputed whenever any of its inputs change: a
        hopper state transition, a load, a sensor reading, a sanitation
        completion or abort, a pause or resume, or the passage of the logical
        clock past `next_sanitation_due_at`."

        Design: Corner/cross_cutting_layers/derived_posture_recomputed_on_sensor_and_load
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(300, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        open_state = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert open_state["posture"] == "OPEN"

        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(100),
                                                   LINE_OPERATOR_HEADERS))
        restricted = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert restricted["posture"] == "RESTRICTED"

        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(400, h["version"]),
                                         LINE_OPERATOR_HEADERS))
        back = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert back["posture"] == "OPEN"


class TestDriftThresholdBoundary:
    def test_drift_exactly_3_00_does_not_quarantine(self, api):
        """PRD §2.7: "When `drift_pct` is not null and its absolute value is
        strictly greater than 3.0, the hopper is quarantined automatically;
        exactly 3.0 does not trigger quarantine."

        Design: Corner/cross_cutting_layers/drift_threshold_boundary_exactly_3pct_no_quarantine
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
        verifier = make_line_operator_headers("op_verifier_1")
        for _ in range(3):
            order = get_success_data(api.create_order(
                create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
            get_success_data(api.start_order_assembly(order["id"], verifier))
            get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 103.0}]), verifier))
        h = get_success_data(api.get_hopper(hopper["id"], QUALITY_LEAD_HEADERS))
        assert h["drift_pct"] == pytest.approx(3.00, abs=0.01)
        assert h["status"] == "IN_SERVICE"


class TestQueueEstimateStrictlyEarlier:
    def test_same_instant_orders_use_creation_order_tie_break(self, api):
        """PRD §3.5: "At placement, `estimated_queue_seconds` is the count of
        `QUEUED` orders on the assigned line whose `queue_entered_at` is
        strictly earlier than this order's — ties broken by `created_at`
        ascending, the order itself excluded — multiplied by the line's
        `service_rate_seconds_per_bowl`."

        Design: Corner/cross_cutting_layers/queue_estimate_excludes_equal_timestamp_order
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
        first = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        second = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        assert first["queue_entered_at"] == second["queue_entered_at"]
        assert first["estimated_queue_seconds"] == 0
        assert second["estimated_queue_seconds"] == 45


class TestImmediateConsistencyOnCompletion:
    def test_completion_visible_immediately_and_hopper_debited(self, api):
        """PRD §1: "the system favors explicit state and immediate consistency:
        every reading, dispense, refill, and verdict is recorded the moment it
        happens, and derived gates such as line posture are recomputed whenever
        their inputs change."
        PRD §3.6: "On an `AUTOMATED` route, starting assembly immediately debits
        each involved hopper: `current_grams` falls by the dispense amount"

        Design: Corner/consistency_model/completion_side_effects_visible_immediately
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
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
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        completed = get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 100.0}]), LINE_OPERATOR_HEADERS))
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None
        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        assert h["current_grams"] == pytest.approx(900.0, abs=0.01)
