"""Difficulty tests: temporal-overlap semantics — closed intervals for service
periods, half-open windows for deployment exceptions."""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    create_deployment_exception_payload,
    create_service_period_payload,
    create_veteran_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestServicePeriodOverlap:
    def test_service_period_closed_interval_touching_collides(self, api):
        """PRD §3.1: "Periods of the same veteran may not overlap. Because
        intervals are closed, a new period is rejected with
        `ERR_SERVICE_PERIOD_OVERLAP` (HTTP 409) whenever it fails to end strictly
        before an existing period's start or begin strictly after that period's
        end — which means a new period whose `start_date` equals an existing
        period's `end_date` collides, because both intervals claim that day."

        Design: Difficulty/resource_temporal_overlap/service_period_closed_interval_touching_collides
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Ovl")),
            expected_status=201,
        )
        validate_success(
            api.create_service_period(
                veteran["id"],
                create_service_period_payload(
                    start_date="2020-01-10", end_date="2021-01-09"),
            ),
            expected_status=201,
        )
        # Touching endpoint: new start == existing end -> collides (closed).
        validate_error(
            api.create_service_period(
                veteran["id"],
                create_service_period_payload(
                    branch="NAVY",
                    start_date="2021-01-09", end_date="2022-01-08"),
            ),
            ApiErrorId.ERR_SERVICE_PERIOD_OVERLAP, expected_status=409,
        )
        # Next day is strictly after the existing end -> accepted.
        ok = validate_success(
            api.create_service_period(
                veteran["id"],
                create_service_period_payload(
                    branch="NAVY",
                    start_date="2021-01-10", end_date="2022-01-08"),
            ),
            expected_status=201,
        )
        # 2021-01-10 through 2022-01-08 inclusive = 364 days (closed interval).
        assert ok["qualifying_days"] == 364

    def test_service_period_touching_rejection_leaves_total_unchanged(self, api):
        """PRD §3.1: "a new period whose `start_date` equals an existing period's
        `end_date` collides, because both intervals claim that day."
        PRD §3.1: "The veteran's `total_qualifying_service_days` is the sum of
        `qualifying_days` across all of the veteran's service periods, recomputed
        whenever a period is added."

        Design: Difficulty/resource_temporal_overlap/service_period_closed_interval_touching_collides
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Ovl2")),
            expected_status=201,
        )
        first = validate_success(
            api.create_service_period(
                veteran["id"],
                create_service_period_payload(
                    start_date="2020-01-10", end_date="2021-01-09"),
            ),
            expected_status=201,
        )
        # 2020 is a leap year: 2020-01-10..2021-01-09 inclusive = 366 days.
        assert first["qualifying_days"] == 366
        validate_error(
            api.create_service_period(
                veteran["id"],
                create_service_period_payload(
                    branch="NAVY",
                    start_date="2021-01-09", end_date="2022-01-08"),
            ),
            ApiErrorId.ERR_SERVICE_PERIOD_OVERLAP, expected_status=409,
        )
        ok = validate_success(
            api.create_service_period(
                veteran["id"],
                create_service_period_payload(
                    branch="NAVY",
                    start_date="2021-01-10", end_date="2022-01-08"),
            ),
            expected_status=201,
        )
        # 2021-01-10..2022-01-08 inclusive = 364 days.
        assert ok["qualifying_days"] == 364
        readback = validate_success(api.get_veteran(veteran["id"]))
        assert readback["total_qualifying_service_days"] == 366 + 364


class TestDeploymentWindowOverlap:
    def test_deployment_window_half_open_adjacency_allowed(self, api):
        """PRD §3.6: "Windows are half-open, so two windows of the same veteran
        overlap only when one starts strictly before the other ends; a window
        whose `deployment_end` equals another window's `deployment_start` does
        not overlap, and anything tighter is rejected with
        `ERR_DEPLOYMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/deployment_window_half_open_adjacency_allowed
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Dep")),
            expected_status=201,
        )
        validate_success(
            api.create_deployment_exception(
                veteran["id"],
                create_deployment_exception_payload(
                    deployment_start="2026-03-01", deployment_end="2026-06-01",
                    orders_reference="ORD-1"),
            ),
            expected_status=201,
        )
        # Adjacent: new start == existing end -> allowed under half-open rules.
        adjacent = validate_success(
            api.create_deployment_exception(
                veteran["id"],
                create_deployment_exception_payload(
                    deployment_start="2026-06-01", deployment_end="2026-09-01",
                    orders_reference="ORD-2"),
            ),
            expected_status=201,
        )
        assert adjacent["id"]
        # Overlapping: starts one day before the first window's end -> rejected.
        validate_error(
            api.create_deployment_exception(
                veteran["id"],
                create_deployment_exception_payload(
                    deployment_start="2026-05-31", deployment_end="2026-08-01",
                    orders_reference="ORD-3"),
            ),
            ApiErrorId.ERR_DEPLOYMENT_WINDOW_OVERLAP, expected_status=409,
        )
        windows, meta = validate_paginated(
            api.list_deployment_exceptions(veteran["id"]))
        assert len(windows) == 2
        assert meta["total_count"] == 2

    def test_deployment_window_overlap_rejected_when_tighter(self, api):
        """PRD §3.6: "Windows are half-open, so two windows of the same veteran
        overlap only when one starts strictly before the other ends; a window
        whose `deployment_end` equals another window's `deployment_start` does
        not overlap, and anything tighter is rejected with
        `ERR_DEPLOYMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/deployment_window_half_open_adjacency_allowed
        """
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Dep2")),
            expected_status=201,
        )
        validate_success(
            api.create_deployment_exception(
                veteran["id"],
                create_deployment_exception_payload(
                    deployment_start="2026-03-01", deployment_end="2026-06-01",
                    orders_reference="ORD-1"),
            ),
            expected_status=201,
        )
        # Fully contained window: strictly tighter than adjacency -> rejected.
        validate_error(
            api.create_deployment_exception(
                veteran["id"],
                create_deployment_exception_payload(
                    deployment_start="2026-04-01", deployment_end="2026-05-01",
                    orders_reference="ORD-2"),
            ),
            ApiErrorId.ERR_DEPLOYMENT_WINDOW_OVERLAP, expected_status=409,
        )
        windows, _meta = validate_paginated(
            api.list_deployment_exceptions(veteran["id"]))
        assert len(windows) == 1
