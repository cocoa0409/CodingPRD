"""Calculation corner tests: RTE energy-sum aggregation, invalid RTE
intervals, auto-augmentation sizing on capacity FAIL, and the dispatch price
floor / capacity cap ordering."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    commission_project,
    create_bid_session,
    create_milestone,
    get_success_data,
    schedule_performance_test,
    set_clock,
    setup_commissioned_project,
    setup_executed_project,
    validate_error,
    validate_paginated,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
PERF = TEST_USERS["performance_engineer_headers"]
MARKET = TEST_USERS["market_operator_headers"]


def test_rte_aggregates_energy_sums_not_interval_ratios(api):
    """PRD §3.4: "The measured efficiency `measured_rte_pct` is the total
    discharge energy summed over all intervals divided by the total charge
    energy summed over all intervals, rounded half up to 4 decimal places —
    intervals are aggregated as energy sums, never as an average of
    per-interval ratios. The test passes when `measured_rte_pct` is greater
    than or equal to the agreement's `guaranteed_rte_pct`, again with equality
    passing."
    PRD §3.4: "A failed `RTE_TEST` creates nothing."

    Design: Corner/calculations/rte_aggregates_energy_sums_not_interval_ratios
    """
    project, _ = setup_executed_project(
        api=api,
        project_overrides={
            "market_application": "FREQUENCY_REGULATION",
            "duty_cycle_profile": "CONTINUOUS",
        },
    )
    test = schedule_performance_test(
        project["id"], "RTE_TEST",
        "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z", api=api,
    )
    data = validate_success(
        api.record_test_results(
            test["id"],
            {
                "rte_intervals": [
                    {"charge_mwh": 10, "discharge_mwh": 9.2},
                    {"charge_mwh": 8, "discharge_mwh": 7.0},
                    {"charge_mwh": 12, "discharge_mwh": 10.9},
                ]
            },
            PERF,
        )
    )
    # 27.1 / 30 = 0.903333... -> 0.9033 at 4dp half-up (energy sums, NOT the
    # 0.8961 mean-of-ratios).
    assert data["measured_rte_pct"] == pytest.approx(0.9033, abs=0.00005), (
        f"27.1/30 -> 0.9033, got {data['measured_rte_pct']}"
    )
    assert data["result"] == "PASS" and data["status"] == "PASSED"

    augs, _ = validate_paginated(
        api.list_augmentations(DEV, params={"project_id": project["id"]})
    )
    assert len(augs) == 0, "an RTE test never auto-creates an augmentation"


def test_rte_invalid_intervals_and_capacity_fail_creates_auto_augmentation(api):
    """PRD §3.4: "For an `RTE_TEST`, the engineer instead supplies
    `rte_intervals`, a list of charge/discharge pairs — each element with
    `charge_mwh` greater than zero and `discharge_mwh` greater than or equal to
    zero, and the list must contain at least one element; a missing, empty, or
    non-positive-charge list is `ERR_INVALID_RTE_INTERVALS`."
    PRD §3.5: "The auto-created augmentation covers that shortfall with a
    gross-up: the shortfall is divided by one minus the 0.5 percent penalty —
    pre-compensating the penalty the new event itself will attract — then
    rounded up to the next 0.01 MWh to produce its `added_capacity_mwh`."
    PRD §3.4: "A failed `CAPACITY_TEST` has one further consequence: the system
    automatically creates an augmentation event with `origin` `AUTO` in
    `PLANNED` status, sized and scheduled per §3.5"

    Design: Corner/calculations/rte_invalid_intervals_and_capacity_fail_creates_auto_augmentation
    """
    project, esa = setup_executed_project(api=api)  # guarantee 38.00
    project, esa, _ = commission_project(
        project, esa, api=api,
        planned_date="2026-09-02T00:00:00Z", actual_date="2026-09-01T00:00:00Z",
    )
    validate_success(
        api.recompute_projection(project["id"], {"equivalent_cycles": 600}, PERF)
    )
    rte_test = schedule_performance_test(
        project["id"], "RTE_TEST",
        "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z", api=api,
    )
    cap_test = schedule_performance_test(
        project["id"], "CAPACITY_TEST",
        "2026-09-08T00:00:00Z", "2026-09-30T00:00:00Z", api=api,
    )

    resp = api.record_test_results(
        rte_test["id"],
        {"rte_intervals": [{"charge_mwh": 0, "discharge_mwh": 0}]},
        PERF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_RTE_INTERVALS)
    rte_after = get_success_data(api.get_performance_test(rte_test["id"], PERF))
    assert rte_after["status"] == "SCHEDULED"

    set_clock("2026-09-08T00:00:00Z", api=api)
    cap = validate_success(
        api.record_test_results(
            cap_test["id"],
            {"measured_capacity_mwh": 37.5, "aux_load_mwh": 0.5},
            PERF,
        )
    )
    # POI: 37.5 - 0.5 = 37.0 < 38.00 -> FAIL
    assert cap["evaluated_capacity_mwh"] == pytest.approx(37.0, abs=0.001)
    assert cap["status"] == "FAILED"

    project_after = get_success_data(api.get_project(project["id"], DEV))
    assert project_after["projected_capacity_mwh"] == pytest.approx(39.64, abs=0.001), (
        f"40 - 600*0.0006 == 39.64, got {project_after['projected_capacity_mwh']}"
    )

    augs, _ = validate_paginated(
        api.list_augmentations(DEV, params={"project_id": project["id"]})
    )
    auto = [a for a in augs if a["origin"] == "AUTO"]
    assert len(auto) == 1, f"exactly one AUTO augmentation, got {len(auto)}"
    event = auto[0]
    assert event["status"] == "PLANNED"
    # shortfall = 38.00 - min(39.64, 37.00) = 1.00; ceil(1.00/0.995 * 100)/100 = 1.01
    assert event["added_capacity_mwh"] == pytest.approx(1.01, abs=0.001), (
        f"ceil(1.00/0.995 * 100)/100 == 1.01, got {event['added_capacity_mwh']}"
    )
    assert event["planned_window_start"].startswith("2026-09-08")
    assert event["planned_window_end"].startswith("2026-10-08")


def test_dispatch_price_floor_evaluated_before_capacity_cap(api):
    """PRD §3.8: "The dispatch optimization then decides the cleared quantity
    in a pinned order, price floor before capacity cap: if the clearing price
    is below the offer floor, `cleared_mwh` is zero even when capacity would
    allow the full offer; otherwise `cleared_mwh` is the smaller of `offer_mwh`
    and a capacity cap that is itself the smaller of the project's current
    `projected_capacity_mwh` and `market_cleared_mwh`, rounded half up to 2
    decimal places."
    PRD §3.8: "computes `revenue_cents` as `cleared_mwh` multiplied by the
    clearing price, rounded half up to integer cents, moving the session to
    `SETTLED`."

    Design: Corner/calculations/dispatch_price_floor_before_capacity_cap
    """
    project, esa = setup_commissioned_project(api=api)
    validate_success(
        api.recompute_projection(project["id"], {"equivalent_cycles": 0}, PERF)
    )
    bs1 = create_bid_session(
        project["id"], api=api,
        window_start="2026-09-03T00:00:00Z", window_end="2026-09-03T04:00:00Z",
        offer_mwh=20, offer_price_cents_per_mwh=9000,
    )
    bs2 = create_bid_session(
        project["id"], api=api,
        window_start="2026-09-04T00:00:00Z", window_end="2026-09-04T04:00:00Z",
        offer_mwh=20, offer_price_cents_per_mwh=9000,
    )

    c1 = validate_success(
        api.record_bid_clearing(
            bs1["id"],
            {"clearing_price_cents_per_mwh": 8999, "market_cleared_mwh": 30},
            MARKET,
        )
    )
    assert c1["cleared_mwh"] == 0, (
        f"8999 < floor 9000 short-circuits before the capacity cap, got {c1['cleared_mwh']}"
    )
    s1 = validate_success(api.settle_bid_session(bs1["id"], MARKET))
    assert s1["revenue_cents"] == 0

    c2 = validate_success(
        api.record_bid_clearing(
            bs2["id"],
            {"clearing_price_cents_per_mwh": 9000, "market_cleared_mwh": 30},
            MARKET,
        )
    )
    # floor inclusive: cleared = min(offer 20, min(projected 40, market 30)) = 20
    assert c2["cleared_mwh"] == pytest.approx(20, abs=0.001), (
        f"min(20, min(40, 30)) == 20, got {c2['cleared_mwh']}"
    )
    s2 = validate_success(api.settle_bid_session(bs2["id"], MARKET))
    assert s2["revenue_cents"] == 180000, (
        f"20 * 9000 == 180000, got {s2['revenue_cents']}"
    )
