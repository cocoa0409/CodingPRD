"""Consumption reconciliation, usage reports, and tier-upgrade proration tests."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    make_account_with_va,
    make_assignment,
    make_device,
    make_pool,
    make_registered_device,
    set_clock,
    setup_pool_with_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestConsumptionVariants:
    def test_assignment_baseline_counted_before_first_report(self, api):
        """PRD §3.2: "for devices with no accepted report in the current
        period, the sum of their `ACTIVE` assignment `quantity` values against
        the pool counts instead."

        Design: Difficulty/dual_variant_calc/provisional_vs_reconciled_consumption_on_pool
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], purchased_quantity=10)
        device = make_registered_device(va["id"])
        make_assignment(device["id"], pool["id"], quantity=3)

        data = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert data["consumed_quantity"] == 3, (
            f"expected assignment baseline 3, got {data['consumed_quantity']}")

    def test_accepted_report_supersedes_assignment_baseline(self, api):
        """PRD §3.2: "for each device whose latest report for the current
        period has been accepted, the device's own reported line quantity for
        this pool replaces whatever its assignments would otherwise imply —
        the device's reported truth supersedes the assumed install".

        Design: Difficulty/dual_variant_calc/provisional_vs_reconciled_consumption_on_pool
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], purchased_quantity=10)
        device = make_registered_device(va["id"])
        make_assignment(device["id"], pool["id"], quantity=3)

        report = validate_success(api.submit_usage_report(device["id"], {
            "reported_at": "2026-09-02T00:00:00Z",
            "lines": [{"license_pool_id": pool["id"], "quantity": 5}],
        }, ADMIN), expected_status=201)
        assert report["status"] == "ACCEPTED"

        data = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert data["consumed_quantity"] == 5, (
            f"reported truth must supersede the assignment baseline, got {data['consumed_quantity']}")


class TestTierUpgradeProration:
    def test_subscription_pool_gains_prorated_credit(self, api):
        """PRD §3.3: "The credit is the pool's `purchased_quantity` multiplied
        by the exact ratio of remaining days to total days, computed as exact
        rationals and rounded down to whole units only as the final step. The
        credited units are added to `purchased_quantity`."

        Design: Difficulty/dual_variant_calc/subscription_vs_perpetual_tier_upgrade_proration
        """
        account, va = make_account_with_va()
        pool = make_pool(
            va["id"], license_model="SUBSCRIPTION", purchased_quantity=10,
            subscription_expires_at="2027-09-01T00:00:00Z")
        set_clock("2026-10-01T00:00:00Z")  # 30 days elapsed of 365; 335 left

        data = validate_success(api.tier_upgrade(pool["id"], {"new_tier": "ADVANTAGE"}, ADMIN))
        # 10 + floor(10 * 335/365) = 10 + 9 = 19
        assert data["purchased_quantity"] == 19, (
            f"expected prorated credit to 19, got {data['purchased_quantity']}")
        assert data["feature_tier"] == "ADVANTAGE"

    def test_perpetual_pool_gains_no_proration(self, api):
        """PRD §3.3: "For a `PERPETUAL` pool the upgrade changes only the tier
        — `purchased_quantity` is untouched and no proration applies."

        Design: Difficulty/dual_variant_calc/subscription_vs_perpetual_tier_upgrade_proration
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], license_model="PERPETUAL", purchased_quantity=10)
        set_clock("2026-10-01T00:00:00Z")

        data = validate_success(api.tier_upgrade(pool["id"], {"new_tier": "ADVANTAGE"}, ADMIN))
        assert data["purchased_quantity"] == 10, (
            f"perpetual upgrade must not change purchased_quantity, got {data['purchased_quantity']}")
        assert data["feature_tier"] == "ADVANTAGE"

    def test_proration_rounds_down_once_at_the_end(self, api):
        """PRD §3.3: "The credit is the pool's `purchased_quantity` multiplied
        by the exact ratio of remaining days to total days, computed as exact
        rationals and rounded down to whole units only as the final step."

        Design: Difficulty/combinatorial_formula/tier_proration_rounding_order
        """
        account, va = make_account_with_va()
        pool = make_pool(
            va["id"], license_model="SUBSCRIPTION", purchased_quantity=7,
            subscription_expires_at="2027-09-01T00:00:00Z")
        set_clock("2027-05-24T00:00:00Z")  # days_total=365, days_left=100

        data = validate_success(api.tier_upgrade(pool["id"], {"new_tier": "PREMIER"}, ADMIN))
        # 7 + floor(7 * 100/365) = 7 + floor(1.9178) = 7 + 1 = 8
        assert data["purchased_quantity"] == 8, (
            f"expected single final round-down to 8, got {data['purchased_quantity']}")
        assert data["feature_tier"] == "PREMIER"

    def test_proration_uses_whole_day_floors(self, api):
        """PRD §3.3: "first determine the total subscription length in days by
        taking the span from the pool's `created_at` to its
        `subscription_expires_at` and flooring to whole days; then determine
        the remaining days by taking the span from the current logical clock
        to `subscription_expires_at`, flooring to whole days, and never going
        below zero."

        Design: Difficulty/combinatorial_formula/tier_proration_rounding_order
        """
        account, va = make_account_with_va()
        pool = make_pool(
            va["id"], license_model="SUBSCRIPTION", purchased_quantity=11,
            subscription_expires_at="2027-09-01T00:00:00Z")
        set_clock("2027-05-24T00:00:00Z")  # days_left=100, days_total=365

        data = validate_success(api.tier_upgrade(pool["id"], {"new_tier": "ADVANTAGE"}, ADMIN))
        # 11 + floor(11 * 100/365) = 11 + floor(3.0136) = 11 + 3 = 14
        assert data["purchased_quantity"] == 14, (
            f"expected floor-based credit to 14, got {data['purchased_quantity']}")


