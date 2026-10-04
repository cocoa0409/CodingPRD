"""Storm lifecycle state machine: cyclic escalation, invalid transitions,
terminal lockdown, close/de-escalation gates, and storm-level OCC."""
from test_helpers import (
    activate_storm,
    ApiErrorId,
    create_storm,
    create_unit_for,
    deescalate_storm,
    escalate_storm,
    file_condition_report,
    get_storm,
    open_checklist,
    set_clock,
    setup_storm_with_unit,
    validate_error,
    validate_success,
)


class TestWatchWarningCycle:
    def test_escalate_deescalate_loop_increments_warning_count(self, api, admin_headers):
        """PRD §3.1: "From `WATCH`, the command center may escalate to `WARNING`,
        which increments `warning_count` by one each time; the storm may also
        fall back from `WARNING` to `WATCH` and re-escalate any number of times,
        so `warning_count` is a cyclic escalation counter rather than a one-shot
        flag."

        Design: Difficulty/non_linear_state_machine/storm_event_watch_warning_cycle
        """
        storm = create_storm(clock="2026-09-10T08:00:00Z")
        storm = escalate_storm(storm)
        storm = deescalate_storm(storm)
        assert storm["status"] == "WATCH"
        resp = api.escalate_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, admin_headers
        )
        storm = validate_success(resp)
        assert storm["status"] == "WARNING"
        assert storm["warning_count"] == 2, (
            f"two WATCH->WARNING entries must count 2, got {storm['warning_count']}"
        )
        assert storm["version"] == 4

    def test_warning_count_stays_at_one_after_single_escalation(self, api, admin_headers):
        """PRD §3.1: "From `WATCH`, the command center may escalate to `WARNING`,
        which increments `warning_count` by one each time; the storm may also
        fall back from `WARNING` to `WATCH` and re-escalate any number of times,
        so `warning_count` is a cyclic escalation counter rather than a one-shot
        flag."

        Design: Difficulty/non_linear_state_machine/storm_event_watch_warning_cycle
        """
        storm = create_storm(clock="2026-09-10T08:00:00Z")
        storm = escalate_storm(storm)
        storm = deescalate_storm(storm)
        # De-escalation WARNING -> WATCH does not touch the counter.
        assert storm["status"] == "WATCH"
        assert storm["warning_count"] == 1
        assert storm["version"] == 3


