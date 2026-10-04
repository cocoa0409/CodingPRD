"""Validation ordering (state vs EOL), purchase adjustment OCC, tier bounds."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    make_account_with_va,
    make_device,
    make_pool,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestStateVsEndOfLifePriority:
    def test_retired_device_with_eol_family_reports_invalid_state(self, api):
        """PRD §2.8: "then generic state-machine legality
        (`ERR_INVALID_STATE`), then account-active gating
        (`ERR_ACCOUNT_NOT_ACTIVE`), then account compliance gating
        (`ERR_ACCOUNT_NON_COMPLIANT`), then product end-of-life gating
        (`ERR_PRODUCT_END_OF_LIFE`)". PRD §2.8: "A request failing several
        checks always reports the earliest failing check in this order."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_device_activate
        """
        account, va = make_account_with_va()
        device = make_device(va["id"], product_family="PF-EOL")
        validate_success(api.activate_device(device["id"], ADMIN))
        validate_success(api.deregister_device(device["id"], ADMIN))
        validate_success(api.retire_device(device["id"], ADMIN))
        get_success_data(api.create_lifecycle_milestone({
            "product_family": "PF-EOL",
            "milestone_type": "END_OF_LIFE",
            "effective_date": "2026-09-01T00:00:00Z",
        }, ADMIN))

        resp = api.activate_device(device["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_invalid_state_reported_despite_in_effect_eol_milestone(self, api):
        """PRD §3.4: "the device's current state must support the transition
        (`ERR_INVALID_STATE` otherwise)". PRD §2.8: "A request failing several
        checks always reports the earliest failing check in this order."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_device_activate
        """
        account, va = make_account_with_va()
        device = make_device(va["id"], product_family="PF-EOL2")
        validate_success(api.activate_device(device["id"], ADMIN))  # REGISTERED now
        get_success_data(api.create_lifecycle_milestone({
            "product_family": "PF-EOL2",
            "milestone_type": "END_OF_LIFE",
            "effective_date": "2026-09-01T00:00:00Z",
        }, ADMIN))

        resp = api.activate_device(device["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPurchaseAdjustmentOcc:
    def test_sequential_adjustment_then_stale_replay_rejected(self, api):
        """PRD §2.6: "adjusting a pool's purchased entitlement requires the
        non-optional field `expected_pool_version`, carrying the client's last
        observed `version` of the target `LicensePool`. If the pool's version
        has advanced since — because a usage sync, an assignment change, or a
        transfer execution legitimately mutated it — the adjustment is
        rejected with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_stale_pool_version_rejected
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], purchased_quantity=5)
        assert pool["version"] == 1

        ok = validate_success(api.purchase_adjustment(
            pool["id"], {"delta": 1, "expected_pool_version": pool["version"]}, ADMIN))
        assert ok["purchased_quantity"] == 6
        assert ok["version"] == 2

        resp = api.purchase_adjustment(
            pool["id"], {"delta": 1, "expected_pool_version": pool["version"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_write_does_not_apply(self, api):
        """PRD §2.6: "If the pool's version has advanced since — because a
        usage sync, an assignment change, or a transfer execution legitimately
        mutated it — the adjustment is rejected with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_stale_pool_version_rejected
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], purchased_quantity=5)
        validate_success(api.purchase_adjustment(
            pool["id"], {"delta": 1, "expected_pool_version": pool["version"]}, ADMIN))

        resp = api.purchase_adjustment(
            pool["id"], {"delta": 1, "expected_pool_version": pool["version"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert after["purchased_quantity"] == 6, "stale write must not apply"
        assert after["version"] == 2

    def test_adjustment_below_zero_rejected(self, api):
        """PRD §3.3: "A reduction that would drive `purchased_quantity` below
        zero is rejected with `ERR_INVALID_QUANTITY` (HTTP 422); a reduction
        that leaves consumption above the new entitlement is allowed and
        simply triggers the overage machinery of §3.2."

        Design: Corner/validations/purchase_adjustment_below_zero_rejected
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], purchased_quantity=3)

        resp = api.purchase_adjustment(
            pool["id"], {"delta": -4, "expected_pool_version": pool["version"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY)


class TestTierDowngrade:
    def test_tier_upgrade_to_lower_tier_rejected(self, api):
        """PRD §3.3: "Feature tier upgrades move a pool upward along the
        `ESSENTIALS` → `ADVANTAGE` → `PREMIER` ladder by supplying a
        `new_tier`; a target tier that is not strictly above the pool's
        current `feature_tier` is rejected with `ERR_TIER_DOWNGRADE_FORBIDDEN`
        (HTTP 422)."

        Design: Corner/errors/every_catalog_error_triggerable
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], feature_tier="ADVANTAGE", purchased_quantity=5)

        resp = api.tier_upgrade(pool["id"], {"new_tier": "ESSENTIALS"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_TIER_DOWNGRADE_FORBIDDEN)
