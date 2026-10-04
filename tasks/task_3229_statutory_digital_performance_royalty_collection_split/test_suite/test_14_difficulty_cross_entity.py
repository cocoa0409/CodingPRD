"""Difficulty queue A: cross_entity_state_dependency — one entity's valid
transitions gated by another entity's state."""
from test_helpers import (
    ApiErrorId,
    PAST_SCHEDULED_FOR,
    create_pool,
    make_admin_headers,
    make_matching_agent_headers,
    make_royalty_ops_headers,
    set_clock,
    setup_standard_paid_scenario,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()
MATCHER = make_matching_agent_headers()


class TestBatchExecutionGatedOnLiabilityPaid:
    def _setup_billed_pipeline(self, api, legal_name="GateCo"):
        """Report ACCEPTED + liability COMPUTED and BILLED (not yet PAID) +
        a 2026 pool + a PLANNED batch scheduled in the past."""
        scenario = setup_standard_paid_scenario(
            legal_name=legal_name,
            lines=[{"isrc": f"NM-{legal_name}", "track_title": "g",
                    "artist_name": "g", "performance_count": 10000}],
        )
        return scenario

    def test_execute_requires_liability_paid_then_succeeds_after_payment(self, api):
        """PRD §3.6: "Execution moves the batch `PLANNED` → `EXECUTED`. Three
        preconditions hold, and the OCC rule of §2.9 applies via
        `expected_distribution_batch_version`: the batch must be PLANNED; the
        liability for the same report must be in PAID status (otherwise
        `ERR_LIABILITY_NOT_PAID`, HTTP 409); and `scheduled_for` must be at or
        before the current logical clock time (otherwise `ERR_BATCH_NOT_DUE`,
        HTTP 409)."
        PRD §2.10: "Executing a distribution batch settles the liability,
        creates the split lines, and feeds the unmatched share into the
        unclaimed pool."

        Design: Difficulty/cross_entity_state_dependency/batch_execution_depends_on_liability_paid
        """
        # Build a pipeline whose liability is only BILLED (payment withheld):
        # replicate the paid scenario but skip record_payment until the trigger.
        from test_helpers import (
            create_active_licensee,
            create_effective_schedule,
            create_report_with_lines,
            submit_and_accept_report,
        )
        create_effective_schedule()
        lic = create_active_licensee(legal_name="GateCo")
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-G", "track_title": "g", "artist_name": "g",
              "performance_count": 10000}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        liability = validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        validate_success(api.bill_liability(liability["id"], OPS))
        create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due
        # once the liability reaches PAID.
        set_clock("2026-10-01T00:00:00Z")
        # Liability is BILLED, not PAID: the execute is gated.
        err = api.execute_distribution_batch(
            batch["id"],
            {"expected_distribution_batch_version": batch["version"]},
            OPS,
        )
        validate_error(err, ApiErrorId.ERR_LIABILITY_NOT_PAID.value)
        # Mutating the OTHER entity (recording payment) ungates the same call.
        validate_success(api.record_liability_payment(liability["id"], OPS))
        executed = validate_success(
            api.execute_distribution_batch(
                batch["id"],
                {"expected_distribution_batch_version": batch["version"]},
                OPS,
            )
        )
        assert executed["batch_status"] == "EXECUTED"
        liab_now = validate_success(
            api.get_royalty_liability(liability["id"], OPS)
        )
        assert liab_now["liability_status"] == "SETTLED"

    def test_execute_unpaid_then_pool_accrual_after_payment(self, api):
        """PRD §3.6: "the liability for the same report must be in PAID status
        (otherwise `ERR_LIABILITY_NOT_PAID`, HTTP 409)"
        PRD §3.9: "Accrual happens at batch execution: when a batch's report
        period lies inside a pool's window, the batch's unmatched share (§3.6)
        is added to that pool's `accrued_unmatched_cents`."

        Design: Difficulty/cross_entity_state_dependency/batch_execution_depends_on_liability_paid
        """
        from test_helpers import (
            create_active_licensee,
            create_effective_schedule,
            create_report_with_lines,
            submit_and_accept_report,
        )
        create_effective_schedule()
        lic = create_active_licensee(legal_name="GateCo2")
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-G2", "track_title": "g2", "artist_name": "g2",
              "performance_count": 10000}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        liability = validate_success(
            api.compute_liability(
                report["id"],
                {"expected_usage_report_version": accepted["version"]},
                OPS,
            ),
            expected_status=201,
        )
        validate_success(api.bill_liability(liability["id"], OPS))
        pool = create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due
        # once the liability reaches PAID.
        set_clock("2026-10-01T00:00:00Z")
        err = api.execute_distribution_batch(
            batch["id"],
            {"expected_distribution_batch_version": batch["version"]},
            OPS,
        )
        validate_error(err, ApiErrorId.ERR_LIABILITY_NOT_PAID.value)
        pool_before = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_before["accrued_unmatched_cents"] == 0
        validate_success(api.record_liability_payment(liability["id"], OPS))
        validate_success(
            api.execute_distribution_batch(
                batch["id"],
                {"expected_distribution_batch_version": batch["version"]},
                OPS,
            )
        )
        pool_after = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_after["accrued_unmatched_cents"] == 100000


