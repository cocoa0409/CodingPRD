"""Validation priority conflicts: which rejection surfaces when two rules both fail."""

from test_helpers import (
    CURATOR,
    DCM,
    PICKER,
    ApiErrorId,
    list_lines,
    setup_draft_order,
    setup_released_order,
    setup_shipped_order,
    validate_error,
    validate_success,
)


class TestReleasedOrderReleaseConflictStateBeatsCuration:
    """State legality outranks the curation gate on a second release."""

    def _released_with_revoked_item(self, api):
        scenario = setup_released_order(
            api,
            lines_spec=[{"price": 5000, "qty": 2, "bundle": 8, "on_hand": 10,
                         "sku": "SKU-5001"}],
        )
        validate_success(api.revoke_curation_review(scenario["review"]["id"], CURATOR))
        return scenario

    def test_the_rejected_release_reports_the_state_code_not_the_curation_code(self, api):
        """PRD §3.3: "the release is gated twice over: the order's `order_status` must
        currently be `DRAFT`, and every line's item must have `curation_review_state`
        `APPROVED`."
        PRD §2.9: "State legality. The target resource must be in a state that permits the
        operation, and the transition must be one the state machine lists for that state;
        otherwise `ERR_INVALID_STATE` (409). This guards every state-transition operation."

        Design: Difficulty/priority_pair_validation_conflict/released_order_release_conflict_state_beats_curation
        """
        scenario = self._released_with_revoked_item(api)

        response = api.release_order(scenario["order"]["id"], scenario["acct_headers"])
        error_data = validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        assert error_data["error_id"] != ApiErrorId.ERR_CURATION_NOT_APPROVED, (
            "the state conflict is reported before the curation gate"
        )

    def test_the_order_stays_released_after_the_rejected_release(self, api):
        """PRD §3.3: "A successful release sets `order_status` to `RELEASED`, leaves
        `fulfillment_status` at `AWAITING_RELEASE`, and increments the order's `version`
        by 1".

        Design: Difficulty/priority_pair_validation_conflict/released_order_release_conflict_state_beats_curation
        """
        scenario = self._released_with_revoked_item(api)

        api.release_order(scenario["order"]["id"], scenario["acct_headers"])
        after = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))

        assert after["order_status"] == "RELEASED"
        assert after["version"] == scenario["order"]["version"], (
            "the rejected second release did not advance the order"
        )


class TestAllocateConflictAuthBeatsState:
    """The role check outranks the state check on a picker's allocation."""

    def _draft(self, api):
        return setup_draft_order(
            api,
            lines_spec=[{"price": 4000, "qty": 2, "bundle": 8, "on_hand": 10,
                         "sku": "SKU-5101"}],
        )

    def test_a_picker_allocation_reports_unauthorized_not_invalid_state(self, api):
        """PRD §2.9: "The chain is deliberate in a few places: authentication precedes
        authorization, existence precedes ownership, and state legality precedes the
        version precondition".
        PRD §4: "| POST | `/orders/{id}/allocate` | Run the center selector, reserve the
        units and price the handling fees. | `CustomerAccount` |"

        Design: Difficulty/priority_pair_validation_conflict/allocate_conflict_auth_beats_state
        """
        scenario = self._draft(api)

        response = api.allocate_order(
            scenario["order"]["id"],
            {"expected_order_version": scenario["order"]["version"]}, PICKER)
        error_data = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

        assert error_data["error_id"] != ApiErrorId.ERR_INVALID_STATE, (
            "the role check pre-empts the state check on an unreleased order"
        )

    def test_the_refused_allocation_reserves_nothing_and_leaves_the_draft(self, api):
        """PRD §3.4: "Committing the allocation has a wide footprint, because an order is
        only as real as the units it holds."
        PRD §3.3: "The order is created as a draft: `order_status` begins `DRAFT` and
        `fulfillment_status` begins `AWAITING_RELEASE`".

        Design: Difficulty/priority_pair_validation_conflict/allocate_conflict_auth_beats_state
        """
        scenario = self._draft(api)

        api.allocate_order(scenario["order"]["id"],
                           {"expected_order_version": scenario["order"]["version"]}, PICKER)

        after = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        assert after["order_status"] == "DRAFT"
        assert after["fulfillment_status"] == "AWAITING_RELEASE"
        assert after["allocated_dc_id"] is None

        stock = validate_success(api.get_stock(scenario["stock_rows"][0]["id"], DCM))
        assert stock["reserved_units"] == 0, "no reservation was written"


class TestPickConflictStateBeatsDcLockdown:
    """The task-state precondition outranks the posture gate on a reopened pick."""

    def _lockdown_after_cutoff(self, api):
        scenario = setup_shipped_order(api, qty=1, price=3500, on_hand=6, sku="SKU-5201")
        validate_success(api.reeducate(
            scenario["dc"]["id"],
            {"hold_action": "RAISE", "reason": "posture hold before the recheck"}, DCM))
        return scenario

    def test_a_pick_against_a_reopened_task_reports_invalid_state(self, api):
        """PRD §3.6: "Three conditions must hold before a pick may start: the order's
        `fulfillment_status` must be `ALLOCATED`, the line's pick task must be in
        `pick_status` `QUEUED`, and the allocated center's `operations_posture` must not be
        `LOCKDOWN`".
        PRD §2.9: "State legality. The target resource must be in a state that permits the
        operation, and the transition must be one the state machine lists for that state;
        otherwise `ERR_INVALID_STATE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/pick_conflict_state_beats_dc_lockdown
        """
        scenario = self._lockdown_after_cutoff(api)
        line = list_lines(api, scenario["acct"], scenario["order"])[0]

        response = api.pick_line(scenario["order"]["id"], line["id"],
                                 {"requested_units": 1}, PICKER)
        error_data = validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        assert error_data["error_id"] != ApiErrorId.ERR_DC_LOCKDOWN, (
            "the task-state precondition is reported before the posture gate"
        )

    def test_the_reopened_task_and_the_lockdown_posture_both_hold(self, api):
        """PRD §3.8: "It is `LOCKDOWN` whenever an open quality or damage hold exists on
        the center".
        PRD §3.8: "fourth, each of those lines reopens its pick task by writing
        `shortage_disposition` `NONE` and returning `pick_status` to `PICKING`."

        Design: Difficulty/priority_pair_validation_conflict/pick_conflict_state_beats_dc_lockdown
        """
        scenario = self._lockdown_after_cutoff(api)
        line = list_lines(api, scenario["acct"], scenario["order"])[0]
        task = scenario["tasks"][0]

        api.pick_line(scenario["order"]["id"], line["id"], {"requested_units": 1}, PICKER)

        current = validate_success(api.get_pick_task(task["id"], DCM))
        assert current["pick_status"] == "PICKING", "not rolled back to QUEUED"

        dc = validate_success(api.get_distribution_center(scenario["dc"]["id"], DCM))
        assert dc["operations_posture"] == "LOCKDOWN"