class TestUsageReportBoundaries:
    def test_equal_timestamp_report_is_accepted(self, api):
        """PRD §3.4: "a report whose `reported_at` is strictly earlier than
        the `reported_at` of the device's last accepted report is stale and
        rejected with `ERR_STALE_REPORT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/usage_report_stale_equal_timestamp_accepted
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], purchased_quantity=100)
        device = make_registered_device(va["id"])
        first = validate_success(api.submit_usage_report(device["id"], {
            "reported_at": "2026-09-10T00:00:00Z",
            "lines": [{"license_pool_id": pool["id"], "quantity": 4}],
        }, ADMIN), expected_status=201)
        assert first["status"] == "ACCEPTED"

        second = validate_success(api.submit_usage_report(device["id"], {
            "reported_at": "2026-09-10T00:00:00Z",
            "lines": [{"license_pool_id": pool["id"], "quantity": 6}],
        }, ADMIN), expected_status=201)
        assert second["status"] == "ACCEPTED", "equal timestamp is not strictly earlier"

    def test_latest_equal_timestamp_report_wins(self, api):
        """PRD §3.2: "for each device whose latest report for the current
        period has been accepted, the device's own reported line quantity for
        this pool replaces whatever its assignments would otherwise imply".

        Design: Difficulty/boundary_precision_check/usage_report_stale_equal_timestamp_accepted
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], purchased_quantity=100)
        device = make_registered_device(va["id"])
        for qty in (4, 6, 7):
            report = validate_success(api.submit_usage_report(device["id"], {
                "reported_at": "2026-09-10T00:00:00Z",
                "lines": [{"license_pool_id": pool["id"], "quantity": qty}],
            }, ADMIN), expected_status=201)
            assert report["status"] == "ACCEPTED"
            data = validate_success(api.get_license_pool(pool["id"], ADMIN))
            assert data["consumed_quantity"] == qty, (
                f"latest report must win: expected {qty}, got {data['consumed_quantity']}")

    def test_report_pool_mismatch_wins_over_staleness(self, api):
        """PRD §2.8: "then coverage overlap (`ERR_COVERAGE_OVERLAP`), then
        report pool mismatch (`ERR_REPORT_POOL_MISMATCH`), then report
        staleness (`ERR_STALE_REPORT`)". PRD §3.4: "every line's pool must
        belong to the same virtual account as the reporting device — a
        cross-segment line rejects the whole submission with
        `ERR_REPORT_POOL_MISMATCH` (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_on_usage_report
        """
        account = get_success_data(api.create_smart_account(
            {"account_ref": "ACCT-MIX", "display_name": "Mixed"}, ADMIN))
        va1 = get_success_data(api.create_virtual_account(
            {"smart_account_id": account["id"], "name": "VA1"}, ADMIN))
        va2 = get_success_data(api.create_virtual_account(
            {"smart_account_id": account["id"], "name": "VA2"}, ADMIN))
        pool_in = make_pool(va1["id"], sku="P-IN", purchased_quantity=10)
        pool_out = make_pool(va2["id"], sku="P-OUT", purchased_quantity=10)
        device = make_registered_device(va1["id"])
        validate_success(api.submit_usage_report(device["id"], {
            "reported_at": "2026-09-10T00:00:00Z",
            "lines": [{"license_pool_id": pool_in["id"], "quantity": 1}],
        }, ADMIN), expected_status=201)

        resp = api.submit_usage_report(device["id"], {
            "reported_at": "2026-09-05T00:00:00Z",  # stale AND foreign pool
            "lines": [{"license_pool_id": pool_out["id"], "quantity": 1}],
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REPORT_POOL_MISMATCH)

    def test_stale_report_rejected_and_mutates_nothing(self, api):
        """PRD §3.4: "a report whose `reported_at` is strictly earlier than
        the `reported_at` of the device's last accepted report is stale and
        rejected with `ERR_STALE_REPORT` (HTTP 422). Reports are append-only:
        a stale or malformed report is persisted with `status` `REJECTED` and
        a `rejection_reason`, and mutates nothing."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_on_usage_report
        """
        account, va = make_account_with_va()
        pool = make_pool(va["id"], purchased_quantity=100)
        device = make_registered_device(va["id"])
        validate_success(api.submit_usage_report(device["id"], {
            "reported_at": "2026-09-10T00:00:00Z",
            "lines": [{"license_pool_id": pool["id"], "quantity": 4}],
        }, ADMIN), expected_status=201)

        resp = api.submit_usage_report(device["id"], {
            "reported_at": "2026-09-09T23:59:59Z",  # one second earlier
            "lines": [{"license_pool_id": pool["id"], "quantity": 9}],
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_REPORT)
        data = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert data["consumed_quantity"] == 4, "stale report must not mutate the pool"
