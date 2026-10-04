"""Cross-entity state dependencies: one resource's transition is gated by the
state of a different resource."""

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
    create_sanitation_cycle_payload,
)


class TestStartAssemblyGatedByLinePosture:
    """An order in a valid QUEUED state still cannot start assembly when its
    assigned line's derived posture is not OPEN."""

    def test_restricted_line_rejects_start_assembly(self, api):
        """PRD §2.5: "The most consequential consumer of posture is
        start-assembly: an order can only begin assembly on a line whose posture
        is `OPEN`, and any attempt otherwise is rejected with `ERR_LINE_NOT_OPEN`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/start_assembly_gated_by_line_posture
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
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        # Deplete the hopper AFTER the order is queued; the line goes RESTRICTED.
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(150),
                                                   LINE_OPERATOR_HEADERS))
        response = api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_LINE_NOT_OPEN)
        after = get_success_data(api.get_order(order["id"], CUSTOMER_HEADERS))
        assert after["status"] == "QUEUED"
        assert after["started_at"] is None

    def test_open_line_allows_start_assembly(self, api):
        """PRD §2.5: "an order can only begin assembly on a line whose posture
        is `OPEN`"

        Design: Difficulty/cross_entity_state_dependency/start_assembly_gated_by_line_posture
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
        line_state = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert line_state["posture"] == "OPEN"
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        started = validate_success(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        assert started["status"] == "ASSEMBLING"
        assert started["started_at"] is not None


class TestSanitationStartGatedByRefillingHopper:
    """A sanitation cycle inside its window still cannot start while the line
    hosts a REFILLING hopper."""

    def _setup_refilling_hopper(self, api):
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
        batch = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=1000), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(batch["id"], PREP_COOK_HEADERS))
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(0),
                                                   LINE_OPERATOR_HEADERS))
        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.start_refill_task(tasks[0]["id"], LINE_OPERATOR_HEADERS))
        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        assert h["status"] == "REFILLING"
        return rest, line, ing, hopper

    def test_start_rejected_while_hopper_refilling(self, api):
        """PRD §3.7: "a line hosting in-flight work is rejected with
        `ERR_LINE_BUSY` (HTTP 409), as is a pause attempt under the same
        conditions."
        PRD §3.7: "the line must be `ACTIVE`, no order on the line may be in
        `QUEUED`, `ASSEMBLING`, or `VERIFICATION`, and no hopper on the line may
        be `REFILLING`"

        Design: Difficulty/cross_entity_state_dependency/sanitation_start_gated_by_refilling_hopper
        """
        _, line, _, _ = self._setup_refilling_hopper(api)
        cycle = get_success_data(api.create_sanitation_cycle(
            create_sanitation_cycle_payload(
                line["id"], "2026-09-01T00:10:00Z", "2026-09-01T00:40:00Z"),
            SHIFT_MANAGER_HEADERS))
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:15:00Z"), OPS_ADMIN_HEADERS))
        response = api.start_sanitation_cycle(cycle["id"], LINE_OPERATOR_HEADERS)
        validate_error(response, ApiErrorId.ERR_LINE_BUSY)
        cycle_after = get_success_data(api.get_sanitation_cycle(cycle["id"], SHIFT_MANAGER_HEADERS))
        line_after = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert cycle_after["status"] == "SCHEDULED"
        assert line_after["status"] == "ACTIVE"

    def test_start_allowed_once_refill_completed(self, api):
        """PRD §3.7: "A `LineOperator` starts a cycle only inside its window:
        the current logical time must be at or after `scheduled_start` and
        strictly before `scheduled_end` — a half-open window"

        Design: Difficulty/cross_entity_state_dependency/sanitation_start_gated_by_refilling_hopper
        """
        _, line, _, hopper = self._setup_refilling_hopper(api)
        cycle = get_success_data(api.create_sanitation_cycle(
            create_sanitation_cycle_payload(
                line["id"], "2026-09-01T00:10:00Z", "2026-09-01T00:40:00Z"),
            SHIFT_MANAGER_HEADERS))
        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.complete_refill_task(tasks[0]["id"], LINE_OPERATOR_HEADERS))
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:15:00Z"), OPS_ADMIN_HEADERS))
        started = validate_success(api.start_sanitation_cycle(cycle["id"], LINE_OPERATOR_HEADERS))
        assert started["status"] == "IN_PROGRESS"
        line_after = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert line_after["status"] == "CLEANING"
