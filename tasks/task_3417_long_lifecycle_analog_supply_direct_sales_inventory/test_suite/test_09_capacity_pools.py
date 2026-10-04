"""Capacity pools: half-open overlap, clock-derived status, receipts, investment OCC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_capacity_pool,
    create_capacity_pool_payload,
    get_part,
    get_pool,
    make_capacity_pool,
    make_part,
    record_receipt,
    set_clock,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["supply_planner_headers"]


class TestCapacityPools:
    def test_capacity_pool_periods_half_open_adjacency(self, api):
        """PRD §3.5: "Two pools with the same `site_name` and `process_technology`
        may not have intersecting half-open windows: an attempt is
        `ERR_POOL_PERIOD_OVERLAP` (HTTP 409), though adjacency is explicitly allowed —
        an existing pool's `period_end` equal to the new pool's `period_start` is not
        a conflict."

        Design: Difficulty/resource_temporal_overlap/capacity_pool_periods_half_open_adjacency
        """
        pool_a = make_capacity_pool(
            site_name="RFAB", process_technology="CMOS_180NM",
            period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
            total_units=300,
        )
        res_b = api.create_capacity_pool(
            create_capacity_pool_payload(
                site_name="RFAB", process_technology="CMOS_180NM",
                period_start="2026-10-01T00:00:00Z", period_end="2026-11-01T00:00:00Z",
                total_units=300,
            ),
            PLANNER,
        )
        pool_b = validate_success(res_b, 201)
        assert_capacity_pool(pool_b)
        assert pool_b["site_name"] == pool_a["site_name"]

        overlap = api.create_capacity_pool(
            create_capacity_pool_payload(
                site_name="RFAB", process_technology="CMOS_180NM",
                period_start="2026-09-15T00:00:00Z", period_end="2026-10-15T00:00:00Z",
                total_units=100,
            ),
            PLANNER,
        )
        validate_error(overlap, ApiErrorId.ERR_POOL_PERIOD_OVERLAP)

    def test_pool_same_window_different_technology_allowed(self, api):
        """PRD §3.5: "Two pools with the same `site_name` and `process_technology`
        may not have intersecting half-open windows: an attempt is
        `ERR_POOL_PERIOD_OVERLAP` (HTTP 409), though adjacency is explicitly allowed —
        an existing pool's `period_end` equal to the new pool's `period_start` is not
        a conflict."

        Design: Difficulty/resource_temporal_overlap/capacity_pool_periods_half_open_adjacency
        """
        make_capacity_pool(
            site_name="RFAB", process_technology="CMOS_180NM",
            period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
            total_units=300,
        )
        res = api.create_capacity_pool(
            create_capacity_pool_payload(
                site_name="RFAB", process_technology="ANALOG_BIPOLAR",
                period_start="2026-09-01T00:00:00Z", period_end="2026-10-01T00:00:00Z",
                total_units=300,
            ),
            PLANNER,
        )
        pool = validate_success(res, 201)
        assert pool["process_technology"] == "ANALOG_BIPOLAR"

    def test_pool_clock_sweep_planned_open_closed_with_boundary(self, api):
        """PRD §2.5: "A capacity pool is `PLANNED` while the clock is before its
        `period_start`, `OPEN` while the clock is at or after `period_start` and
        before `period_end`, and `CLOSED` once the clock reaches `period_end`".
        PRD §3.5: "The pool's clock-derived `status` must be `OPEN` — a receipt
        against a `PLANNED` or `CLOSED` pool is `ERR_POOL_NOT_OPEN` (HTTP 422)."

        Design: Corner/state_machines/pool_clock_sweep_planned_open_closed_with_boundary
        """
        part = make_part(part_number="SN7400N", process_technology="CMOS_180NM")
        pool = make_capacity_pool(
            site_name="LFAB", process_technology="CMOS_180NM",
            period_start="2026-10-01T00:00:00Z", period_end="2026-11-01T00:00:00Z",
            total_units=500,
        )
        assert pool["status"] == "PLANNED"

        early = api.create_receipt(part["id"], {"capacity_pool_id": pool["id"], "units": 10}, PLANNER)
        validate_error(early, ApiErrorId.ERR_POOL_NOT_OPEN)

        set_clock("2026-10-01T00:00:00Z")
        assert get_pool(pool["id"])["status"] == "OPEN"
        updated = validate_success(
            api.create_receipt(part["id"], {"capacity_pool_id": pool["id"], "units": 50}, PLANNER),
            201,
        )
        assert updated["on_hand_units"] == 50

        set_clock("2026-11-01T00:00:00Z")
        assert get_pool(pool["id"])["status"] == "CLOSED"
        late = api.create_receipt(part["id"], {"capacity_pool_id": pool["id"], "units": 10}, PLANNER)
        validate_error(late, ApiErrorId.ERR_POOL_NOT_OPEN)
        final_pool = get_pool(pool["id"])
        assert final_pool["allocated_units"] == 50
        assert final_pool["status"] == "CLOSED"

    def test_receipt_exceeds_pool_capacity_rejected(self, api):
        """PRD §3.5: "The receipt's `units` must not exceed the pool's remaining
        capacity, `total_units` minus `allocated_units` — an overage is
        `ERR_POOL_CAPACITY_EXCEEDED` (HTTP 422)."
        PRD §3.1: "A successful receipt adds `units` to the part's `on_hand_units`
        and to the pool's `allocated_units`, recomputes the part's `posture`, and
        returns the part."

        Design: Corner/validations/receipt_exceeds_pool_capacity_rejected
        """
        part = make_part(part_number="LM2903DR", package_family="SOIC")
        pool = make_capacity_pool(
            site_name="DFAB", process_technology="ANALOG_BIPOLAR", total_units=500
        )
        record_receipt(part["id"], pool["id"], 300)

        res = api.create_receipt(part["id"], {"capacity_pool_id": pool["id"], "units": 250}, PLANNER)
        validate_error(res, ApiErrorId.ERR_POOL_CAPACITY_EXCEEDED)

        assert get_pool(pool["id"])["allocated_units"] == 300
        assert get_part(part["id"])["on_hand_units"] == 300

    def test_pool_invest_occ_and_capacity_floor(self, api):
        """PRD §3.5: "Investment can only raise installed capacity: `total_units`
        may never be set below the pool's `allocated_units`, and an attempt is
        `ERR_POOL_CAPACITY_EXCEEDED` (HTTP 422)."
        PRD §2.7: "If the pool's current `version` does not match — for example
        because another planner has just invested in the same pool — the investment
        is rejected with `ERR_STALE_VERSION` (HTTP 412) and the pool is unchanged."

        Design: Corner/cross_cutting_layers/pool_invest_occ_and_capacity_floor
        """
        part = make_part(part_number="LM317HV", package_family="TO3")
        pool = make_capacity_pool(
            site_name="DFAB", process_technology="ANALOG_BIPOLAR", total_units=500
        )
        record_receipt(part["id"], pool["id"], 300)
        current_version = get_pool(pool["id"])["version"]

        low = api.invest_capacity_pool(
            pool["id"],
            {"total_units": 200, "expected_capacity_pool_version": current_version},
            PLANNER,
        )
        validate_error(low, ApiErrorId.ERR_POOL_CAPACITY_EXCEEDED)

        raised = validate_success(
            api.invest_capacity_pool(
                pool["id"],
                {"total_units": 800, "expected_capacity_pool_version": current_version},
                PLANNER,
            ),
            200,
        )
        assert raised["total_units"] == 800
        assert raised["version"] == current_version + 1

        stale = api.invest_capacity_pool(
            pool["id"],
            {"total_units": 900, "expected_capacity_pool_version": current_version},
            PLANNER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        final_pool = get_pool(pool["id"])
        assert final_pool["total_units"] == 800
        assert final_pool["allocated_units"] == 300

    def test_default_clock_is_fixed_at_scaffold_epoch(self, api):
        """PRD §2.5: "Before any client call, the clock starts at exactly
        `2026-09-01T00:00:00Z`, and the server must never fall back to wall-clock
        time."
        PRD §2.5: "A capacity pool is `PLANNED` while the clock is before its
        `period_start`, `OPEN` while the clock is at or after `period_start` and
        before `period_end`, and `CLOSED` once the clock reaches `period_end`".

        Design: Corner/endpoints/default_clock_is_fixed_at_scaffold_epoch
        """
        planned = make_capacity_pool(
            site_name="MFAB", process_technology="CMOS_180NM",
            period_start="2026-09-01T00:00:01Z", period_end="2026-12-01T00:00:00Z",
            total_units=100,
        )
        assert planned["status"] == "PLANNED", (
            "window starting one second after the fixed default clock is PLANNED"
        )

        open_now = make_capacity_pool(
            site_name="NFAB", process_technology="CMOS_180NM",
            period_start="2026-09-01T00:00:00Z", period_end="2026-12-01T00:00:00Z",
            total_units=100,
        )
        assert open_now["status"] == "OPEN", (
            "window starting exactly at the default clock is OPEN (inclusive start)"
        )
