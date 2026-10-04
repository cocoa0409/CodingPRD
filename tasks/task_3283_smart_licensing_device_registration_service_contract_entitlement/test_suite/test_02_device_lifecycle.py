"""Device registration lifecycle: re-registration loop and posture gating."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_ts_equal,
    get_success_data,
    make_account_with_va,
    make_assignment,
    make_device,
    make_pool,
    make_registered_device,
    set_clock,
    setup_pool_in_grace,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestDeviceRegistrationCycle:
    def test_reregister_after_deregister_succeeds(self, api):
        """PRD §3.4: "Activation — which transitions the device from `PENDING`
        to `REGISTERED`, or later from `DEREGISTERED` back to `REGISTERED` in
        a re-registration cycle".

        Design: Difficulty/non_linear_state_machine/device_registration_cycle_loop
        """
        account, va = make_account_with_va()
        device = make_device(va["id"])
        set_clock("2026-09-05T00:00:00Z")
        first = validate_success(api.activate_device(device["id"], ADMIN))
        assert first["registration_state"] == "REGISTERED"

        dereg = validate_success(api.deregister_device(device["id"], ADMIN))
        assert dereg["registration_state"] == "DEREGISTERED"

        set_clock("2026-09-06T00:00:00Z")
        second = validate_success(api.activate_device(device["id"], ADMIN))
        assert second["registration_state"] == "REGISTERED"

    def test_reregister_refreshes_registered_at(self, api):
        """PRD §3.4: "Successful activation stamps `registered_at` and
        `last_sync_at` with the logical clock and increments the device's
        `version`."

        Design: Difficulty/non_linear_state_machine/device_registration_cycle_loop
        """
        account, va = make_account_with_va()
        device = make_device(va["id"])
        set_clock("2026-09-05T00:00:00Z")
        first = validate_success(api.activate_device(device["id"], ADMIN))
        assert_ts_equal(first["registered_at"], "2026-09-05T00:00:00Z")

        validate_success(api.deregister_device(device["id"], ADMIN))
        set_clock("2026-09-06T00:00:00Z")
        second = validate_success(api.activate_device(device["id"], ADMIN))
        assert_ts_equal(second["registered_at"], "2026-09-06T00:00:00Z",
            "re-registration must restamp registered_at")
        assert_ts_equal(second["last_sync_at"], "2026-09-06T00:00:00Z")


class TestDeviceActivationPostureGate:
    def test_non_compliant_account_blocks_activation(self, api):
        """PRD §3.4: "the owning account's `compliance_posture` must not be
        `NON_COMPLIANT` (`ERR_ACCOUNT_NON_COMPLIANT` otherwise — an account
        in `GRACE` may still activate)".

        Design: Difficulty/cross_entity_state_dependency/device_activation_gated_by_account_posture
        """
        account, va, pool, device1, asg = setup_pool_in_grace(purchased=1, assign_qty=2)
        device2 = make_device(va["id"])
        set_clock("2026-12-15T00:00:00Z")  # past the 90-day grace deadline

        posture = validate_success(api.get_smart_account(account["id"], ADMIN))
        assert posture["compliance_posture"] == "NON_COMPLIANT"

        resp = api.activate_device(device2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NON_COMPLIANT)

    def test_blocked_device_stays_pending(self, api):
        """PRD §2.5: "Account posture acts as a gate: a `NON_COMPLIANT`
        account may not activate new devices (rejected with
        `ERR_ACCOUNT_NON_COMPLIANT`), while a `GRACE` account retains that
        ability."

        Design: Difficulty/cross_entity_state_dependency/device_activation_gated_by_account_posture
        """
        account, va, pool, device1, asg = setup_pool_in_grace(purchased=1, assign_qty=2)
        device2 = make_device(va["id"])
        set_clock("2026-12-15T00:00:00Z")

        resp = api.activate_device(device2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_NON_COMPLIANT)

        device_after = validate_success(api.get_device(device2["id"], ADMIN))
        assert device_after["registration_state"] == "PENDING", (
            f"blocked activation must leave the device PENDING, got {device_after['registration_state']}")
