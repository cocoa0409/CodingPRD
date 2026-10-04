"""Corner — state machines: preconditions, terminal lockdown, side effects,
cascades, compensation, and conditional transitions."""

import pytest

from test_helpers import (
    ApiErrorId,
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    PREP_COOK_HEADERS,
    QUALITY_LEAD_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    is_iso8601_timestamp,
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
    create_prep_batch_payload,
    create_substitution_rule_payload,
    create_sanitation_cycle_payload,
)


def _standard_store(api, shelf_life=240, hopper_capacity=2000, load=1000):
    get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
    rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
    line = get_success_data(api.create_assembly_line(
        create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED",
                                     service_rate_seconds_per_bowl=45), OPS_ADMIN_HEADERS))
    ing = get_success_data(api.create_ingredient(
        create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                  shelf_life_minutes=shelf_life), OPS_ADMIN_HEADERS))
    recipe = get_success_data(api.create_recipe(
        create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                              name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
    hopper = get_success_data(api.create_hopper(
        create_hopper_payload(line["id"], ing["id"], capacity_grams=hopper_capacity,
                              station_slot=0, calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
    get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(load, hopper["version"]),
                                     LINE_OPERATOR_HEADERS))
    return rest, line, ing, recipe, hopper


class TestPauseWithInFlightOrder:
    def test_pause_rejected_while_order_assembling(self, api):
        """PRD §3.7: "a `ShiftManager` may pause an `ACTIVE` line — subject to
        the line-busy guard that no order on the line is `ASSEMBLING` and no
        hopper is `REFILLING`"
        PRD §3.7: "a line hosting in-flight work is rejected with
        `ERR_LINE_BUSY` (HTTP 409), as is a pause attempt under the same
        conditions."

        Design: Corner/state_machines/pause_with_in_flight_order_rejected
        """
        rest, line, ing, recipe, hopper = _standard_store(api)
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        response = api.pause_line(line["id"], SHIFT_MANAGER_HEADERS)
        validate_error(response, ApiErrorId.ERR_LINE_BUSY)
        after = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert after["status"] == "ACTIVE"


class TestCompletedOrderTerminal:
    def test_cancel_and_reroute_of_completed_order_rejected(self, api):
        """PRD §3.6: "`COMPLETED` and `CANCELLED` are the terminal states of an
        order."
        PRD §2.9: "5. The target resource's state permits the requested
        transition (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/completed_order_terminal_lockdown
        """
        rest, line, ing, recipe, hopper = _standard_store(api)
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        completed = get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 100.0}]), LINE_OPERATOR_HEADERS))
        assert completed["status"] == "COMPLETED"

        cancel = api.cancel_order(order["id"], CUSTOMER_HEADERS)
        validate_error(cancel, ApiErrorId.ERR_INVALID_STATE)
        reroute = api.reroute_order(order["id"], {"target_route": "MANUAL"}, SHIFT_MANAGER_HEADERS)
        validate_error(reroute, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_order(order["id"], CUSTOMER_HEADERS))
        assert after["status"] == "COMPLETED"


