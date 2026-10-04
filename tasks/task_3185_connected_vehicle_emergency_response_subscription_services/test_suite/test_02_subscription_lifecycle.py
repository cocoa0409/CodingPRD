"""Subscription lifecycle: conversion fee, billing cycle, OCC, caps, clock."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_account_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_account_scenario,
    create_tier,
    create_zone,
    create_account,
    create_vehicle,
    create_trial_subscription,
    convert_subscription,
    convert_and_fail_payment,
    drive_to_emergency_retained,
    set_clock,
    issue_and_acknowledge_remote_command,
    fill_remote_command_cap,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
INGESTION = TEST_USERS["system_ingestion_headers"]
ADVISOR = TEST_USERS["advisor_headers"]


def _get_sub(api, account, subscription_id):
    return get_success_data(
        api.get_subscription(account["id"], subscription_id,
                             make_account_headers(account["id"]))
    )


class TestConversionFeeVariants:
    def test_early_bird_conversion_waives_fee(self, api):
        """PRD §3.2: if the logical-clock date is strictly before
        trial_end_date, the fee is 0 regardless of tier price

        Design: Difficulty/dual_variant_calc/conversion_fee_early_bird_vs_late_conversion
        """
        _, _, account, vehicle, sub = setup_account_scenario(
            tier_code="SAFETY_REMOTE", tier_fee=4000, allows_remote_commands=True,
        )
        converted = convert_subscription(account, sub)
        assert converted["status"] == "ACTIVE"
        assert converted["conversion_fee_paid_cents"] == 0, (
            f"early conversion must waive the fee, got {converted['conversion_fee_paid_cents']}"
        )

    def test_late_conversion_charges_twenty_percent_of_monthly_fee(self, api):
        """PRD §3.2: otherwise the fee is the larger of zero and the tier's
        monthly_fee_cents multiplied by 0.20, with the product rounded half-up
        to the cent exactly once and no second rounding applied after the
        maximum is taken.

        Design: Difficulty/dual_variant_calc/conversion_fee_early_bird_vs_late_conversion
        """
        _, _, account, vehicle, sub = setup_account_scenario(
            tier_code="SAFETY_REMOTE", tier_fee=4000, allows_remote_commands=True,
        )
        set_clock("2026-10-02T00:00:00Z")  # past trial_end_date 2026-10-01
        converted = convert_subscription(account, sub)
        assert converted["status"] == "ACTIVE"
        assert converted["conversion_fee_paid_cents"] == 800, (
            f"20% of 4000 cents = 800, got {converted['conversion_fee_paid_cents']}"
        )


class TestBillingRecoveryCycle:
    def test_payment_failure_then_retry_resets_period_and_usage(self, api):
        """PRD §3.2: A PAYMENT_SUCCEEDED outcome against a PAST_DUE
        subscription returns it to ACTIVE, resetting current_period_start to
        the logical-clock date, pushing next_renewal_date 30 days out, and
        zeroing period_remote_commands_used.

        Design: Difficulty/non_linear_state_machine/subscription_recovery_cycle_active_past_due_active
        """
        _, _, account, vehicle, sub = setup_account_scenario(
            tier_code="SAFETY_REMOTE", tier_fee=4000, allows_remote_commands=True,
        )
        sub = convert_subscription(account, sub)
        issue_and_acknowledge_remote_command(account, vehicle, "LOCK")
        assert _get_sub(api, account, sub["id"])["period_remote_commands_used"] == 1

        # Advance the clock past the pre-reset command's created_at so the
        # reset current_period_start is strictly later than that created_at.
        # PRD §3.5 pins a closed-open window [period_start, period_start+30d),
        # so a command created at the same instant as the reset would still
        # fall inside the new window and the counter would not read zero.
        set_clock("2026-09-01T00:00:00.001Z")

        resp = api.record_billing_event(
            account["id"], sub["id"], {"outcome": "PAYMENT_FAILED"}, BILLING,
        )
        past_due = validate_success(resp)
        assert past_due["status"] == "PAST_DUE"

        resp = api.record_billing_event(
            account["id"], sub["id"], {"outcome": "PAYMENT_SUCCEEDED"}, BILLING,
        )
        active = validate_success(resp)
        assert active["status"] == "ACTIVE"
        assert active["period_remote_commands_used"] == 0, (
            "cycle re-entry must zero the period usage counter"
        )

    def test_renewal_on_active_performs_same_period_reset(self, api):
        """PRD §3.2: A PAYMENT_SUCCEEDED outcome against an ACTIVE subscription
        is a renewal: it leaves the status at ACTIVE but performs the same
        period reset — current_period_start to the logical-clock date,
        next_renewal_date 30 days out, period_remote_commands_used zeroed.

        Design: Difficulty/non_linear_state_machine/subscription_recovery_cycle_active_past_due_active
        """
        _, _, account, vehicle, sub = setup_account_scenario(
            tier_code="SAFETY_REMOTE", tier_fee=4000, allows_remote_commands=True,
        )
        sub = convert_subscription(account, sub)
        issue_and_acknowledge_remote_command(account, vehicle, "LOCK")
        # Advance the clock past the pre-reset command's created_at so the
        # reset current_period_start is strictly later than that created_at
        # (same closed-open window rationale as above, PRD §3.5).
        set_clock("2026-09-01T00:00:00.001Z")
        resp = api.record_billing_event(
            account["id"], sub["id"], {"outcome": "PAYMENT_SUCCEEDED"}, BILLING,
        )
        renewed = validate_success(resp)
        assert renewed["status"] == "ACTIVE"
        assert renewed["period_remote_commands_used"] == 0

    def test_payment_failed_on_trial_rejected_as_invalid_transition(self, api):
        """PRD §3.2: Any other combination of outcome and current status is
        rejected with ERR_BILLING_TRANSITION_INVALID.

        Design: Corner/endpoints/billing_payment_failed_on_trial_rejected_as_invalid_transition
        """
        _, _, account, vehicle, sub = setup_account_scenario()
        assert sub["status"] == "TRIAL"
        resp = api.record_billing_event(
            account["id"], sub["id"], {"outcome": "PAYMENT_FAILED"}, BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_BILLING_TRANSITION_INVALID)
        after = _get_sub(api, account, sub["id"])
        assert after["status"] == "TRIAL"
        assert after["version"] == sub["version"]


class TestEmergencyRetainedLocateCap:
    def _emergency_retained(self, api):
        _, _, account, vehicle, sub = setup_account_scenario()
        retained = drive_to_emergency_retained(account, sub)
        assert retained["status"] == "EMERGENCY_RETAINED"
        return account, vehicle, retained

    def test_exactly_two_locate_commands_allowed_third_rejected(self, api):
        """PRD §3.5: For subscriptions in EMERGENCY_RETAINED, the accounting
        uses a different baseline: exactly 2 emergency LOCATE commands are
        permitted per 30-day window counted from lapse_date (not from
        current_period_start), and only rows whose is_emergency_command flag
        is true count against that fixed cap.
        PRD §3.5: a new command is accepted only when the count is strictly
        less than the cap, and a count equal to the cap is rejected with
        ERR_REMOTE_COMMAND_CAP_REACHED

        Design: Difficulty/boundary_precision_check/emergency_locate_cap_at_exactly_two_in_thirty_day_window
        """
        account, vehicle, retained = self._emergency_retained(api)
        headers = make_account_headers(account["id"])
        rc1 = issue_and_acknowledge_remote_command(account, vehicle, "LOCATE")
        rc2 = issue_and_acknowledge_remote_command(account, vehicle, "LOCATE")
        assert rc1["is_emergency_command"] is True
        assert rc2["is_emergency_command"] is True
        resp = api.create_remote_command(vehicle["id"], {"command_type": "LOCATE"}, headers)
        validate_error(resp, ApiErrorId.ERR_REMOTE_COMMAND_CAP_REACHED)

    def test_emergency_locate_window_keys_on_lapse_date(self, api):
        """PRD §3.5: exactly 2 emergency LOCATE commands are permitted per
        30-day window counted from lapse_date (not from current_period_start)

        Design: Difficulty/boundary_precision_check/emergency_locate_cap_at_exactly_two_in_thirty_day_window
        """
        account, vehicle, retained = self._emergency_retained(api)
        headers = make_account_headers(account["id"])
        issue_and_acknowledge_remote_command(account, vehicle, "LOCATE")
        issue_and_acknowledge_remote_command(account, vehicle, "LOCATE")
        # A further LOCATE still inside the 30-day window from lapse_date is rejected.
        set_clock("2026-09-20T00:00:00Z")
        resp = api.create_remote_command(vehicle["id"], {"command_type": "LOCATE"}, headers)
        validate_error(resp, ApiErrorId.ERR_REMOTE_COMMAND_CAP_REACHED)


class TestSubscriptionPeriodWindow:
    def test_cap_enforced_within_period_and_reset_on_renewal(self, api):
        """PRD §3.5: The per-tier cap is 0 for EMERGENCY_ONLY, 0 for SAFETY,
        10 for SAFETY_REMOTE, and 50 for PREMIUM; a new command is accepted
        only when the count is strictly less than the cap, and a count equal
        to the cap is rejected with ERR_REMOTE_COMMAND_CAP_REACHED.
        PRD §3.2: A PAYMENT_SUCCEEDED outcome against an ACTIVE subscription
        is a renewal: it leaves the status at ACTIVE but performs the same
        period reset — current_period_start to the logical-clock date,
        next_renewal_date 30 days out, period_remote_commands_used zeroed.

        Design: Difficulty/resource_temporal_overlap/subscription_period_window_closed_open_membership
        """
        _, _, account, vehicle, sub = setup_account_scenario(
            tier_code="SAFETY_REMOTE", tier_fee=4000, allows_remote_commands=True,
        )
        sub = convert_subscription(account, sub)
        headers = make_account_headers(account["id"])
        fill_remote_command_cap(account, vehicle, 10, "LOCK")
        resp = api.create_remote_command(vehicle["id"], {"command_type": "LOCK"}, headers)
        validate_error(resp, ApiErrorId.ERR_REMOTE_COMMAND_CAP_REACHED)
        # Advance the clock past the pre-reset commands' created_at so the
        # reset current_period_start is strictly later than those created_at
        # values (same closed-open window rationale as above, PRD §3.5).
        set_clock("2026-09-01T00:00:00.001Z")
        resp = api.record_billing_event(
            account["id"], sub["id"], {"outcome": "PAYMENT_SUCCEEDED"}, BILLING,
        )
        renewed = validate_success(resp)
        assert renewed["period_remote_commands_used"] == 0
        resp = api.create_remote_command(vehicle["id"], {"command_type": "LOCK"}, headers)
        new_command = validate_success(resp, 201)
        assert new_command["status"] in {"PENDING", "SENT"}

    def test_expired_commands_excluded_from_period_count(self, api):
        """PRD §3.5: period_remote_commands_used counts the subscription's
        RemoteCommand rows whose status is ACKNOWLEDGED or FAILED and whose
        created_at falls within the closed-open window from
        current_period_start up to but not including current_period_start
        plus 30 days.
        PRD §3.5: an EXPIRED command never consumes the cap

        Design: Difficulty/resource_temporal_overlap/subscription_period_window_closed_open_membership
        """
        _, _, account, vehicle, sub = setup_account_scenario(
            tier_code="SAFETY_REMOTE", tier_fee=4000, allows_remote_commands=True,
        )
        sub = convert_subscription(account, sub)
        headers = make_account_headers(account["id"])
        get_success_data(api.create_remote_command(
            vehicle["id"], {"command_type": "LOCK"}, headers,
        ), 201)
        get_success_data(api.create_remote_command(
            vehicle["id"], {"command_type": "UNLOCK"}, headers,
        ), 201)
        set_clock("2026-09-01T00:11:00Z")
        sub_after = _get_sub(api, account, sub["id"])
        assert sub_after["period_remote_commands_used"] == 0, (
            "EXPIRED rows must be excluded from the cap aggregation"
        )


class TestSubscriptionStateMachineCorners:
    def test_subscription_created_starts_in_trial_state(self, api):
        """PRD §3.2: On creation the subscription enters TRIAL status
        PRD §2.4: version (integer): a system-managed integer that starts at 1
        on creation and increments by exactly 1 on every mutation.

        Design: Corner/state_machines/subscription_created_starts_in_trial_state
        """
        _, _, account, vehicle, sub = setup_account_scenario()
        assert sub["status"] == "TRIAL"
        assert sub["version"] == 1

    def test_cancelled_subscription_is_terminal_and_rejects_convert(self, api):
        """PRD §3.2: Cancellation is permitted from TRIAL, from ACTIVE, and
        from EMERGENCY_RETAINED; every cancellation lands in the terminal
        CANCELLED state.
        PRD §2.8: (6) state-machine legality — the target resource is in a
        valid from-state for the requested transition, else ERR_INVALID_STATE

        Design: Corner/state_machines/subscription_cancelled_is_terminal_and_rejects_convert
        """
        _, _, account, vehicle, sub = setup_account_scenario()
        headers = make_account_headers(account["id"])
        get_success_data(api.cancel_subscription(account["id"], sub["id"], headers))
        cancelled = _get_sub(api, account, sub["id"])
        resp = api.convert_subscription(
            account["id"], sub["id"],
            {"expected_subscription_version": cancelled["version"]},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert _get_sub(api, account, sub["id"])["status"] == "CANCELLED"

    def test_stale_version_rejected_before_state_check_on_convert(self, api):
        """PRD §2.8: (5) optimistic concurrency —
        expected_subscription_version matches the current version where
        applicable, else ERR_STALE_VERSION; (6) state-machine legality
        PRD §2.8: Later rules are consulted only after all earlier rules pass.

        Design: Corner/validations/stale_version_rejected_before_state_check_on_convert
        """
        _, _, account, vehicle, sub = setup_account_scenario()
        headers = make_account_headers(account["id"])
        pre_cancel_version = sub["version"]
        get_success_data(api.cancel_subscription(account["id"], sub["id"], headers))
        resp = api.convert_subscription(
            account["id"], sub["id"],
            {"expected_subscription_version": pre_cancel_version},
            headers,
        )
        err = validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert err["error_id"] != "ERR_INVALID_STATE"

    def test_stale_convert_after_successful_convert_returns_412(self, api):
        """PRD §2.7: If the supplied value does not equal the subscription's
        current version, the request is rejected with ERR_STALE_VERSION
        (HTTP 412), and no state change occurs.

        Design: Corner/cross_cutting_layers/stale_convert_after_successful_convert_returns_412
        """
        _, _, account, vehicle, sub = setup_account_scenario()
        headers = make_account_headers(account["id"])
        captured_version = sub["version"]
        converted = convert_subscription(account, sub)
        assert converted["status"] == "ACTIVE"
        resp = api.convert_subscription(
            account["id"], sub["id"],
            {"expected_subscription_version": captured_version},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = _get_sub(api, account, sub["id"])
        assert after["status"] == "ACTIVE"
        assert after["version"] == captured_version + 1


class TestSubscriptionComputedAndListing:
    def test_trial_dates_computed_from_logical_clock(self, api):
        """PRD §3.2: the server stamps trial_start_date from the logical
        clock, and trial_end_date is computed as exactly 30 days after the
        trial start.
        PRD §3.2: next_renewal_date is computed as 30 days after
        current_period_start while the subscription is ACTIVE (and null in
        any other status)

        Design: Corner/entities/subscription_trial_end_date_is_computed_and_client_input_ignored
        """
        _, _, account, vehicle, sub = setup_account_scenario()
        assert sub["trial_start_date"].startswith("2026-09-01")
        assert sub["trial_end_date"].startswith("2026-10-01"), (
            f"trial_end_date must be start + 30 days, got {sub['trial_end_date']}"
        )
        assert sub["status"] == "TRIAL"
        assert sub["next_renewal_date"] is None

    def test_subscriptions_list_paginates_with_envelope_fields(self, api):
        """PRD §2.3: The meta object of every list response carries four
        pagination fields: limit, offset, total_count, and has_more.

        Design: Corner/entities/subscriptions_list_paginates_with_envelope_fields
        """
        create_tier(code="SAFETY")
        create_zone(region_code="TX")
        account = create_account()
        headers = make_account_headers(account["id"])
        v1 = create_vehicle(account)
        v2 = create_vehicle(account)
        create_trial_subscription(account, v1, "SAFETY")
        create_trial_subscription(account, v2, "SAFETY")

        data1, meta1 = validate_paginated(
            api.list_account_subscriptions(account["id"], headers,
                                           params={"limit": 1, "offset": 0})
        )
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_account_subscriptions(account["id"], headers,
                                           params={"limit": 1, "offset": 1})
        )
        assert len(data2) == 1
        assert meta2["has_more"] is False


class TestClockDrivenTransitions:
    def test_clock_advances_lapse_then_cancellation(self, api):
        """PRD §2.6: Advancing the clock fires every time-based transition
        that has become due: a PAST_DUE subscription whose retry window has
        closed lapses, a LAPSED subscription whose retention window has closed
        is cancelled, and any RemoteCommand whose expires_at has been reached
        flips to EXPIRED.
        PRD §3.2: When the logical clock reaches 10 days after the date a
        PAST_DUE subscription entered that state without a successful payment,
        the subscription transitions automatically to LAPSED; lapse_date is
        stamped from the logical clock and next_renewal_date becomes null.

        Design: Corner/cross_cutting_layers/clock_set_advances_lapse_and_cancellation_epochs
        """
        _, _, account, vehicle, sub = setup_account_scenario()
        convert_subscription(account, sub)
        set_clock("2026-09-02T00:00:00Z")
        get_success_data(api.record_billing_event(
            account["id"], sub["id"], {"outcome": "PAYMENT_FAILED"}, BILLING,
        ))
        # PAST_DUE entered 2026-09-02; lapse at +10 days -> 2026-09-12.
        set_clock("2026-09-12T00:00:00Z")
        lapsed = _get_sub(api, account, sub["id"])
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapse_date"] is not None
        assert lapsed["lapse_date"].startswith("2026-09-12")
        assert lapsed["next_renewal_date"] is None
        # Retention window closes at lapse_date + 30 days = 2026-10-12.
        set_clock("2026-10-13T00:00:00Z")
        cancelled = _get_sub(api, account, sub["id"])
        assert cancelled["status"] == "CANCELLED"
