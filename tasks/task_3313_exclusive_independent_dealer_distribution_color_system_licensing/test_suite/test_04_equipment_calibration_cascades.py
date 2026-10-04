"""Equipment calibration cycle, license suspension cascades, and rematch gating."""
from test_helpers import (
    ApiErrorId,
    RM,
    api_client,
    make_dealer_principal_headers,
    record_calibration,
    setup_contractor,
    setup_effective_change,
    setup_formula,
    setup_onboarded_dealer,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCalibrationCycle:
    def test_fail_drops_calibrated_unit_back_to_installed(self, api):
        """PRD section 3.3: "A `FAIL` result leaves or returns the unit to
        `INSTALLED` from any of the same three states and increments
        `consecutive_failed_calibrations` by 1; notably a calibrated unit
        that fails drops back to `INSTALLED` and no longer counts as
        calibrated."

        Design: Difficulty/non_linear_state_machine/equipment_calibration_cycle_fail_drop_and_recovery
        """
        ctx = setup_onboarded_dealer()
        after_fail = record_calibration(ctx["equipment"]["id"], "FAIL")
        assert after_fail["status"] == "INSTALLED"
        assert after_fail["consecutive_failed_calibrations"] == 1

    def test_pass_recalibrates_and_reverses_license_suspension(self, api):
        """PRD section 3.3: "whenever a `FAIL` calibration or an overdue
        sweep leaves no `CALIBRATED` unit for the license's colorant system
        at that dealer, the license cascades from `ACTIVE` to `SUSPENDED`;
        whenever a `PASS` calibration again yields a calibrated unit for the
        system, a `SUSPENDED` license cascades back to `ACTIVE`."
        PRD section 3.3: "A `PASS` result moves the unit to `CALIBRATED` from
        any of `INSTALLED`, `CALIBRATED`, or `CALIBRATION_OVERDUE`; it sets
        `last_calibrated_on` to `performed_on`, sets `calibration_due_on` to
        ninety days after `performed_on`, and resets
        `consecutive_failed_calibrations` to 0."

        Design: Difficulty/non_linear_state_machine/equipment_calibration_cycle_fail_drop_and_recovery
        """
        ctx = setup_onboarded_dealer()
        lic_id = ctx["license"]["id"]
        record_calibration(ctx["equipment"]["id"], "FAIL")
        lic_after_fail = validate_success(api.get_license(lic_id, RM))
        assert lic_after_fail["status"] == "SUSPENDED"
        after_pass = record_calibration(ctx["equipment"]["id"], "PASS")
        assert after_pass["status"] == "CALIBRATED"
        assert after_pass["consecutive_failed_calibrations"] == 0
        lic_after_pass = validate_success(api.get_license(lic_id, RM))
        assert lic_after_pass["status"] == "ACTIVE"


class TestFailCascadeBlocksPurchase:
    def test_fail_suspends_license_before_purchase_attempt(self, api):
        """PRD section 3.3: "whenever a `FAIL` calibration or an overdue
        sweep leaves no `CALIBRATED` unit for the license's colorant system
        at that dealer, the license cascades from `ACTIVE` to `SUSPENDED`".

        Design: Difficulty/transitive_cascade/fail_calibration_cascades_to_license_then_blocks_purchase
        """
        ctx = setup_onboarded_dealer()
        setup_contractor(ctx["dealer"]["id"])
        record_calibration(ctx["equipment"]["id"], "FAIL")
        lic = validate_success(api.get_license(ctx["license"]["id"], RM))
        assert lic["status"] == "SUSPENDED"

    def test_suspended_license_rejects_purchase(self, api):
        """PRD section 3.6: "the dealer must hold an `ACTIVE` license
        covering the purchased line's colorant system — `PENDING`, `EXPIRED`,
        `SUSPENDED`, or `REVOKED` do not suffice — else
        `ERR_LICENSE_NOT_ACTIVE`".

        Design: Difficulty/transitive_cascade/fail_calibration_cascades_to_license_then_blocks_purchase
        """
        ctx = setup_onboarded_dealer()
        contractor = setup_contractor(ctx["dealer"]["id"])
        record_calibration(ctx["equipment"]["id"], "FAIL")
        resp = api.create_purchase(
            {
                "contractor_account_id": contractor["id"],
                "product_line_id": ctx["line"]["id"],
                "units": 5,
            },
            make_dealer_principal_headers(ctx["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)


class TestRematchCompletionGatedByEquipment:
    def test_complete_rematch_fails_without_calibrated_unit(self, api):
        """PRD section 3.8: "Completion requires the task's dealer to have at
        least one `CALIBRATED` equipment unit on the colorant system of the
        formula's product line; without one the completion is rejected with
        `ERR_EQUIPMENT_NOT_CALIBRATED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/rematch_task_completion_gated_by_equipment_state
        """
        ctx = setup_onboarded_dealer()
        setup_formula(ctx["line"]["id"])
        _change, tasks_resp = setup_effective_change(ctx)
        tasks, _meta = validate_paginated(tasks_resp)
        task_id = tasks[0]["id"]
        record_calibration(ctx["equipment"]["id"], "FAIL")
        resp = api.complete_rematch_task(
            task_id, make_dealer_principal_headers(ctx["dealer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_NOT_CALIBRATED)

    def test_complete_rematch_succeeds_with_calibrated_unit(self, api):
        """PRD section 3.8: "the `DealerPrincipal` whose `X-User-ID` equals
        the task's `dealer_id` performs the physical color rematch and marks
        the task `DONE`. Completion requires the task's dealer to have at
        least one `CALIBRATED` equipment unit on the colorant system of the
        formula's product line".

        Design: Difficulty/cross_entity_state_dependency/rematch_task_completion_gated_by_equipment_state
        """
        ctx = setup_onboarded_dealer()
        setup_formula(ctx["line"]["id"])
        _change, tasks_resp = setup_effective_change(ctx)
        tasks, _meta = validate_paginated(tasks_resp)
        task_id = tasks[0]["id"]
        done = validate_success(
            api.complete_rematch_task(task_id, make_dealer_principal_headers(ctx["dealer"]["id"]))
        )
        assert done["status"] == "DONE"