class TestEightySixPropagation:
    def test_eighty_six_flips_availability_and_restore_flips_back(self, api):
        """PRD §3.2: "When an ingredient runs out or is pulled, a `ShiftManager`
        eighty-sixes it: the ingredient moves `ACTIVE → EIGHTY_SIXED` and
        `is_available` is recomputed for every recipe containing it."
        PRD §3.2: "Restoration reverses the move — `EIGHTY_SIXED → ACTIVE`,
        with availability recomputed for affected recipes"

        Design: Corner/state_machines/eighty_six_propagates_to_recipe_availability
        """
        rest = get_success_data(api.create_restaurant(
            create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        assert recipe["is_available"] is True

        get_success_data(api.eighty_six_ingredient(ing["id"], SHIFT_MANAGER_HEADERS))
        off = get_success_data(api.get_recipe(recipe["id"], CUSTOMER_HEADERS))
        assert off["is_available"] is False

        get_success_data(api.restore_ingredient(ing["id"], SHIFT_MANAGER_HEADERS))
        on = get_success_data(api.get_recipe(recipe["id"], CUSTOMER_HEADERS))
        assert on["is_available"] is True


class TestSubstitutionCoversEightySix:
    def test_active_rule_keeps_recipe_available_retire_drops_it(self, api):
        """PRD §3.2: "a recipe's `is_available` is true if and only if every
        `portion_spec` entry resolves — either the named ingredient is `ACTIVE`,
        or an `ACTIVE` `SubstitutionRule` at the same restaurant covers it,
        meaning the rule's `from_ingredient_id` equals the entry's ingredient
        and the current logical time falls inside the rule's effective window."
        PRD §3.2: "retiring an `ACTIVE` rule — `ACTIVE → RETIRED` — recomputes
        availability again, since an eighty-sixed from-ingredient may now leave
        its recipes unavailable."

        Design: Corner/state_machines/substitution_covers_eighty_sixed_ingredient
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        ing_a = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="A1", name="IngA", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        ing_b = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="B1", name="IngB", station_type="BASE",
                                      shelf_life_minutes=240), OPS_ADMIN_HEADERS))
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing_a["id"], "target_grams": 100}],
                                  name="Harvest", base_complexity=0), OPS_ADMIN_HEADERS))
        rule = get_success_data(api.create_substitution_rule(
            create_substitution_rule_payload(
                rest["id"], ing_a["id"], ing_b["id"],
                "2026-09-01T00:00:00Z", "2026-09-01T23:59:00Z"), OPS_ADMIN_HEADERS))
        get_success_data(api.activate_substitution_rule(rule["id"], SHIFT_MANAGER_HEADERS))
        get_success_data(api.eighty_six_ingredient(ing_a["id"], SHIFT_MANAGER_HEADERS))

        covered = get_success_data(api.get_recipe(recipe["id"], CUSTOMER_HEADERS))
        assert covered["is_available"] is True

        get_success_data(api.retire_substitution_rule(rule["id"], SHIFT_MANAGER_HEADERS))
        after = get_success_data(api.get_recipe(recipe["id"], CUSTOMER_HEADERS))
        assert after["is_available"] is False


class TestExpireSweepReleaseAndReallocate:
    def test_expired_batch_releases_task_and_waterfall_reallocates(self, api):
        """PRD §3.3: "Expiry has a cascade: each `RefillTask` holding an
        allocation from an expired batch and currently `READY` is released back
        to `SCHEDULED` with `allocated_grams` reset to 0 and `prep_batch_id`
        cleared (its `version` bumped); the batch's `allocated_grams` shrinks by
        each released amount; and any linked hopper that was `REFILL_SCHEDULED`
        falls back to `DEPLETED` (its `version` bumped). The waterfall then
        re-runs, attempting to re-allocate the released tasks from other ready,
        unexpired batches."

        Design: Corner/state_machines/expire_sweep_releases_ready_task_and_reallocates
        """
        get_success_data(api.set_clock(clock_payload("2026-09-01T00:00:00Z"), OPS_ADMIN_HEADERS))
        rest = get_success_data(api.create_restaurant(create_restaurant_payload(name="R1", city="LA"), OPS_ADMIN_HEADERS))
        line = get_success_data(api.create_assembly_line(
            create_assembly_line_payload(rest["id"], name="L1", line_type="AUTOMATED"), OPS_ADMIN_HEADERS))
        ing = get_success_data(api.create_ingredient(
            create_ingredient_payload(sku="ROM", name="Romaine", station_type="BASE",
                                      shelf_life_minutes=60), OPS_ADMIN_HEADERS))
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=500, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(300, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        # A queued order commits 350 g of forecast demand for the ingredient.
        recipe = get_success_data(api.create_recipe(
            create_recipe_payload(rest["id"], [{"ingredient_id": ing["id"], "target_grams": 350}],
                                  name="Big Bowl", base_complexity=0), OPS_ADMIN_HEADERS))
        get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        b1 = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=400), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(b1["id"], PREP_COOK_HEADERS))
        get_success_data(api.report_sensor_reading(hopper["id"], sensor_reading_payload(150),
                                                   LINE_OPERATOR_HEADERS))
        tasks = get_success_data(api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        assert tasks[0]["status"] == "READY"
        assert tasks[0]["prep_batch_id"] == b1["id"]
        # Forecast: min(500 - 150, 350) = 350 allocated from the expiring batch.
        assert tasks[0]["allocated_grams"] == pytest.approx(350.0, abs=0.01)

        # Advance past b1's expiry (ready 00:00 + 60 min shelf life = 01:00)
        # before readying b2, so b2 (expires 02:30) survives the sweep.
        get_success_data(api.set_clock(clock_payload("2026-09-01T01:30:00Z"), OPS_ADMIN_HEADERS))
        b2 = get_success_data(api.create_prep_batch(
            create_prep_batch_payload(rest["id"], ing["id"], quantity_grams=1000), PREP_COOK_HEADERS))
        get_success_data(api.mark_prep_batch_ready(b2["id"], PREP_COOK_HEADERS))

        sweep = get_success_data(api.expire_sweep_prep_batches(SHIFT_MANAGER_HEADERS))
        assert sweep["expired_count"] == 1
        assert b1["id"] in sweep["expired_batch_ids"]

        tasks_after = get_success_data(
            api.list_hopper_refill_tasks(hopper["id"], LINE_OPERATOR_HEADERS))
        task = tasks_after[0]
        assert task["status"] == "READY"
        assert task["allocated_grams"] == pytest.approx(350.0, abs=0.01)
        assert task["prep_batch_id"] == b2["id"]
        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        assert h["status"] == "REFILL_SCHEDULED"


class TestSanitationCompleteClearsQuarantine:
    def _quarantine_hopper(self, api, rest, line, ing, recipe, hopper):
        verifier = make_line_operator_headers("op1")
        for _ in range(3):
            order = get_success_data(api.create_order(
                create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
            get_success_data(api.start_order_assembly(order["id"], verifier))
            get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 104.0}]), verifier))

    def test_complete_resets_quarantined_hopper_to_depleted(self, api):
        """PRD §3.7: "Completing the cycle — also a `LineOperator` act, on an
        `IN_PROGRESS` cycle — stamps `actual_completed_at`, moves the cycle
        `IN_PROGRESS → COMPLETED`, and drives the line `CLEANING → ACTIVE` with
        three consequences: `last_sanitation_completed_at` is set to now and
        `next_sanitation_due_at` recomputed four hours out; every hopper on the
        line that was `QUARANTINED` is reset to `DEPLETED` — it must be
        reloaded before re-service — with each such hopper's `version` bumped;
        and the line posture is recomputed."

        Design: Corner/state_machines/sanitation_complete_clears_quarantine_to_depleted
        """
        rest, line, ing, recipe, hopper = _standard_store(api, hopper_capacity=5000, load=2000)
        self._quarantine_hopper(api, rest, line, ing, recipe, hopper)
        armed = get_success_data(api.get_hopper(hopper["id"], QUALITY_LEAD_HEADERS))
        assert armed["status"] == "QUARANTINED"

        cycle = get_success_data(api.create_sanitation_cycle(
            create_sanitation_cycle_payload(
                line["id"], "2026-09-01T00:30:00Z", "2026-09-01T01:30:00Z"),
            SHIFT_MANAGER_HEADERS))
        get_success_data(api.set_clock(clock_payload("2026-09-01T01:00:00Z"), OPS_ADMIN_HEADERS))
        get_success_data(api.start_sanitation_cycle(cycle["id"], LINE_OPERATOR_HEADERS))
        completed = get_success_data(api.complete_sanitation_cycle(cycle["id"], LINE_OPERATOR_HEADERS))
        assert completed["status"] == "COMPLETED"

        line_after = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert line_after["status"] == "ACTIVE"
        assert line_after["last_sanitation_completed_at"] is not None
        assert is_iso8601_timestamp(line_after["last_sanitation_completed_at"])

        h = get_success_data(api.get_hopper(hopper["id"], QUALITY_LEAD_HEADERS))
        assert h["status"] == "DEPLETED"

    def test_abort_leaves_quarantine_and_overdue_intact(self, api):
        """PRD §3.7: "A `ShiftManager` may instead abort an `IN_PROGRESS` cycle:
        the cycle becomes `ABORTED` and the line returns to `ACTIVE`, but
        `last_sanitation_completed_at` and `next_sanitation_due_at` are
        unchanged — the overdue posture persists — and quarantined hoppers
        remain `QUARANTINED`, since abort does not clear quarantine."

        Design: Corner/state_machines/sanitation_complete_clears_quarantine_to_depleted
        """
        rest, line, ing, recipe, hopper = _standard_store(api, hopper_capacity=5000, load=2000)
        self._quarantine_hopper(api, rest, line, ing, recipe, hopper)
        cycle = get_success_data(api.create_sanitation_cycle(
            create_sanitation_cycle_payload(
                line["id"], "2026-09-01T00:30:00Z", "2026-09-01T01:30:00Z"),
            SHIFT_MANAGER_HEADERS))
        get_success_data(api.set_clock(clock_payload("2026-09-01T01:00:00Z"), OPS_ADMIN_HEADERS))
        get_success_data(api.start_sanitation_cycle(cycle["id"], LINE_OPERATOR_HEADERS))
        aborted = get_success_data(api.abort_sanitation_cycle(cycle["id"], SHIFT_MANAGER_HEADERS))
        assert aborted["status"] == "ABORTED"

        line_after = get_success_data(api.get_assembly_line(line["id"], SHIFT_MANAGER_HEADERS))
        assert line_after["status"] == "ACTIVE"
        assert line_after["last_sanitation_completed_at"] is None

        h = get_success_data(api.get_hopper(hopper["id"], QUALITY_LEAD_HEADERS))
        assert h["status"] == "QUARANTINED"
        assert line_after["posture"] == "RESTRICTED"
