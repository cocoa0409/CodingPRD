"""State preconditions: close/archive blocking, subscription expiry overage."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_ts_equal,
    make_account,
    make_account_with_va,
    make_device,
    make_pool,
    make_registered_device,
    make_va,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestAccountClosePreconditions:
    def test_close_blocked_by_registered_device(self, api):
        """PRD §3.1: "Closure is the terminal act and is permitted from either
        `ACTIVE` or `SUSPENDED`, but only when the account is quiet: no device
        under the account may be in `registration_state` `REGISTERED`".

        Design: Corner/state_machines/account_close_blocked_by_registered_device
        """
        account, va = make_account_with_va()
        make_registered_device(va["id"])

        resp = api.close_smart_account(account["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_close_leaves_account_active(self, api):
        """PRD §3.1: "Closure is the terminal act and is permitted from either
        `ACTIVE` or `SUSPENDED`, but only when the account is quiet: no device
        under the account may be in `registration_state` `REGISTERED`". PRD
        §3.1: "Attempting a lifecycle transition from a state that does not
        support it is rejected with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/account_close_blocked_by_registered_device
        """
        account, va = make_account_with_va()
        make_registered_device(va["id"])

        resp = api.close_smart_account(account["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_smart_account(account["id"], ADMIN))
        assert after["status"] == "ACTIVE", "failed close must leave the account ACTIVE"


class TestVirtualAccountArchivePreconditions:
    def test_archive_blocked_by_pending_device(self, api):
        """PRD §3.1: "each virtual account begins `ACTIVE` and can later be
        archived, provided no device under it is still `PENDING` or
        `REGISTERED` and no pool under it is in `IN_GRACE` or
        `OUT_OF_COMPLIANCE`."

        Design: Corner/state_machines/virtual_account_archive_blocked_by_pending_device
        """
        account, va = make_account_with_va()
        make_device(va["id"])  # stays PENDING

        resp = api.archive_virtual_account(va["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSubscriptionExpiry:
    def test_expiry_zeroes_effective_entitlement_and_enters_grace(self, api):
        """PRD §3.2: "The *effective* purchased entitlement for comparison
        purposes is the pool's `purchased_quantity`, except that a
        `SUBSCRIPTION` pool whose `subscription_expires_at` has been reached
        or passed by the logical clock is treated as having zero entitlement —
        subscription expiry alone can therefore push a pool into overage."

        Design: Corner/calculations/subscription_expiry_zeroes_effective_purchased
        """
        account, va = make_account_with_va()
        pool = make_pool(
            va["id"], license_model="SUBSCRIPTION", purchased_quantity=5,
            subscription_expires_at="2026-09-10T00:00:00Z")
        device = make_registered_device(va["id"])
        validate_success(api.create_license_assignment(
            {"device_id": device["id"], "license_pool_id": pool["id"], "quantity": 1}, ADMIN),
            expected_status=201)

        set_clock("2026-09-10T00:00:00Z")
        after = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert after["compliance_state"] == "IN_GRACE", (
            f"consumed 1 > effective purchased 0 at expiry, got {after['compliance_state']}")
        assert_ts_equal(after["grace_deadline"], "2026-12-09T00:00:00Z",
            "grace deadline must be expiry + 90 days")
