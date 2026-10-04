"""Corner — endpoints: logical clock default, manual reroute, refill start on a
paused line, and load-to-capacity boundary."""

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


class TestLogicalClockDefault:
    def test_restaurant_created_before_any_clock_set_uses_default_instant(self, api):
        """PRD §2.4: "Before any call, the clock reads exactly
        `2026-09-01T00:00:00Z` — a fixed startup default that never falls back
        to wall-clock."

        Design: Corner/endpoints/clock_default_is_2026_09_01
        """
        data = validate_success(api.create_restaurant(
            create_restaurant_payload(name="R0", city="SF"), OPS_ADMIN_HEADERS), 201)
        # The creation timestamp must reflect the fixed startup instant.
        assert data["created_at"].startswith("2026-09-01T00:00:00")


class TestManualReroute:
    def test_reroute_moves_order_to_target_line_back_of_queue(self, api):
        """PRD §3.5: "A `ShiftManager` may instead reroute a `QUEUED` order by
        supplying a `target_route` and optionally a `target_line_id`: the target
        line must exist at the order's restaurant, its `line_type` must match
        the requested `target_route` (which must differ from the route the order
        currently requires), and the target line's `posture` must be `OPEN`.
        Rerouting updates `route` and `assigned_line_id`, re-stamps
        `queue_entered_at` to now — the order joins the back of the target
        line's queue — and recomputes the estimate."

        Design: Corner/endpoints/manual_reroute_moves_order_to_target_line_back_of_queue
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        la1 = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="LA1", line_type="AUTOMATED",
                                         service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
        lm1 = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="LM1", line_type="MANUAL",
                                         service_rate_seconds_per_bowl=120), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        # An allergen-flagged topping drives customization complexity past 8 so
        # orders carrying the EXTRA customization route MANUAL.
        ing_flag = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ALM", name="Almonds", station_type="TOPPING",
                                      shelf_life_minutes=240, allergen_flag=True), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        recipe_flag = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [
                {"ingredient_id": ing["id"], "target_grams": 100},
                {"ingredient_id": ing_flag["id"], "target_grams": 30},
            ], name="Nutty", base_complexity=0), OPS_ADMIN_HEADERS))
        hopper_a = get_success_data(api.create_hopper(
            create_hopper_payload(la1["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper_a["id"], load_hopper_payload(1000, hopper_a["version"]),
                                         LINE_OPERATOR_HEADERS))

        # Two orders queue on the MANUAL line: three REMOVE customizations on
        # allergen-flagged... use EXTRA on the allergen ingredient three times
        # is impossible (duplicates rejected), so base the route on score:
        # EXTRA (+1) plus allergen (+2) per customization entry. Three
        # allergen entries -> 9 > 8 routes MANUAL.
        ing_f2 = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="WAL", name="Walnuts", station_type="TOPPING",
                                      shelf_life_minutes=240, allergen_flag=True), OPS_ADMIN_HEADERS))
        ing_f3 = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="PEC", name="Pecans", station_type="TOPPING",
                                      shelf_life_minutes=240, allergen_flag=True), OPS_ADMIN_HEADERS))
        recipe_manual = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [
                {"ingredient_id": ing["id"], "target_grams": 100},
                {"ingredient_id": ing_flag["id"], "target_grams": 30},
                {"ingredient_id": ing_f2["id"], "target_grams": 30},
                {"ingredient_id": ing_f3["id"], "target_grams": 30},
            ], name="Trail", base_complexity=0), OPS_ADMIN_HEADERS))
        manual_custom = [
            {"ingredient_id": ing_flag["id"], "action": "EXTRA"},
            {"ingredient_id": ing_f2["id"], "action": "EXTRA"},
            {"ingredient_id": ing_f3["id"], "action": "EXTRA"},
        ]
        o2 = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe_manual["id"], recipe_manual["version"],
                                 customizations=manual_custom), CUSTOMER_HEADERS))
        o3 = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe_manual["id"], recipe_manual["version"],
                                 customizations=manual_custom), CUSTOMER_HEADERS))
        assert o2["route"] == "MANUAL"
        assert o2["assigned_line_id"] == lm1["id"]
        assert o3["assigned_line_id"] == lm1["id"]

        # The subject order routes AUTOMATED onto la1.
        subject = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        assert subject["route"] == "AUTOMATED"
        assert subject["assigned_line_id"] == la1["id"]

        rerouted = validate_success(api.reroute_order(
            subject["id"],
            {"target_route": "MANUAL", "target_line_id": lm1["id"]},
            SHIFT_MANAGER_HEADERS))
        assert rerouted["route"] == "MANUAL"
        assert rerouted["assigned_line_id"] == lm1["id"]
        # The subject joins the back of the manual line's queue behind o2 and
        # o3: 2 * 120 seconds.
        assert rerouted["estimated_queue_seconds"] == 2 * 120


class TestStartRefillOnPausedLine:
    def test_start_rejected_when_line_paused(self, api):
        """PRD §3.4: "Starting requires the task `READY`, its allocated batch
        still `READY` with `expires_at` strictly after now (otherwise
        `ERR_PREP_BATCH_EXPIRED`), the hopper in `REFILL_SCHEDULED`, and the
        hopper's line `ACTIVE` — a line out of service cannot be refilled."
        PRD §2.9: "5. The target resource's state permits the requested
        transition (`ERR_INVALID_STATE`)"

        Design: Corner/endpoints/start_refill_on_paused_line_rejected
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
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
        # A queued order gives the auto FORECAST task committed demand.
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 350}],
                                  name="Big Bowl", base_complexity=0), OPS_ADMIN_HEADERS))
        get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        batch = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=1000), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(batch["id"], PREP_COOK_HEADERS))
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(0),
                                                   LINE_OPERATOR_HEADERS))
        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        task = tasks[0]
        assert task["status"] == "READY"
        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        assert h["status"] == "REFILL_SCHEDULED"

        get_success_data(api.pause_line(line["id"], SHIFT_MANAGER_HEADERS))
        response = api.start_refill_task(task["id"], LINE_OPERATOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        task_after = get_success_data(api.get_refill_task(task["id"], LINE_OPERATOR_HEADERS))
        h_after = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        assert task_after["status"] == "READY"
        assert h_after["status"] == "REFILL_SCHEDULED"


class TestLoadExactlyToCapacity:
    def test_load_to_exactly_capacity_allowed_one_gram_over_rejected(self, api):
        """PRD §3.1: "the sum of `current_grams` plus `load_grams` must not
        exceed `capacity_grams` — filling exactly to capacity is allowed, one
        gram over is `ERR_HOPPER_CAPACITY_EXCEEDED`."

        Design: Corner/endpoints/load_exactly_to_capacity_allowed
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
        # Re-baseline down to 150 via the sensor (above-threshold reading keeps
        # the hopper IN_SERVICE, then the 150 reading depletes it so it can be
        # re-loaded; a DEPLETED hopper accepts loads).
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(300),
                                                   LINE_OPERATOR_HEADERS))
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(150),
                                                   LINE_OPERATOR_HEADERS))
        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        # 150 + 350 == 500 capacity: allowed.
        full = validate_success(api.load_hopper(
            hopper["id"], load_hopper_payload(350, h["version"]), LINE_OPERATOR_HEADERS))
        assert full["current_grams"] == pytest.approx(500, abs=0.01)

        # Re-baseline back down to 150 and try one gram over capacity.
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(500),
                                                   LINE_OPERATOR_HEADERS))
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(150),
                                                   LINE_OPERATOR_HEADERS))
        h2 = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        over = api.load_hopper(hopper["id"], load_hopper_payload(351, h2["version"]),
                               LINE_OPERATOR_HEADERS)
        validate_error(over, ApiErrorId.ERR_HOPPER_CAPACITY_EXCEEDED)
