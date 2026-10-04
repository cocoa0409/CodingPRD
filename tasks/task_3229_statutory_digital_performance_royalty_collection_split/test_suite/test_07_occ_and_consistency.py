"""Optimistic-concurrency and immediate-consistency claims (queue B)."""
from test_helpers import (
    ApiErrorId,
    PAST_SCHEDULED_FOR,
    create_active_licensee,
    create_effective_schedule,
    create_pool,
    create_report_with_lines,
    make_admin_headers,
    make_licensee_headers,
    make_royalty_ops_headers,
    set_clock,
    setup_standard_paid_scenario,
    submit_and_accept_report,
    validate_error,
    validate_success,
)

ADMIN = make_admin_headers()
OPS = make_royalty_ops_headers()


class TestComputeLiabilityOcc:
    def test_occ_stale_version_on_compute_liability(self, api):
        """PRD §2.9: "Computing (or recomputing) a liability against a usage
        report requires the request to carry `expected_usage_report_version`,
        equal to the report's current `version` as last observed by the caller.
        If the report's version has advanced since — because an intervening
        amendment or resubmission legitimately changed the report's play lines —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A
        successful compute itself increments the report's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_compute_liability
        """
        create_effective_schedule()
        lic = create_active_licensee(legal_name="OCCo")
        lh = make_licensee_headers(lic["id"])
        report, _ = create_report_with_lines(
            lic["id"],
            [{"isrc": "NM-OC", "track_title": "oc", "artist_name": "oc",
              "performance_count": 1000}],
            "2026-01-01T00:00:00Z",
            "2026-01-31T00:00:00Z",
        )
        accepted = submit_and_accept_report(report["id"], lic["id"])
        rep_v = accepted["version"]
        validate_success(
            api.compute_liability(
                report["id"], {"expected_usage_report_version": rep_v}, OPS,
            ),
            expected_status=201,
        )
        # Amend cycle advances the report version several times.
        validate_success(api.amend_usage_report(report["id"], lh))
        validate_success(api.submit_usage_report(report["id"], lh))
        accepted2 = validate_success(api.accept_usage_report(report["id"], OPS))
        assert accepted2["version"] > rep_v
        err = api.compute_liability(
            report["id"], {"expected_usage_report_version": rep_v}, OPS,
        )
        validate_error(err, ApiErrorId.ERR_STALE_VERSION.value)


class TestBatchExecuteOcc:
    def test_occ_stale_version_on_batch_execute(self, api):
        """PRD §2.9: "Executing a distribution batch requires the request to
        carry `expected_distribution_batch_version`, equal to the batch's
        current `version` as last observed by the caller. If the batch's version
        has advanced — because an intervening cancel-and-rebatch or an
        amendment-driven reversal legitimately superseded the batch — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_batch_execute
        """
        scenario = setup_standard_paid_scenario(
            legal_name="OCB",
            lines=[{"isrc": "NM-OCB", "track_title": "ocb", "artist_name": "ocb",
                    "performance_count": 10}],
        )
        report = scenario["report"]
        create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        err = api.execute_distribution_batch(
            batch["id"],
            {"expected_distribution_batch_version": batch["version"] - 1},
            OPS,
        )
        validate_error(err, ApiErrorId.ERR_STALE_VERSION.value)
        got = validate_success(api.get_distribution_batch(batch["id"], OPS))
        assert got["batch_status"] == "PLANNED"


class TestExecuteCascadeConsistency:
    def test_execute_cascade_visible_in_same_response_chain(self, api):
        """PRD §2.10: "Executing a distribution batch settles the liability,
        creates the split lines, and feeds the unmatched share into the
        unclaimed pool."
        PRD §2.10: "Consistency is immediate: there is no eventual-consistency
        window anywhere in this system."
        PRD §3.6: "As cascade link 2 of the distribution cascade, execution
        flips the liability from `PAID` to `SETTLED`."

        Design: Corner/consistency_model/execute_cascade_visible_in_same_response_chain
        """
        scenario = setup_standard_paid_scenario(
            legal_name="ImmCo",
            lines=[{"isrc": "NM-IM", "track_title": "im", "artist_name": "im",
                    "performance_count": 10000}],
        )
        report = scenario["report"]
        liability = scenario["liability"]
        pool = create_pool()
        batch = validate_success(
            api.create_distribution_batch(
                report["id"], {"scheduled_for": "2026-10-01T00:00:00Z"}, OPS,
            ),
            expected_status=201,
        )
        # Advance the logical clock to exactly scheduled_for so the batch is due.
        set_clock("2026-10-01T00:00:00Z")
        executed = validate_success(
            api.execute_distribution_batch(
                batch["id"],
                {"expected_distribution_batch_version": batch["version"]},
                OPS,
            )
        )
        assert executed["batch_status"] == "EXECUTED"
        liab = validate_success(api.get_royalty_liability(liability["id"], OPS))
        assert liab["liability_status"] == "SETTLED"
        pool_now = validate_success(api.get_unclaimed_pool(pool["id"], OPS))
        assert pool_now["accrued_unmatched_cents"] == 100000
