"""Corner-queue tests: calculations — departure variance, dwell aggregation
input filtering, and the HOS constant boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_crew_pool,
    create_locomotive,
    create_yard,
    create_active_plan,
    get_pool,
    get_success_data,
    record_car_event,
    set_clock,
    setup_two_shipments_dwelling,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

TS_HEADERS = TEST_USERS["terminal_superintendent_headers"]


class TestDepartureVariance:
    def test_departure_variance_zero_when_on_time(self, api, np_headers, cd_headers, pp_headers, any_headers):
        """PRD §3.5: "A successful finalize stamps `actual_departure_utc` from
        the logical clock, computes `departure_variance_minutes` as actual
        minus scheduled in whole minutes (positive values mean late)".
        PRD §2.8: "A departure more than 30 minutes behind schedule raises
        delay exceptions (see §3.5)."

        Design: Corner/calculations/departure_variance_zero_when_on_time
        """
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code="CA1-A")
        yB = create_yard(yard_code="CA1-B")
        plan = create_active_plan(
            yA["id"], yB["id"], train_symbol="CA1-P",
            scheduled_departure_utc="2026-09-01T08:00:00Z",
        )
        pool = create_crew_pool(yA["id"], crews_available=1)
        loco = create_locomotive(yA["id"], unit_number="CA1-UP1")
        dep = get_success_data(
            api.create_train_departure(
                {
                    "train_plan_id": plan["id"],
                    "service_date": "2026-09-01",
                    "crew_pool_id": pool["id"],
                    "locomotive_id": loco["id"],
                    "car_count_planned": 1,
                    "crew_hours_estimated": 6,
                },
                TS_HEADERS,
            )
        )
        set_clock("2026-09-01T08:00:00Z")
        finalized = validate_success(
            api.finalize_train_departure(dep["id"], TS_HEADERS)
        )
        assert finalized["actual_departure_utc"].startswith("2026-09-01T08:00:00")
        assert finalized["departure_variance_minutes"] == 0
        _data, meta = validate_paginated(
            api.list_service_exceptions(
                any_headers, params={"exception_type": "DEPARTURE_DELAY"}
            )
        )
        assert meta["total_count"] == 0, "on-time finalize raises no delay exception"


class TestDwellAggregation:
    def test_dwell_excludes_closed_sessions_and_under_benchmark(self, api):
        """PRD §3.6: "For each open session, the session's overage is the
        elapsed hours from its arrival to the current logical-clock instant
        minus the yard's `dwell_benchmark_hours`, floored at zero so a session
        inside its benchmark contributes nothing."
        PRD §3.2: "overage equal to the benchmark exactly stays `OPEN`".

        Design: Corner/calculations/dwell_excludes_closed_sessions_and_under_benchmark
        """
        fx = setup_two_shipments_dwelling(
            "CA2",
            arrival_a_utc="2026-09-01T20:00:00Z",
            arrival_b_utc="2026-09-02T03:00:00Z",
        )
        # Close SA's session at 2026-09-02T01:00:00Z (dwell 5h, now closed).
        set_clock("2026-09-02T01:00:00Z")
        record_car_event(
            fx["sA"]["id"], fx["yC"]["id"], "CLASSIFICATION_COMPLETE",
            "2026-09-02T01:00:00Z", fx["sA"]["car_count"],
        )
        # At 2026-09-02T08:00:00Z SB's session is 5h old (under benchmark 10).
        set_clock("2026-09-02T08:00:00Z")
        yard = get_success_data(api.get_yard(fx["yC"]["id"], TEST_USERS["any_headers"]))
        assert yard["current_dwell_overage_hours"] == 0
        assert yard["posture"] == "OPEN"


class TestHosBoundary:
    def test_hos_boundary_twelve_exactly_allowed(self, api, np_headers, cd_headers, pp_headers, any_headers):
        """PRD §3.5: "`crew_hours_estimated` must not exceed the 12.0-hour
        hours-of-service maximum, with a strictly-greater comparison: an
        estimate of exactly 12.0 hours is allowed, anything above it is
        rejected with `ERR_HOS_EXCEEDED` (HTTP 422)."

        Design: Corner/calculations/hos_boundary_twelve_exactly_allowed
        """
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code="CA3-A")
        yB = create_yard(yard_code="CA3-B")
        plan = create_active_plan(
            yA["id"], yB["id"], train_symbol="CA3-P",
            scheduled_departure_utc="2026-09-01T08:00:00Z",
        )
        pool = create_crew_pool(yA["id"], crews_available=2)
        l1 = create_locomotive(yA["id"], unit_number="CA3-L1")
        l2 = create_locomotive(yA["id"], unit_number="CA3-L2")
        d1 = get_success_data(
            api.create_train_departure(
                {
                    "train_plan_id": plan["id"], "service_date": "2026-09-01",
                    "crew_pool_id": pool["id"], "locomotive_id": l1["id"],
                    "car_count_planned": 5, "crew_hours_estimated": 12.0,
                },
                TS_HEADERS,
            )
        )
        d2 = get_success_data(
            api.create_train_departure(
                {
                    "train_plan_id": plan["id"], "service_date": "2026-09-01",
                    "crew_pool_id": pool["id"], "locomotive_id": l2["id"],
                    "car_count_planned": 5, "crew_hours_estimated": 12.0001,
                },
                TS_HEADERS,
            )
        )
        set_clock("2026-09-01T08:00:00Z")
        ok = validate_success(api.finalize_train_departure(d1["id"], TS_HEADERS))
        assert ok["status"] == "DEPARTED", "12.0 exactly is allowed (> semantics)"
        resp = api.finalize_train_departure(d2["id"], TS_HEADERS)
        validate_error(resp, ApiErrorId.ERR_HOS_EXCEEDED.value)
        dep2 = get_success_data(api.get_train_departure(d2["id"], any_headers))
        assert dep2["status"] == "SCHEDULED"
        pool_now = get_pool(pool["id"])
        assert pool_now["crews_booked"] == 1, (
            "only the passing departure consumed a crew"
        )
