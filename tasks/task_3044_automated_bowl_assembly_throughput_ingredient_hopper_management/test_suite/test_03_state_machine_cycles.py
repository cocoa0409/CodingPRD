"""Non-linear state machines: the Order remake cycle and the Hopper
quarantine cycle with drift-window reset."""

import pytest

from test_helpers import (
    CUSTOMER_HEADERS,
    LINE_OPERATOR_HEADERS,
    OPS_ADMIN_HEADERS,
    QUALITY_LEAD_HEADERS,
    SHIFT_MANAGER_HEADERS,
    get_success_data,
    make_line_operator_headers,
    make_quality_lead_headers,
    clock_payload,
    create_restaurant_payload,
    create_assembly_line_payload,
    create_ingredient_payload,
    create_recipe_payload,
    create_hopper_payload,
    load_hopper_payload,
    create_order_payload,
    submit_verification_payload,
    calibration_adjustment_payload,
)


def _setup_single_hopper_store(api):
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
    return rest, line, ing, recipe


class TestOrderVerificationRemakeCycle:
    """Order cycles QUEUED -> ASSEMBLING -> VERIFICATION -> QUEUED until the
    remake guard cancels it on the fourth failure."""

    def test_third_failure_requeues_and_fourth_cancels(self, api):
        """PRD §3.6: "When any verification is `FAIL` and the order's
        `remake_count` is still below 3, the order returns `VERIFICATION → QUEUED`:
        `remake_count` increments"
        PRD §3.6: "When a verification fails and `remake_count` has already
        reached 3, the order instead moves `VERIFICATION → CANCELLED` — the
        fourth failure cancels"

        Design: Difficulty/non_linear_state_machine/order_verification_remake_cycle
        """
        rest, line, ing, recipe = _setup_single_hopper_store(api)
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))

        for expected_remake in (1, 2, 3):
            get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
            failed = get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 110.0}]), LINE_OPERATOR_HEADERS))
            assert failed["status"] == "QUEUED"
            assert failed["remake_count"] == expected_remake

        # The third failed verification gives the hopper three drift samples at
        # +10% — drift exceeds 3.0 and the hopper quarantines (PRD §3.6 fires
        # the cascade on re-queue too), which also force-reroutes the re-queued
        # order to MANUAL. A QualityLead clears the quarantine and a
        # ShiftManager reroutes the order back to AUTOMATED so the fourth
        # remake can dispense from the hopper again.
        get_success_data(api.create_calibration_adjustment(
            hopper["id"], calibration_adjustment_payload(1.0), QUALITY_LEAD_HEADERS))
        get_success_data(api.reroute_order(
            order["id"], {"target_route": "AUTOMATED", "target_line_id": line["id"]},
            SHIFT_MANAGER_HEADERS))

        get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
        cancelled = get_success_data(api.submit_order_verification(
            order["id"], submit_verification_payload(
                [{"hopper_id": hopper["id"], "actual_grams": 110.0}]), LINE_OPERATOR_HEADERS))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["remake_count"] == 3

    def test_failed_dispense_reclassified_to_waste_not_returned(self, api):
        """PRD §3.6: "for each failed measurement the expected grams move from
        the hopper's `cumulative_dispensed_grams` into its `cumulative_waste_grams`
        without returning to `current_grams`"

        Design: Difficulty/non_linear_state_machine/order_verification_remake_cycle
        """
        rest, line, ing, recipe = _setup_single_hopper_store(api)
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=2000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(1000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        order = get_success_data(api.create_order(
            create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
        for cycle in range(4):
            get_success_data(api.start_order_assembly(order["id"], LINE_OPERATOR_HEADERS))
            get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 110.0}]), LINE_OPERATOR_HEADERS))
            if cycle == 2:
                # Three failed verifications at +10% quarantine the hopper
                # (drift 10.0 > 3.0) and force-reroute the re-queued order to
                # MANUAL; a QualityLead clears the quarantine and a
                # ShiftManager reroutes the order back to AUTOMATED so the
                # fourth dispense draws from the hopper again.
                get_success_data(api.create_calibration_adjustment(
                    hopper["id"], calibration_adjustment_payload(1.0), QUALITY_LEAD_HEADERS))
                get_success_data(api.reroute_order(
                    order["id"], {"target_route": "AUTOMATED", "target_line_id": line["id"]},
                    SHIFT_MANAGER_HEADERS))
        h = get_success_data(api.get_hopper(hopper["id"], LINE_OPERATOR_HEADERS))
        # Four dispenses of 100 each, all four reclassified to waste.
        assert h["cumulative_waste_grams"] == pytest.approx(400.0, abs=0.01)
        assert h["cumulative_dispensed_grams"] == pytest.approx(0.0, abs=0.01)
        assert h["current_grams"] == pytest.approx(600.0, abs=0.01)


