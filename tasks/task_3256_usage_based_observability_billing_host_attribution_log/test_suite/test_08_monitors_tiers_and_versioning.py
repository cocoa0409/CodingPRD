"""Monitors and plan caps (PRD §3.8), retention-tier window arithmetic
(PRD §2.9, §3.5), and version bookkeeping (PRD §2.4, §2.8)."""
from test_helpers import (
    ApiErrorId,
    FREE_PLAN,
    create_account,
    create_monitor_payload,
    create_plan_tier_config,
    create_retention_tier_payload,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BA, setup_account_with_period


class TestMonitorCap:
    def _setup_free_account_with_monitors(self, api, count):
        set_clock()
        create_plan_tier_config(plan=FREE_PLAN)
        account = create_account(name="Cap Test", plan_tier="FREE")
        created = []
        for i in range(count):
            monitor = validate_success(
                api.create_monitor(
                    account["id"],
                    create_monitor_payload(name=f"m{i + 1}"),
                    BA,
                ),
                expected_status=201,
            )
            assert monitor["status"] == "ACTIVE"
            created.append(monitor)
        return account, created

    def test_create_rejected_at_exactly_max(self, api):
        """PRD §3.8: "The plan's hard cap counts only `ACTIVE` monitors: creating a
        monitor is rejected with `ERR_PLAN_LIMIT` when the account's count of
        `ACTIVE` monitors has already reached the plan's `max_monitors` — the cap is
        reached exactly when the active count equals the cap, so the create that
        would push it over fails."

        Design: Difficulty/boundary_precision_check/plan_monitor_cap_at_exactly_max
        """
        account, _monitors = self._setup_free_account_with_monitors(api, 5)
        resp = api.create_monitor(
            account["id"], create_monitor_payload(name="m6"), BA
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_LIMIT.value)

    def test_create_allowed_at_max_minus_one(self, api):
        """PRD §3.8: "the cap is reached exactly when the active count equals the
        cap, so the create that would push it over fails."

        Design: Difficulty/boundary_precision_check/plan_monitor_cap_at_exactly_max
        """
        account, _monitors = self._setup_free_account_with_monitors(api, 4)
        fifth = validate_success(
            api.create_monitor(account["id"], create_monitor_payload(name="m5"), BA),
            expected_status=201,
        )
        assert fifth["status"] == "ACTIVE"

    def test_muted_monitor_releases_cap_slot(self, api):
        """PRD §3.8: "Muting a monitor moves it from `ACTIVE` to `MUTED` and
        releases its slot against the cap; deletion — a `BillingAdmin`-only
        operation available from any status — moves it to `DELETED`, which likewise
        does not count."

        Design: Difficulty/boundary_precision_check/plan_monitor_cap_at_exactly_max
        """
        account, monitors = self._setup_free_account_with_monitors(api, 5)
        resp = api.create_monitor(
            account["id"], create_monitor_payload(name="m6"), BA
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_LIMIT.value)
        muted = validate_success(api.mute_monitor(account["id"], monitors[0]["id"], BA))
        assert muted["status"] == "MUTED"
        sixth = validate_success(
            api.create_monitor(account["id"], create_monitor_payload(name="m6"), BA),
            expected_status=201,
        )
        assert sixth["status"] == "ACTIVE"


class TestRetentionTierWindows:
    def test_adjacent_half_open_windows_accepted(self, api):
        """PRD §2.9: "A `RetentionTier`'s effective window is **half-open**: it
        covers instants from `effective_from_utc` (inclusive) up to but not
        including `effective_to_utc`. Two tiers on the same account whose half-open
        windows intersect are rejected with `ERR_TIER_WINDOW_OVERLAP`. Adjacent
        windows — one ending exactly where the next begins — do not overlap."

        Design: Difficulty/resource_temporal_overlap/retention_tier_half_open_window_adjacency
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="Half Open")
        validate_success(
            api.create_retention_tier(
                account["id"],
                create_retention_tier_payload(account["version"], name="sept"),
                BA,
            ),
            expected_status=201,
        )
        # Adjacent window starting exactly at the first tier's exclusive end.
        created = validate_success(
            api.create_retention_tier(
                account["id"],
                create_retention_tier_payload(
                    account["version"] + 1,
                    name="oct",
                    effective_from_utc="2026-10-01T00:00:00Z",
                    effective_to_utc="2026-11-01T00:00:00Z",
                ),
                BA,
            ),
            expected_status=201,
        )
        assert created["name"] == "oct"

    def test_overlapping_half_open_windows_rejected(self, api):
        """PRD §2.9: "A `RetentionTier`'s effective window is **half-open**: it
        covers instants from `effective_from_utc` (inclusive) up to but not
        including `effective_to_utc`. Two tiers on the same account whose half-open
        windows intersect are rejected with `ERR_TIER_WINDOW_OVERLAP`. Adjacent
        windows — one ending exactly where the next begins — do not overlap."

        Design: Difficulty/resource_temporal_overlap/retention_tier_half_open_window_adjacency
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="Half Open Reject")
        validate_success(
            api.create_retention_tier(
                account["id"],
                create_retention_tier_payload(account["version"], name="sept"),
                BA,
            ),
            expected_status=201,
        )
        # Starts one second BEFORE the first tier's exclusive end: the half-open
        # windows share an instant, so the overlap rule rejects it.
        resp = api.create_retention_tier(
            account["id"],
            create_retention_tier_payload(
                account["version"] + 1,
                name="overlap",
                effective_from_utc="2026-09-30T23:59:59Z",
                effective_to_utc="2026-11-01T00:00:00Z",
            ),
            BA,
        )
        validate_error(resp, ApiErrorId.ERR_TIER_WINDOW_OVERLAP.value)

    def test_intersecting_half_open_windows_rejected(self, api):
        """PRD §2.9: "Two tiers on the same account whose half-open windows
        intersect are rejected with `ERR_TIER_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_tier_create
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="Conflict B")
        validate_success(
            api.create_retention_tier(
                account["id"],
                create_retention_tier_payload(account["version"], name="first"),
                BA,
            ),
            expected_status=201,
        )
        # A tag policy exists on the account, but tier creation is not usage-record
        # ingestion — the only applicable guard here is window integrity.
        validate_success(
            api.create_tag_policy(
                account["id"],
                {"required_tag_key": "team", "allowed_values": ["a"], "enforcement": "BLOCK"},
                BA,
            ),
            expected_status=201,
        )
        resp = api.create_retention_tier(
            account["id"],
            create_retention_tier_payload(
                account["version"] + 1,
                name="overlap",
                retention_days=15,
                effective_from_utc="2026-09-15T00:00:00Z",
                effective_to_utc="2026-11-01T00:00:00Z",
                index_rate_multiplier_bp=15000,
            ),
            BA,
        )
        validate_error(resp, ApiErrorId.ERR_TIER_WINDOW_OVERLAP.value)

    def test_stale_version_rejected_on_tier_create(self, api):
        """PRD §3.5: "Creation is OCC-protected exactly like commitment creation —
        the request carries `expected_billing_account_version`, stale values draw
        `ERR_STALE_VERSION`, and a successful create increments the account's
        `version`".

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_tier_create
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="Tier OCC")
        validate_success(
            api.create_retention_tier(
                account["id"],
                create_retention_tier_payload(account["version"], name="first"),
                BA,
            ),
            expected_status=201,
        )
        # The first create bumped the account version; the stale value is rejected
        # before the window check can even be considered.
        resp = api.create_retention_tier(
            account["id"],
            create_retention_tier_payload(
                account["version"],
                name="second",
                effective_from_utc="2026-10-01T00:00:00Z",
                effective_to_utc="2026-11-01T00:00:00Z",
            ),
            BA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


class TestVersionBookkeeping:
    def test_commitment_create_bumps_account_version(self, api):
        """PRD §2.8: "Both creations, on success, increment the parent
        `BillingAccount`'s `version` by 1."
        PRD §2.4: "`version` (integer): A system-managed integer starting at 1 that
        increments with every modification to the resource."

        Design: Corner/cross_cutting_layers/occ_version_increments_on_every_mutation
        """
        from test_helpers import create_commitment_payload

        set_clock()
        create_plan_tier_config()
        account = create_account(name="V")
        assert account["version"] == 1
        validate_success(
            api.create_commitment(
                account["id"],
                create_commitment_payload(account["version"], committed_quantity=5),
                BA,
            ),
            expected_status=201,
        )
        refreshed = validate_success(api.get_billing_account(account["id"], BA))
        assert refreshed["version"] == 2

    def test_retention_tier_create_bumps_account_version(self, api):
        """PRD §2.8: "Both creations, on success, increment the parent
        `BillingAccount`'s `version` by 1."
        PRD §3.5: "a successful create increments the account's `version`".

        Design: Corner/cross_cutting_layers/occ_version_increments_on_every_mutation
        """
        set_clock()
        create_plan_tier_config()
        account = create_account(name="V2")
        validate_success(
            api.create_retention_tier(
                account["id"],
                create_retention_tier_payload(account["version"], name="t"),
                BA,
            ),
            expected_status=201,
        )
        refreshed = validate_success(api.get_billing_account(account["id"], BA))
        assert refreshed["version"] == account["version"] + 1
