"""Resource temporal overlap tests: half-open window adjacency on performance
tests; status-filtered overlap on bid sessions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_bid_session,
    get_success_data,
    schedule_performance_test,
    setup_executed_project,
    validate_error,
    validate_paginated,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
PERF = TEST_USERS["performance_engineer_headers"]
MARKET = TEST_USERS["market_operator_headers"]


class TestPerformanceTestWindowAdjacency:
    def test_overlap_rejected_but_exact_adjacency_accepted(self, api):
        """PRD §3.4: "Windows are half-open, so two tests on the same project
        may touch but never overlap: any overlap among tests in `SCHEDULED`,
        `PASSED`, or `FAILED` status on the same project is rejected with
        `ERR_TEST_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/performance_test_windows_half_open_adjacency
        """
        project, _ = setup_executed_project(api=api)
        schedule_performance_test(
            project["id"], "CAPACITY_TEST",
            "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z", api=api,
        )
        # Overlapping [09-05, 09-12) -> rejected.
        resp = api.create_performance_test(
            {
                "project_id": project["id"],
                "test_type": "RTE_TEST",
                "window_start": "2026-09-05T00:00:00Z",
                "window_end": "2026-09-12T00:00:00Z",
            },
            PERF,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_WINDOW_OVERLAP)

        # Exactly adjacent [09-10, 09-20) -> accepted.
        data = validate_success(
            api.create_performance_test(
                {
                    "project_id": project["id"],
                    "test_type": "CAPACITY_TEST",
                    "window_start": "2026-09-10T00:00:00Z",
                    "window_end": "2026-09-20T00:00:00Z",
                },
                PERF,
            ),
            expected_status=201,
        )
        assert data["status"] == "SCHEDULED"
        tests, meta = validate_paginated(
            api.list_performance_tests(DEV, params={"project_id": project["id"]})
        )
        assert len(tests) == 2 and meta["total_count"] == 2

    def test_nested_window_rejected_and_containment_is_overlap(self, api):
        """PRD §3.4: "Windows are half-open, so two tests on the same project
        may touch but never overlap: any overlap among tests in `SCHEDULED`,
        `PASSED`, or `FAILED` status on the same project is rejected with
        `ERR_TEST_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/performance_test_windows_half_open_adjacency
        """
        project, _ = setup_executed_project(api=api)
        schedule_performance_test(
            project["id"], "CAPACITY_TEST",
            "2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z", api=api,
        )
        # Fully contained window [09-01, 09-02) is still an overlap.
        resp = api.create_performance_test(
            {
                "project_id": project["id"],
                "test_type": "CAPACITY_TEST",
                "window_start": "2026-09-01T00:00:00Z",
                "window_end": "2026-09-02T00:00:00Z",
            },
            PERF,
        )
        validate_error(resp, ApiErrorId.ERR_TEST_WINDOW_OVERLAP)

        # Adjacent on the other side [08-20, 09-01) touches at window_start.
        data = validate_success(
            api.create_performance_test(
                {
                    "project_id": project["id"],
                    "test_type": "CAPACITY_TEST",
                    "window_start": "2026-08-20T00:00:00Z",
                    "window_end": "2026-09-01T00:00:00Z",
                },
                PERF,
            ),
            expected_status=201,
        )
        assert data["status"] == "SCHEDULED"


class TestBidSessionOverlapStatusFiltering:
    def test_cancelled_session_frees_its_window(self, api):
        """PRD §3.8: "Sessions in `OPEN` or `CLEARED` status on the same
        project may not overlap — adjacency is fine under the half-open
        convention — and a conflict is rejected with
        `ERR_BID_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/bid_session_windows_survive_only_when_open_or_cleared
        """
        project, _ = setup_executed_project(api=api)
        bs1 = create_bid_session(
            project["id"], api=api,
            window_start="2026-09-02T00:00:00Z", window_end="2026-09-02T04:00:00Z",
            offer_mwh=20, offer_price_cents_per_mwh=9000,
        )
        # Overlap while OPEN -> rejected.
        resp = api.create_bid_session(
            {
                "project_id": project["id"],
                "market": "REAL_TIME",
                "window_start": "2026-09-02T02:00:00Z",
                "window_end": "2026-09-02T06:00:00Z",
                "offer_mwh": 10,
                "offer_price_cents_per_mwh": 9500,
            },
            MARKET,
        )
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_OVERLAP)

        cancelled = validate_success(api.cancel_bid_session(bs1["id"], MARKET))
        assert cancelled["status"] == "CANCELLED"

        # Same overlapping window now accepted.
        data = validate_success(
            api.create_bid_session(
                {
                    "project_id": project["id"],
                    "market": "REAL_TIME",
                    "window_start": "2026-09-02T02:00:00Z",
                    "window_end": "2026-09-02T06:00:00Z",
                    "offer_mwh": 10,
                    "offer_price_cents_per_mwh": 9500,
                },
                MARKET,
            ),
            expected_status=201,
        )
        assert data["status"] == "OPEN"

    def test_settled_session_no_longer_blocks_window(self, api):
        """PRD §3.8: "Sessions in `OPEN` or `CLEARED` status on the same
        project may not overlap — adjacency is fine under the half-open
        convention — and a conflict is rejected with
        `ERR_BID_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/bid_session_windows_survive_only_when_open_or_cleared
        """
        project, _ = setup_executed_project(api=api)
        bs1 = create_bid_session(
            project["id"], api=api,
            window_start="2026-09-03T00:00:00Z", window_end="2026-09-03T04:00:00Z",
        )
        validate_success(
            api.record_bid_clearing(
                bs1["id"],
                {"clearing_price_cents_per_mwh": 9000, "market_cleared_mwh": 20},
                MARKET,
            )
        )
        # CLEARED still blocks an overlap.
        resp = api.create_bid_session(
            {
                "project_id": project["id"],
                "market": "REAL_TIME",
                "window_start": "2026-09-03T02:00:00Z",
                "window_end": "2026-09-03T06:00:00Z",
                "offer_mwh": 10,
                "offer_price_cents_per_mwh": 9500,
            },
            MARKET,
        )
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_OVERLAP)

        # SETTLED is neither OPEN nor CLEARED -> window freed.
        settled = validate_success(api.settle_bid_session(bs1["id"], MARKET))
        assert settled["status"] == "SETTLED"
        data = validate_success(
            api.create_bid_session(
                {
                    "project_id": project["id"],
                    "market": "REAL_TIME",
                    "window_start": "2026-09-03T02:00:00Z",
                    "window_end": "2026-09-03T06:00:00Z",
                    "offer_mwh": 10,
                    "offer_price_cents_per_mwh": 9500,
                },
                MARKET,
            ),
            expected_status=201,
        )
        assert data["status"] == "OPEN"