class TestInvalidAndTerminalTransitions:
    def test_storm_cancel_from_active_returns_invalid_state(self, api, admin_headers):
        """PRD §3.1: "While still in `WATCH` or `WARNING`, the storm may instead
        be called off entirely, moving to `CANCELLED`."
        PRD §2.8: "5. State legality — the target entity is in a state from
        which the requested transition exists (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/storm_cancel_from_active_returns_invalid_state
        """
        storm = create_storm(clock="2026-09-10T08:00:00Z")
        storm = activate_storm(storm)
        resp = api.cancel_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        storm_after = get_storm(storm["id"])
        assert storm_after["status"] == "ACTIVE"
        assert storm_after["version"] == 2, "a failed transition must mutate nothing"

    def test_closed_storm_is_terminal_lockdown(self, api, admin_headers):
        """PRD §3.1: "Finally, `RECOVERY` moves to terminal `CLOSED`, stamped
        with `closed_at`, and only when two gates pass together: every
        registered unit's `menu_tier` must be back to `FULL` (otherwise
        `ERR_UNITS_NOT_RESTORED`), and no unit may hold a checklist run in
        `IN_PROGRESS`, `SUBMITTED`, or `REJECTED` (otherwise
        `ERR_OPEN_CHECKLISTS`)."
        PRD §2.8: "5. State legality — the target entity is in a state from
        which the requested transition exists (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/closed_storm_is_terminal_lockdown
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        storm = activate_storm(ctx["storm"])
        storm = deescalate_storm(storm)
        assert storm["status"] == "RECOVERY"
        resp = api.close_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, admin_headers
        )
        storm = validate_success(resp)
        assert storm["status"] == "CLOSED"
        assert storm["closed_at"] is not None
        # Every lifecycle action out of CLOSED is illegal; escalate stands for
        # the terminal lockdown.
        resp = api.escalate_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        storm_after = get_storm(storm["id"])
        assert storm_after["status"] == "CLOSED"
        assert storm_after["version"] == 4


class TestStormCloseAndDeescalationGates:
    def test_storm_close_blocked_until_all_units_full_menu(self, api, admin_headers):
        """PRD §3.1: "Finally, `RECOVERY` moves to terminal `CLOSED`, stamped
        with `closed_at`, and only when two gates pass together: every
        registered unit's `menu_tier` must be back to `FULL` (otherwise
        `ERR_UNITS_NOT_RESTORED`), and no unit may hold a checklist run in
        `IN_PROGRESS`, `SUBMITTED`, or `REJECTED` (otherwise
        `ERR_OPEN_CHECKLISTS`)."

        Design: Corner/validations/storm_close_blocked_until_all_units_full_menu
        """
        storm = create_storm(clock="2026-09-10T08:00:00Z")
        create_unit_for(storm, unit_code="U-1", address="1 Storm Way")
        u2 = create_unit_for(storm, unit_code="U-2", address="2 Storm Way")
        storm = activate_storm(storm)
        file_condition_report(
            u2["id"], power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        storm = deescalate_storm(storm)
        assert storm["status"] == "RECOVERY"
        resp = api.close_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNITS_NOT_RESTORED)
        assert get_storm(storm["id"])["status"] == "RECOVERY"

    def test_deescalate_active_blocked_while_checklist_in_progress(self, api, admin_headers):
        """PRD §3.1: "Once `ACTIVE`, de-escalation moves the storm to `RECOVERY`
        — but only when every reopening checklist run across the storm's units
        has left the `IN_PROGRESS` state; if any unit still has a run
        `IN_PROGRESS`, the de-escalation is rejected with
        `ERR_UNITS_STABILIZING`."

        Design: Corner/validations/deescalate_active_blocked_while_checklist_in_progress
        """
        ctx = setup_storm_with_unit(clock="2026-09-10T08:00:00Z")
        storm = activate_storm(ctx["storm"])
        file_condition_report(
            ctx["unit"]["id"], power="DOWN", water="UP", gas="UP", payment_network="UP"
        )
        open_checklist(ctx["unit"]["id"])
        resp = api.deescalate_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNITS_STABILIZING)
        assert get_storm(storm["id"])["status"] == "ACTIVE"


class TestStormOptimisticConcurrency:
    def test_occ_storm_stale_version_on_escalate(self, api, admin_headers):
        """PRD §2.5: "Every storm-lifecycle action taken against a specific
        storm event — escalation, de-escalation, activation, closure, and
        cancellation — must carry the `expected_storm_event_version` field in
        its request body, holding the caller's last observed `version` of the
        `StormEvent`. Because any command-center write on the storm advances
        its `version`, a value that no longer matches means another write
        (escalate, de-escalate, activate, cancel, or close) has moved the storm
        since the caller last read it, and the caller's picture of the storm
        lifecycle is stale. The request is then rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_storm_stale_version_on_escalate
        """
        storm = create_storm(clock="2026-09-10T08:00:00Z")
        storm = escalate_storm(storm)
        assert storm["status"] == "WARNING"
        stale = storm["version"] - 1
        resp = api.deescalate_storm_event(
            storm["id"], {"expected_storm_event_version": stale}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        resp = api.deescalate_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, admin_headers
        )
        storm = validate_success(resp)
        assert storm["status"] == "WATCH"
        assert storm["version"] == 3

    def test_occ_stale_version_on_activate(self, api, admin_headers):
        """PRD §2.5: "Every storm-lifecycle action taken against a specific
        storm event — escalation, de-escalation, activation, closure, and
        cancellation — must carry the `expected_storm_event_version` field in
        its request body, holding the caller's last observed `version` of the
        `StormEvent`."
        PRD §2.5: "The request is then rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_storm_stale_version_on_escalate
        """
        storm = create_storm(clock="2026-09-10T08:00:00Z")
        storm = escalate_storm(storm)
        # version is now 2; activating with 1 must be rejected as stale.
        resp = api.activate_storm_event(
            storm["id"], {"expected_storm_event_version": 1}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_storm(storm["id"])["status"] == "WARNING"
        resp = api.activate_storm_event(
            storm["id"], {"expected_storm_event_version": storm["version"]}, admin_headers
        )
        storm = validate_success(resp)
        assert storm["status"] == "ACTIVE"
        assert storm["activated_at"] is not None
