"""License transfers: quantity conservation, terminal lockdown, sufficiency."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    make_account_with_va,
    make_pool,
    make_va,
    setup_approved_transfer,
    setup_pool_with_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestTransferConservation:
    def test_execute_decrements_source_and_creates_target(self, api):
        """PRD §3.8: "First, the source pool's `purchased_quantity` decreases
        by `quantity` and the source pool's `version` increments. Second, the
        destination is resolved: if the target virtual account already holds a
        pool with the same `sku`, `license_model`, and `feature_tier`, that
        pool's `purchased_quantity` increases by `quantity` and its `version`
        increments; otherwise a new pool is created there with those same
        attributes and `purchased_quantity` equal to `quantity`."

        Design: Difficulty/compensating_invariant/transfer_conserves_global_purchased_quantity
        """
        account, va1, va2, pool, transfer = setup_approved_transfer(
            quantity=5, purchased=10, assign_qty=2)

        executed = validate_success(api.execute_license_transfer_request(transfer["id"], ADMIN))
        assert executed["status"] == "EXECUTED"

        source = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert source["purchased_quantity"] == 5

        target_pools, meta = validate_paginated(
            api.list_license_pools_of_va(va2["id"], ADMIN))
        assert len(target_pools) == 1
        assert target_pools[0]["purchased_quantity"] == 5

    def test_execute_conserves_global_purchased_quantity(self, api):
        """PRD §3.8: "First, the source pool's `purchased_quantity` decreases
        by `quantity` ... Second, the destination is resolved: ... otherwise a
        new pool is created there with those same attributes and
        `purchased_quantity` equal to `quantity`."

        Design: Difficulty/compensating_invariant/transfer_conserves_global_purchased_quantity
        """
        account, va1, va2, pool, transfer = setup_approved_transfer(
            quantity=5, purchased=10, assign_qty=2)
        validate_success(api.execute_license_transfer_request(transfer["id"], ADMIN))

        source = validate_success(api.get_license_pool(pool["id"], ADMIN))
        target_pools, meta = validate_paginated(
            api.list_license_pools_of_va(va2["id"], ADMIN))
        total = source["purchased_quantity"] + sum(p["purchased_quantity"] for p in target_pools)
        assert total == 10, f"global purchased_quantity must be conserved, got {total}"


class TestTransferTerminalLockdown:
    def test_approve_of_executed_transfer_rejected(self, api):
        """PRD §3.1: "Attempting a lifecycle transition from a state that does
        not support it is rejected with `ERR_INVALID_STATE`". PRD §3.8: "The
        request transitions to the terminal `EXECUTED` and its `version`
        increments."

        Design: Corner/state_machines/transfer_invalid_from_executed
        """
        account, va1, va2, pool, transfer = setup_approved_transfer(
            quantity=5, purchased=10)
        validate_success(api.execute_license_transfer_request(transfer["id"], ADMIN))

        resp = api.approve_license_transfer_request(
            transfer["id"], {"expected_transfer_version": transfer["version"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_approve_leaves_pools_unchanged(self, api):
        """PRD §3.8: "Approval moves the request from `PENDING_APPROVAL` to
        `APPROVED` and records the approver in `decided_by`". PRD §3.1:
        "Attempting a lifecycle transition from a state that does not support
        it is rejected with `ERR_INVALID_STATE`".

        Design: Corner/state_machines/transfer_invalid_from_executed
        """
        account, va1, va2, pool, transfer = setup_approved_transfer(
            quantity=5, purchased=10)
        validate_success(api.execute_license_transfer_request(transfer["id"], ADMIN))

        resp = api.approve_license_transfer_request(
            transfer["id"], {"expected_transfer_version": transfer["version"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        source = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert source["purchased_quantity"] == 5, "failed approve must not mutate pools"


class TestTransferSufficiency:
    def test_insufficient_transferable_at_create(self, api):
        """PRD §3.8: "Creation already checks the source pool's transferable
        balance — only un-consumed units may move, meaning the pool's
        `purchased_quantity` minus its `consumed_quantity` must be at least
        `quantity`; a shortfall is rejected with `ERR_INSUFFICIENT_TRANSFERABLE`
        (HTTP 422)".

        Design: Corner/validations/insufficient_transferable_at_create
        """
        account, va, pool, device, asg = setup_pool_with_assignment(
            purchased=10, assign_qty=2)
        va2 = make_va(account["id"])

        resp = api.create_license_transfer_request({
            "source_pool_id": pool["id"],
            "target_virtual_account_id": va2["id"],
            "quantity": 9,
            "reason": "HARDWARE_REFRESH",
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TRANSFERABLE)
