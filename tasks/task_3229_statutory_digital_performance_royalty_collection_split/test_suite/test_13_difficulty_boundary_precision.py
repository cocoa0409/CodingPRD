"""Difficulty queue A: boundary_precision_check — equality boundaries on
scheduled_for and the exact campaign-count gate for pool release."""
from test_helpers import (
    ApiErrorId,
    create_pool,
    make_admin_headers,
    make_matching_agent_headers,
    make_royalty_ops_headers,
    set_clock,
    setup_standard_paid_scenario,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
MATCHER = make_matching_agent_headers()


def _setup_paid_report_with_batch(api, legal_name, scheduled_for):
    """Paid 10000-perf January report + one PLANNED batch at `scheduled_for`.

    Returns (report, liability, batch). Clock must be compatible.
    """
    scenario = setup_standard_paid_scenario(
        legal_name=legal_name,
        lines=[{"isrc": f"NM-{legal_name}", "track_title": "x",
                "artist_name": "x", "performance_count": 10000}],
    )
    report = scenario["report"]
    batch = validate_success(
        api.create_distribution_batch(
            report["id"], {"scheduled_for": scheduled_for}, OPS,
        ),
        expected_status=201,
    )
    return scenario, batch


class TestScheduledForEqualityGate:
    def test_execute_one_second_before_scheduled_for_rejected(self, api):
        """PRD §3.6: "Execution moves the batch `PLANNED` → `EXECUTED`. Three
        preconditions hold, and the OCC rule of §2.9 applies via
        `expected_distribution_batch_version`: the batch must be PLANNED; the
        liability for the same report must be in PAID status (otherwise
        `ERR_LIABILITY_NOT_PAID`, HTTP 409); and `scheduled_for` must be at or
        before the current logical clock time (otherwise `ERR_BATCH_NOT_DUE`,
        HTTP 409)."
        PRD §2.5: "The clock's startup default, before any explicit set, is
        exactly 2026-09-01T00:00:00Z."

        Design: Difficulty/boundary_precision_check/scheduled_for_equality_gates_execution
        """
        # Clock is at the startup default 2026-09-01T00:00:00Z; the batch is
        # scheduled one second AFTER the clock.
        create_pool()
        _, batch = _setup_paid_report_with_batch(
            api, "BoundEarly", "2026-09-01T00:00:01Z",
        )
        err = api.execute_distribution_batch(
            batch["id"],
            {"expected_distribution_batch_version": batch["version"]},
            OPS,
        )
        validate_error(err, ApiErrorId.ERR_BATCH_NOT_DUE.value)
        got = validate_success(api.get_distribution_batch(batch["id"], OPS))
        assert got["batch_status"] == "PLANNED"

    def test_execute_at_exact_scheduled_for_succeeds(self, api):
        """PRD §3.6: "Execution moves the batch `PLANNED` → `EXECUTED`. Three
        preconditions hold, and the OCC rule of §2.9 applies via
        `expected_distribution_batch_version`: the batch must be PLANNED; the
        liability for the same report must be in PAID status (otherwise
        `ERR_LIABILITY_NOT_PAID`, HTTP 409); and `scheduled_for` must be at or
        before the current logical clock time (otherwise `ERR_BATCH_NOT_DUE`,
        HTTP 409)."
        PRD §2.5: "The clock's startup default, before any explicit set, is
        exactly 2026-09-01T00:00:00Z."

        Design: Difficulty/boundary_precision_check/scheduled_for_equality_gates_execution
        """
        # Plan one second past the startup clock, then advance the logical
        # clock to exactly scheduled_for: equality gates execution (at-or-before).
        create_pool()
        _, batch = _setup_paid_report_with_batch(
            api, "BoundOnTime", "2026-09-01T00:00:01Z",
        )
        set_clock("2026-09-01T00:00:01Z")
        executed = validate_success(
            api.execute_distribution_batch(
                batch["id"],
                {"expected_distribution_batch_version": batch["version"]},
                OPS,
            )
        )
        assert executed["batch_status"] == "EXECUTED"


class TestPoolReleaseCampaignCountGate:
    def _setup_pool_with_accrual(self, api, legal_name="PoolCo"):
        """Executed batch whose single unmatched 5000-perf line accrues the full
        100000-cent distributable pool into a 2026 unclaimed pool."""
        scenario = setup_standard_paid_scenario(
            legal_name=legal_name,
            lines=[{"isrc": f"NM-{legal_name}-P", "track_title": "u",
                    "artist_name": "u", "performance_count": 5000}],
        )
        report = scenario["report"]
        pool = create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due.
        set_clock("2026-10-01T00:00:00Z")
        validate_success(
            api.execute_distribution_batch(
                batch["id"],
                {"expected_distribution_batch_version": batch["version"]},
                OPS,
            )
        )
        pool_now = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_now["accrued_unmatched_cents"] == 100000
        return pool_now

    def test_release_with_two_campaigns_rejected(self, api):
        """PRD §3.9: "If a completion brings `campaign_count` to 3 and
        `accrued_unmatched_cents` is still greater than zero, the pool
        auto-transitions from `ACCRUING` to `DISTRIBUTION_ELIGIBLE`."
        PRD §3.9: "Release moves a DISTRIBUTION_ELIGIBLE pool to `DISTRIBUTED` —
        attempting a release against a pool in any other status is rejected with
        `ERR_POOL_NOT_DISTRIBUTABLE` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/pool_release_requires_exactly_three_campaigns
        """
        pool = self._setup_pool_with_accrual(api)
        for _ in range(2):
            validate_success(api.start_pool_campaign(pool["id"], MATCHER))
            validate_success(api.complete_pool_campaign(pool["id"], MATCHER))
        pool_now = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_now["campaign_count"] == 2
        assert pool_now["pool_status"] == "ACCRUING"
        err = api.release_pool(pool["id"], OPS)
        validate_error(err, ApiErrorId.ERR_POOL_NOT_DISTRIBUTABLE.value)

    def test_third_campaign_makes_pool_releasable(self, api):
        """PRD §3.9: "If a completion brings `campaign_count` to 3 and
        `accrued_unmatched_cents` is still greater than zero, the pool
        auto-transitions from `ACCRUING` to `DISTRIBUTION_ELIGIBLE`."
        PRD §3.9: "Release moves a DISTRIBUTION_ELIGIBLE pool to `DISTRIBUTED`"
        PRD §3.9: "At release, `distributed_cents` is set equal to
        `accrued_unmatched_cents` at release time."

        Design: Difficulty/boundary_precision_check/pool_release_requires_exactly_three_campaigns
        """
        pool = self._setup_pool_with_accrual(api)
        for _ in range(3):
            validate_success(api.start_pool_campaign(pool["id"], MATCHER))
            validate_success(api.complete_pool_campaign(pool["id"], MATCHER))
        pool_now = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_now["campaign_count"] == 3
        assert pool_now["pool_status"] == "DISTRIBUTION_ELIGIBLE"
        released = validate_success(api.release_pool(pool["id"], OPS))
        assert released["pool_status"] == "DISTRIBUTED"
        assert released["distributed_cents"] == released["accrued_unmatched_cents"]