class TestPoolCampaignGatedOnBatchAccrual:
    def test_start_campaign_blocked_until_batch_execution_accrues(self, api):
        """PRD §3.9: "A `MatchingAgent` runs re-identification campaigns against
        an accruing pool. Starting a campaign moves the pool `ACCRUING` →
        `MATCHING_CAMPAIGN`, and requires the accrued balance to be greater than
        zero."
        PRD §3.9: "Accrual happens at batch execution: when a batch's report
        period lies inside a pool's window, the batch's unmatched share (§3.6)
        is added to that pool's `accrued_unmatched_cents`."
        PRD §2.8: "sixth, state-machine legality of the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/pool_start_campaign_depends_on_batch_execution_accrual
        """
        scenario = setup_standard_paid_scenario(
            legal_name="DepCo",
            lines=[{"isrc": "NM-DEP", "track_title": "d", "artist_name": "d",
                    "performance_count": 5000}],
        )
        report = scenario["report"]
        pool = create_pool()
        # Accrual is zero: the ACCRUING -> MATCHING_CAMPAIGN transition's
        # precondition fails.
        err = api.start_pool_campaign(pool["id"], MATCHER)
        validate_error_is_one_of(
            err,
            [ApiErrorId.ERR_INVALID_STATE.value,
             ApiErrorId.ERR_POOL_NOT_DISTRIBUTABLE.value],
        )
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due
        # once the liability reaches PAID.
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
        # The identical retry now succeeds — the other entity's transition
        # changed this pool's valid transition set.
        started = validate_success(api.start_pool_campaign(pool["id"], MATCHER))
        assert started["pool_status"] == "MATCHING_CAMPAIGN"

    def test_start_campaign_succeeds_only_after_accrual_nonzero(self, api):
        """PRD §3.9: "Starting a campaign moves the pool `ACCRUING` →
        `MATCHING_CAMPAIGN`, and requires the accrued balance to be greater than
        zero."
        PRD §3.9: "Accrual happens at batch execution: when a batch's report
        period lies inside a pool's window, the batch's unmatched share (§3.6)
        is added to that pool's `accrued_unmatched_cents`."

        Design: Difficulty/cross_entity_state_dependency/pool_start_campaign_depends_on_batch_execution_accrual
        """
        scenario = setup_standard_paid_scenario(
            legal_name="DepCo2",
            lines=[{"isrc": "NM-DEP2", "track_title": "d2", "artist_name": "d2",
                    "performance_count": 5000}],
        )
        report = scenario["report"]
        pool = create_pool()
        pool_now = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_now["accrued_unmatched_cents"] == 0
        err = api.start_pool_campaign(pool["id"], MATCHER)
        validate_error_is_one_of(
            err,
            [ApiErrorId.ERR_INVALID_STATE.value,
             ApiErrorId.ERR_POOL_NOT_DISTRIBUTABLE.value],
        )
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due
        # once the liability reaches PAID.
        set_clock("2026-10-01T00:00:00Z")
        validate_success(
            api.execute_distribution_batch(
                batch["id"],
                {"expected_distribution_batch_version": batch["version"]},
                OPS,
            )
        )
        pool_after = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_after["accrued_unmatched_cents"] > 0
        started = validate_success(api.start_pool_campaign(pool["id"], MATCHER))
        assert started["pool_status"] == "MATCHING_CAMPAIGN"
