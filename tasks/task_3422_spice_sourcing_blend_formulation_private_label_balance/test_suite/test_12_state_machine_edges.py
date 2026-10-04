"""State-machine edges: illegal from-states, terminal lockdown, re-gating."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_supplier, create_received_lot, create_active_formula,
    create_blend_run, create_committed_blend_run, setup_produced_batch,
    formula_payload, formula_line_payload, recall_case_payload,
    batch_for_run, get_lot, get_recall_case,
)


class TestIllegalFromStates:
    def test_disposition_on_received_lot_invalid_state(self, api):
        """PRD §3.2: "A disposition attempted against a lot that is not in a
        legal from-state for the requested action — such as a `RECEIVED` lot
        that has never been tested, or an `ACCEPTED` lot — is rejected with
        `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/disposition_on_received_lot_invalid_state
        """
        supplier = create_supplier()
        lot = create_received_lot(supplier["id"], spice_code="CUMIN",
                                  origin_region="Aleppo", quantity_kg=40,
                                  flavor_intensity_units=60.0)
        resp = api_client.disposition_lot(
            lot["id"], {"action": "QUARANTINE"},
            TEST_USERS["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_lot(lot["id"])["status"] == "RECEIVED"

    def test_blend_void_twice_invalid_state(self, api):
        """PRD §3.4: "Voiding a `DRAFT` run simply moves it to `VOIDED` —
        nothing was consumed, so no lot quantities change." PRD §3.4:
        "`VOIDED` is terminal." PRD §2.8: "a blend run must be `DRAFT` or
        `COMMITTED` (and not referenced by any `COMPLETED` production run) to
        be voided ... else `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/blend_void_twice_invalid_state
        """
        formula = create_active_formula(
            "VOID-1", lines=[dict(spice_code="CUMIN", target_proportion_pct=100.0,
                                  min_lot_flavor_units=0.0)])
        br = create_blend_run(formula["id"], "COST_MIN", 5)
        first = validate_success(api_client.void_blend_run(
            br["id"], TEST_USERS["flavor_scientist_headers"]), 200)
        assert first["status"] == "VOIDED"
        resp = api_client.void_blend_run(br["id"],
                                         TEST_USERS["flavor_scientist_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_run_complete_twice_invalid_state(self, api):
        """PRD §3.6: "Both completion and cancellation attempted on a run in
        any other state are rejected with `ERR_INVALID_STATE`."

        The second complete creates no second finished batch.

        Design: Corner/state_machines/run_complete_twice_invalid_state
        """
        s = setup_produced_batch(product_code="CMP-2", target_batch_kg=10,
                                 window_start="2026-09-14T08:00:00Z",
                                 window_end="2026-09-14T12:00:00Z")
        assert s["run"]["status"] == "SCHEDULED"
        resp = api_client.complete_production_run(
            s["run"]["id"], TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert batch_for_run(s["run"]["id"])["id"] == s["batch"]["id"]

    def test_recall_initiate_twice_invalid_state(self, api):
        """PRD §3.7: "initiating a case not in `DRAFT` is rejected with
        `ERR_INVALID_STATE`". PRD §3.7: "an empty scope is legitimate — a case
        may initiate with an empty `affected_batch_ids`".

        The second initiate fails and the frozen (empty) scope is unchanged.

        Design: Corner/state_machines/recall_initiate_twice_invalid_state
        """
        supplier = create_supplier()
        lot = create_received_lot(supplier["id"], spice_code="CUMIN",
                                  origin_region="Aleppo", quantity_kg=40,
                                  flavor_intensity_units=60.0)
        resp = api_client.create_recall_case(
            recall_case_payload(trigger_type="LOT_SUSPECT", scope_policy="FINAL",
                                suspect_lot_id=lot["id"]),
            TEST_USERS["recall_coordinator_headers"])
        case = validate_success(resp, 201)
        first = validate_success(api_client.initiate_recall_case(
            case["id"], TEST_USERS["recall_coordinator_headers"]), 200)
        assert first["status"] == "INITIATED"
        resp = api_client.initiate_recall_case(
            case["id"], TEST_USERS["recall_coordinator_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_recall_case(case["id"])
        assert after["affected_batch_ids"] == []
        assert after["affected_quantity_kg"] == 0


class TestFormulaActivationGate:
    def test_formula_activate_empty_rejected(self, api):
        """PRD §3.3: "Activating a `DRAFT` formula requires the sum of its
        lines' `target_proportion_pct` to sit within 0.01 of the 100.0 target
        — inclusive, so a sum of 99.99 or 100.01 passes, while a formula with
        no lines at all sums to 0 and fails — else activation is rejected with
        `ERR_PROPORTION_SUM_INVALID` (HTTP 422)."

        Design: Corner/state_machines/formula_activate_empty_rejected
        """
        resp = api_client.create_formula(
            formula_payload("EMPTY-1", target_flavor_units=80.0),
            TEST_USERS["flavor_scientist_headers"])
        formula = validate_success(resp, 201)
        resp = api_client.activate_formula(
            formula["id"], TEST_USERS["flavor_scientist_headers"])
        validate_error(resp, ApiErrorId.ERR_PROPORTION_SUM_INVALID)
        after = validate_success(api_client.get_formula(
            formula["id"], TEST_USERS["flavor_scientist_headers"]), 200)
        assert after["status"] == "DRAFT"

    def test_formula_activate_sum_correction_then_success(self, api):
        """PRD §3.3: "Activating a `DRAFT` formula requires the sum of its
        lines' `target_proportion_pct` to sit within 0.01 of the 100.0 target
        — inclusive, so a sum of 99.99 or 100.01 passes ... else activation is
        rejected with `ERR_PROPORTION_SUM_INVALID` (HTTP 422)."

        Sum 90.0 fails; after adding the missing 10% line the same formula
        activates — the gate is re-evaluated per attempt.

        Design: Corner/state_machines/formula_activate_sum_correction_then_success
        """
        resp = api_client.create_formula(
            formula_payload("SUM-1", target_flavor_units=80.0),
            TEST_USERS["flavor_scientist_headers"])
        formula = validate_success(resp, 201)
        for line in (dict(spice_code="BLACK_PEPPER", target_proportion_pct=60.0,
                          min_lot_flavor_units=40.0),
                     dict(spice_code="PAPRIKA", target_proportion_pct=30.0,
                          min_lot_flavor_units=40.0)):
            validate_success(api_client.add_formula_line(
                formula["id"], formula_line_payload(**line),
                TEST_USERS["flavor_scientist_headers"]), 201)
        resp = api_client.activate_formula(
            formula["id"], TEST_USERS["flavor_scientist_headers"])
        validate_error(resp, ApiErrorId.ERR_PROPORTION_SUM_INVALID)
        validate_success(api_client.add_formula_line(
            formula["id"],
            formula_line_payload(spice_code="CUMIN", target_proportion_pct=10.0,
                                 min_lot_flavor_units=40.0),
            TEST_USERS["flavor_scientist_headers"]), 201)
        activated = validate_success(api_client.activate_formula(
            formula["id"], TEST_USERS["flavor_scientist_headers"]), 200)
        assert activated["status"] == "ACTIVE"


class TestShipTerminalLockdown:
    def test_batch_ship_happy_then_reship_invalid(self, api):
        """PRD §3.6: "A successful ship moves `commercial_status` to `SHIPPED`,
        which is terminal for the commercial dimension." PRD §3.6: "the
        batch's `commercial_status` must be `CREATED` (else
        `ERR_INVALID_STATE`)".

        At the clock default the batch has its full shelf life remaining, so
        the first ship succeeds; the second is rejected.

        Design: Corner/state_machines/batch_ship_happy_then_reship_invalid
        """
        s = setup_produced_batch(product_code="SHP-1", target_batch_kg=10,
                                 window_start="2026-09-15T08:00:00Z",
                                 window_end="2026-09-15T12:00:00Z")
        resp = api_client.ship_batch(s["batch"]["id"],
                                     TEST_USERS["supply_planner_headers"])
        shipped = validate_success(resp, 200)
        assert shipped["commercial_status"] == "SHIPPED"
        resp = api_client.ship_batch(s["batch"]["id"],
                                     TEST_USERS["supply_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