class TestHopperServiceQuarantineCycleReset:
    """Hopper cycles IN_SERVICE -> QUARANTINED -> IN_SERVICE; the calibration
    adjustment closes the loop and resets the drift window."""

    def _drive_to_quarantine(self, api, rest, line, ing, recipe, hopper):
        verifier = make_line_operator_headers("op_verifier_1")
        for _ in range(3):
            order = get_success_data(api.create_order(
                create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
            get_success_data(api.start_order_assembly(order["id"], verifier))
            get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 104.0}]), verifier))

    def test_quarantine_then_adjustment_resets_drift_window(self, api):
        """PRD §2.7: "When `drift_pct` is not null and its absolute value is
        strictly greater than 3.0, the hopper is quarantined automatically"
        PRD §3.6: "The hopper's `calibration_coefficient` becomes the new value,
        `drift_window_anchor` resets to now, `drift_pct` recomputes to null as
        the window empties, the hopper returns `QUARANTINED → IN_SERVICE`, and
        the line posture recomputes."

        Design: Difficulty/non_linear_state_machine/hopper_service_quarantine_cycle_reset
        """
        rest, line, ing, recipe = _setup_single_hopper_store(api)
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=5000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(2000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        self._drive_to_quarantine(api, rest, line, ing, recipe, hopper)

        armed = get_success_data(api.get_hopper(hopper["id"], QUALITY_LEAD_HEADERS))
        assert armed["status"] == "QUARANTINED"
        assert armed["drift_pct"] == pytest.approx(4.00, abs=0.01)

        approver = make_quality_lead_headers("qa_approver_1")
        adjustment = get_success_data(api.create_calibration_adjustment(
            hopper["id"], calibration_adjustment_payload(0.95), approver))
        assert adjustment["old_coefficient"] == pytest.approx(1.0, abs=1e-9)
        assert adjustment["drift_pct_observed"] == pytest.approx(4.00, abs=0.01)
        assert adjustment["approved_by_user_id"] == "qa_approver_1"

        after = get_success_data(api.get_hopper(hopper["id"], QUALITY_LEAD_HEADERS))
        assert after["status"] == "IN_SERVICE"
        assert after["calibration_coefficient"] == pytest.approx(0.95, abs=1e-9)
        assert after["drift_pct"] is None

    def test_drift_reaches_null_only_after_enough_samples(self, api):
        """PRD §2.7: "If fewer than 3 such samples exist, `drift_pct` is null —
        the system refuses to judge drift on insufficient data."

        Design: Difficulty/non_linear_state_machine/hopper_service_quarantine_cycle_reset
        """
        rest, line, ing, recipe = _setup_single_hopper_store(api)
        hopper = get_success_data(api.create_hopper(
            create_hopper_payload(line["id"], ing["id"], capacity_grams=5000, station_slot=0,
                                  calibration_coefficient=1.0), OPS_ADMIN_HEADERS))
        get_success_data(api.load_hopper(hopper["id"], load_hopper_payload(2000, hopper["version"]),
                                         LINE_OPERATOR_HEADERS))
        verifier = make_line_operator_headers("op_verifier_1")
        # Two verified orders only: still below the 3-sample minimum.
        for _ in range(2):
            order = get_success_data(api.create_order(
                create_order_payload(rest["id"], recipe["id"], recipe["version"]), CUSTOMER_HEADERS))
            get_success_data(api.start_order_assembly(order["id"], verifier))
            get_success_data(api.submit_order_verification(
                order["id"], submit_verification_payload(
                    [{"hopper_id": hopper["id"], "actual_grams": 104.0}]), verifier))
        h = get_success_data(api.get_hopper(hopper["id"], QUALITY_LEAD_HEADERS))
        assert h["status"] == "IN_SERVICE"
        assert h["drift_pct"] is None
