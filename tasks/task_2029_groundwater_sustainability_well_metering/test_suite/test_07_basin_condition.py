"""Basin condition evaluation: dual variants, breach boundaries, supersede, publish
gates, and reading freshness (PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_basin_condition_snapshot,
    create_account,
    create_active_monitoring_well,
    create_basin_snapshot,
    create_monitoring_reading_payload,
    publish_basin_snapshot,
    record_monitoring_reading,
    setup_basin_condition,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDualVariantEvaluation:
    def test_basin_condition_official_breach_differs_from_mean(self, api):
        """PRD §3.5: "The snapshot's `condition` is `CRITICAL` when `breach_pct` is at least 50, `WATCH` when it is at least 25 but below 50, and `NORMAL` otherwise — a value of exactly 50.00 lands on `CRITICAL`, and exactly 25.00 lands on `WATCH`."
        PRD §3.5: "`breached_well_count` is the number of eligible wells whose latest reading's `depth_to_water_ft` is strictly greater than their `minimum_threshold_ft`, and `breach_pct` is one hundred times `breached_well_count` divided by `eligible_well_count`, rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/basin_condition_official_breach_differs_from_mean
        """
        # Depths 130/125/60/55 against threshold 100: 2 of 4 breach -> 50.00% -> CRITICAL.
        basin = setup_basin_condition([130.0, 125.0, 60.0, 55.0])
        snapshot = basin["snapshot"]
        assert_basin_condition_snapshot(snapshot)
        assert snapshot["eligible_well_count"] == 4
        assert snapshot["breached_well_count"] == 2
        assert snapshot["breach_pct"] == pytest.approx(50.00, abs=1e-9), (
            f"2 of 4 wells breach -> breach_pct 50.00, got {snapshot['breach_pct']}"
        )
        assert snapshot["condition"] == "CRITICAL", (
            f"breach_pct exactly 50.00 lands on CRITICAL, got {snapshot['condition']}"
        )

    def test_basin_condition_mean_variant_diverges_on_same_readings(self, api):
        """PRD §3.5: "`rolling_mean_depth_ft` is the arithmetic mean of the latest eligible depths, rounded half-up to 2 decimal places, and `mean_condition` is `CRITICAL` when the mean is at least 120.00 feet, `WATCH` when it is at least 100.00 but below 120.00, and `NORMAL` otherwise."

        Design: Difficulty/dual_variant_calc/basin_condition_official_breach_differs_from_mean
        """
        # Identical input data as the sibling test: the mean of 130/125/60/55 is
        # 92.50 < 100.00, so the published variant reads NORMAL while the official
        # threshold-breach variant reads CRITICAL.
        basin = setup_basin_condition([130.0, 125.0, 60.0, 55.0])
        snapshot = basin["snapshot"]
        assert snapshot["rolling_mean_depth_ft"] == pytest.approx(92.50, abs=1e-9), (
            f"mean of 130/125/60/55 is 92.50, got {snapshot['rolling_mean_depth_ft']}"
        )
        assert snapshot["mean_condition"] == "NORMAL", (
            f"mean 92.50 < 100.00 -> NORMAL, got {snapshot['mean_condition']}"
        )
        assert snapshot["condition"] == "CRITICAL"
        assert snapshot["condition"] != snapshot["mean_condition"], (
            "the two variants must diverge on identical input data"
        )


class TestBreachBoundary:
    def test_breach_pct_exactly_25_yields_watch(self, api):
        """PRD §3.5: "The snapshot's `condition` is `CRITICAL` when `breach_pct` is at least 50, `WATCH` when it is at least 25 but below 50, and `NORMAL` otherwise — a value of exactly 50.00 lands on `CRITICAL`, and exactly 25.00 lands on `WATCH`."

        Design: Difficulty/boundary_precision_check/breach_pct_exactly_25_yields_watch
        """
        # Exactly 1 of 4 wells over threshold -> breach_pct 25.00 -> WATCH.
        basin = setup_basin_condition([130.0, 50.0, 55.0, 60.0])
        snapshot = basin["snapshot"]
        assert snapshot["breach_pct"] == pytest.approx(25.00, abs=1e-9), (
            f"1 of 4 wells breach -> breach_pct 25.00, got {snapshot['breach_pct']}"
        )
        assert snapshot["condition"] == "WATCH", (
            f"exactly 25.00 lands on WATCH (>= 25 inclusive), got {snapshot['condition']}"
        )

    def test_breach_pct_zero_yields_normal(self, api):
        """PRD §3.5: "The snapshot's `condition` is `CRITICAL` when `breach_pct` is at least 50, `WATCH` when it is at least 25 but below 50, and `NORMAL` otherwise — a value of exactly 50.00 lands on `CRITICAL`, and exactly 25.00 lands on `WATCH`."

        Design: Difficulty/boundary_precision_check/breach_pct_exactly_25_yields_watch
        """
        # No well over threshold -> breach_pct 0.00 -> NORMAL (the "one fewer" leg).
        basin = setup_basin_condition([50.0, 55.0, 60.0, 70.0])
        snapshot = basin["snapshot"]
        assert snapshot["breached_well_count"] == 0
        assert snapshot["breach_pct"] == pytest.approx(0.00, abs=1e-9)
        assert snapshot["condition"] == "NORMAL", (
            f"0.00 is below the 25 threshold -> NORMAL, got {snapshot['condition']}"
        )


class TestSnapshotLifecycle:
    def test_snapshot_creation_supersedes_existing_draft(self, api, water_master_headers):
        """PRD §3.5: "When a `WaterMaster` requests a new snapshot, the system first discards any existing `DRAFT` snapshot (the prior draft transitions to `DISCARDED` and its `version` increments), then computes a fresh `DRAFT` snapshot from current monitoring data."
        PRD §3.5: "When no wells are eligible, `condition` is `NORMAL` while `breach_pct`, `rolling_mean_depth_ft`, and `mean_condition` are all null."
        PRD §2.3: "Every list response sorts by `created_at` ascending; ties are broken by request-arrival order — that is, the order in which the server accepted the create calls."

        Design: Corner/state_machines/snapshot_creation_supersedes_existing_draft
        """
        first = create_basin_snapshot()
        second = create_basin_snapshot()

        data, meta = validate_paginated(api.list_basin_snapshots(water_master_headers))
        assert meta["total_count"] == 2
        assert data[0]["id"] == first["id"], "created_at ASC with arrival tie-break"
        assert data[0]["status"] == "DISCARDED", (
            f"the prior DRAFT must be superseded, got {data[0]['status']}"
        )
        assert data[1]["id"] == second["id"] and data[1]["status"] == "DRAFT"

        for snap in data:
            assert snap["condition"] == "NORMAL"
            assert snap["breach_pct"] is None, (
                "the empty input set leaves breach_pct null"
            )

    def test_publish_already_published_snapshot_rejected(self, api, water_master_headers):
        """PRD §3.5: "Publishing is a separate `WaterMaster` step that requires the snapshot to be in `DRAFT` (anything else yields `ERR_INVALID_SNAPSHOT_STATE`)."

        Design: Corner/state_machines/publish_already_published_snapshot_rejected
        """
        snapshot = create_basin_snapshot()
        publish_basin_snapshot(snapshot["id"])

        resp = api.publish_basin_snapshot(snapshot["id"], water_master_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_SNAPSHOT_STATE)


class TestReadingFreshness:
    def test_reading_future_measured_at_returns_invalid_request(self, api, water_master_headers):
        """PRD §3.5: "A `WaterMaster` records depth readings against `ACTIVE` `MONITORING` wells by supplying `well_id`, `measured_at` (an ISO 8601 UTC instant that must not be after the logical clock, or the request fails with `ERR_INVALID_REQUEST`), `depth_to_water_ft` (strictly positive, 2-decimal precision; larger values indicate a worse condition), and `collector_name`."

        Design: Corner/validations/reading_future_measured_at_returns_invalid_request
        """
        account = create_account(holder_name="Agency Monitor", account_type="MUNICIPAL",
                                 base_allocation_af=1000.000)
        well = create_active_monitoring_well(account["id"], 100.0, "MW-1")

        resp = api.create_monitoring_reading(
            create_monitoring_reading_payload(
                well["id"], measured_at="2026-09-01T08:00:00Z", depth_to_water_ft=90.0
            ),
            water_master_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
