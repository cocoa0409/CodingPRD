"""Queue A (difficulty) translations: dual-variant calculations.

Covers rule_id dual_variant_calc:
- travel_cost_planning_vs_execution_diverge (2 tests)
- stow_density_vs_accessibility_pick_different_pods (1 test; the
  accessibility_first branch outcome is not uniquely derivable from PRD
  because PRD never specifies the accessibility_rank of a confirm-created
  slot, so the rank-driven winner cannot be constructed via declared
  endpoints)
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    get_success_data,
    set_clock,
    create_zone,
    create_drive_unit,
    create_pod,
    create_sku,
    create_pick_station,
    create_order_with_line,
    create_pick_task_payload,
    create_stow_task_payload,
    create_shift_plan_payload,
    get_station_version,
    get_sku_version,
    get_pick_task,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]
OPERATOR = TEST_USERS["station_operator_headers"]


def _setup_travel_cost_scenario():
    """Two zones Z1(0,0) and Z2(10,0); pod P1 in Z1 stocked with 20 units of
    SKU1; station ST1 in Z2; drive units DU1..DU2 homed in Z1; a background
    dispatched task so congestion == 1 when the measured task dispatches.
    """
    set_clock("2026-09-01T08:00:00Z")
    z1 = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                     max_human_occupancy=2)
    z2 = create_zone(zone_code="Z2", grid_x=10, grid_y=0, width=10, height=10,
                     max_human_occupancy=2)
    du1 = create_drive_unit(z1["id"], unit_code="DU1")
    du2 = create_drive_unit(z1["id"], unit_code="DU2")
    pod = create_pod(z1["id"], pod_code="P1", slot_capacity=5)
    sku = create_sku(sku_code="SKU1", velocity_class="HIGH")
    station = create_pick_station(z2["id"], station_code="ST1", max_queue=10)

    stow = get_success_data(
        api_client.create_stow_task(
            create_stow_task_payload(sku["id"], quantity=20), FLOW
        )
    )
    get_success_data(api_client.place_stow_task(stow["id"], sku["version"], FLOW))
    get_success_data(api_client.confirm_stow_task(stow["id"], OPERATOR))

    # Background order + task dispatched -> one EN_ROUTE unit in the corridor.
    obg, obg_line = create_order_with_line(sku["id"], quantity=1)
    pt_bg = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                obg["id"], obg_line["id"], pod["id"], station["id"], quantity=1
            ),
            FLOW,
        )
    )
    get_success_data(
        api_client.sequence_pick_task(pt_bg["id"], get_station_version(station["id"]), FLOW)
    )
    get_success_data(api_client.dispatch_pick_task(pt_bg["id"], FLOW))

    return {
        "z1": z1, "z2": z2, "du1": du1, "du2": du2, "pod": pod,
        "sku": sku, "station": station, "pt_bg": pt_bg,
    }


def _dispatch_measured_task(env):
    """Create + sequence + dispatch the measured task against env; returns it."""
    o1, o1_line = create_order_with_line(env["sku"]["id"], quantity=1)
    pt1 = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                o1["id"], o1_line["id"], env["pod"]["id"],
                env["station"]["id"], quantity=1,
            ),
            FLOW,
        )
    )
    get_success_data(
        api_client.sequence_pick_task(
            pt1["id"], get_station_version(env["station"]["id"]), FLOW
        )
    )
    return get_success_data(api_client.dispatch_pick_task(pt1["id"], FLOW))


def test_travel_cost_planning_variant_caps_congestion(api):
    """PRD §3.3: "The base cost is the Manhattan distance between the pod's
    zone origin and the station's zone origin."
    PRD §3.3: "The planning variant adds ten hundredths of the base per
    congesting unit, with the congestion count capped at 3."
    PRD §2.8: "All travel-cost figures (`est_cost`, `actual_cost`, and the
    battery/odometer adjustments derived from them) are computed to 2 decimal
    places with round-half-up rounding."

    Design: Difficulty/dual_variant_calc/travel_cost_planning_vs_execution_diverge
    """
    env = _setup_travel_cost_scenario()
    dispatched = _dispatch_measured_task(env)
    # base = manhattan((0,0),(10,0)) = 10; congestion = 1 EN_ROUTE unit;
    # planning: 10 * (1 + 0.10 * 1) = 11.00
    assert dispatched["est_cost"] == pytest.approx(11.00, abs=0.001), (
        f"planning-variant est_cost must be 11.00, got {dispatched['est_cost']}"
    )


def test_travel_cost_execution_variant_uncapped_differs(api):
    """PRD §3.3: "The execution variant — computed on delivery, written to
    `actual_cost`, and also subtracted from the unit's `battery_pct` and added
    to its `odometer_cells` — adds twenty-five hundredths of the base per
    congesting unit with **no cap**, and adds a flat 4-cell detour surcharge
    when the carrying unit's home zone was `RESTRICTED` at dispatch time."

    Design: Difficulty/dual_variant_calc/travel_cost_planning_vs_execution_diverge
    """
    env = _setup_travel_cost_scenario()
    dispatched = _dispatch_measured_task(env)
    delivered = get_success_data(api_client.deliver_pick_task(dispatched["id"], FLOW))
    # execution: 10 * (1 + 0.25 * 1) = 12.50 (no detour; home zone OPEN)
    assert delivered["actual_cost"] == pytest.approx(12.50, abs=0.001), (
        f"execution-variant actual_cost must be 12.50, got {delivered['actual_cost']}"
    )
    assert delivered["est_cost"] != delivered["actual_cost"], (
        "planning (capped, no detour) and execution (uncapped, detour) variants "
        "must diverge on the same inputs"
    )


def _setup_two_pod_stow_scenario():
    """PA in Z1(0,0) capacity 10 filled with 10 units of ten distinct filler
    SKUs (one slot each); PB in Z2(5,0) capacity 10 holding 1 slot; then two
    of PA's filler units are picked out so PA's slots_used drops to 8.

    Why the detour: stow placement is algorithm-driven, so a stow always
    lands on the densest reachable pod — PA can only be filled by letting it
    win every placement until full, and PB only receives a stow once PA is
    ineligible (full). PA is then brought back below capacity by picking two
    filler units out through the full pick lifecycle.

    Final world: PA density 0.8 at distance 0, PB density 0.1 at distance 5,
    and neither pod holds a slot for the measured SKU — so both access terms
    fall back to the PRD-stated baseline of 3 and the comparison is driven
    purely by density and distance, independent of the (PRD-unspecified)
    accessibility_rank of confirm-created slots.

    Returns dict(z1, z2, pa, pb).
    """
    set_clock("2026-09-01T08:00:00Z")
    z1 = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                     max_human_occupancy=2)
    z2 = create_zone(zone_code="Z2", grid_x=5, grid_y=0, width=10, height=10,
                     max_human_occupancy=2)
    pa = create_pod(z1["id"], pod_code="PA", slot_capacity=10)
    pb = create_pod(z2["id"], pod_code="PB", slot_capacity=10)
    du = create_drive_unit(z1["id"], unit_code="DU1")
    station = create_pick_station(z1["id"], station_code="ST1", max_queue=10)
    # Roster a picker so begin-pick is legal on the current shift date.
    get_success_data(
        api_client.create_shift_plan(
            create_shift_plan_payload(
                plan_date="2026-09-01", staffed_pickers=1, planned_units=1
            ),
            ADMIN,
        )
    )

    def _stow_one(sku, expect_pod):
        task = get_success_data(
            api_client.create_stow_task(
                create_stow_task_payload(sku["id"], quantity=1), FLOW
            )
        )
        placed = get_success_data(
            api_client.place_stow_task(task["id"], get_sku_version(sku["id"]), FLOW)
        )
        assert placed["pod_id"] == expect_pod["id"], (
            f"fixture stow must land on pod {expect_pod['pod_code']}, "
            f"landed on {placed['pod_id']}"
        )
        get_success_data(api_client.confirm_stow_task(task["id"], OPERATOR))

    # Fill PA to capacity: ten 1-unit stows of ten distinct SKUs. PA wins
    # every placement (highest density term, zero distance term) until full.
    fillers = []
    for i in range(10):
        sku = create_sku(sku_code=f"FILL-{i}", velocity_class="LOW")
        _stow_one(sku, pa)
        fillers.append(sku)

    # PA is now full (slots_used == slot_capacity); the next stow of a new
    # SKU is ineligible for PA and must land on PB.
    pb_sku = create_sku(sku_code="PB-SKU", velocity_class="LOW")
    _stow_one(pb_sku, pb)

    # Pick two filler units out of PA through the full lifecycle so two
    # slots drain to quantity 0 and PA's slots_used drops to 8 (density 0.8).
    for sku in fillers[:2]:
        order, line = create_order_with_line(sku["id"], quantity=1)
        task = get_success_data(
            api_client.create_pick_task(
                create_pick_task_payload(
                    order["id"], line["id"], pa["id"], station["id"], quantity=1
                ),
                FLOW,
            )
        )
        get_success_data(
            api_client.sequence_pick_task(
                task["id"], get_station_version(station["id"]), FLOW
            )
        )
        get_success_data(api_client.dispatch_pick_task(task["id"], FLOW))
        get_success_data(api_client.deliver_pick_task(task["id"], FLOW))
        get_success_data(api_client.begin_pick_task(task["id"], OPERATOR))
        get_success_data(api_client.complete_pick_task(task["id"], OPERATOR))
    return {"z1": z1, "z2": z2, "pa": pa, "pb": pb}


def test_stow_density_first_selects_dense_pod_for_low_velocity(api):
    """PRD §3.4: "For a `LOW`-velocity SKU the density-first variant scores a
    candidate as 0.6 times the density term, minus 0.3 times the distance term
    times one hundredth, minus 0.1 times the access term times one tenth."
    PRD §3.4: "The pod with the highest score wins."

    With the measured SKU absent from both pods the access term is the
    baseline 3 for both candidates, so PA scores
    0.6*0.8 - 0.3*0*0.01 - 0.1*3*0.1 = 0.4500 and PB scores
    0.6*0.1 - 0.3*5*0.01 - 0.1*3*0.1 = 0.0150; the denser pod must win.

    Design: Difficulty/dual_variant_calc/stow_density_vs_accessibility_pick_different_pods
    """
    env = _setup_two_pod_stow_scenario()
    low = create_sku(sku_code="LOW_SKU", velocity_class="LOW")
    task = get_success_data(
        api_client.create_stow_task(
            create_stow_task_payload(low["id"], quantity=1), FLOW
        )
    )
    placed = get_success_data(
        api_client.place_stow_task(task["id"], get_sku_version(low["id"]), FLOW)
    )
    assert placed["pod_id"] == env["pa"]["id"], (
        "density_first (LOW velocity) must select the denser pod PA "
        f"(score 0.4500 vs 0.0150); selected {placed['pod_id']}"
    )
