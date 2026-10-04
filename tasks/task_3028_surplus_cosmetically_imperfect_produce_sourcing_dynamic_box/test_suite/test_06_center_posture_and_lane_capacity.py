"""Fulfillment-center forward posture, the lane capacity lock and its recovery."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ApiErrorId,
    build_order,
    make_center,
    make_lot,
    make_operator_headers,
    make_supplier,
    reset_clock,
    setup_box_scenario,
    setup_subscriber,
)
from test_helpers.fixtures import (
    advance_clock,
    award_lot,
    finalize_order,
    line_plan,
    make_bid,
    make_lot_ready,
    make_order_buildable,
    order_items,
    refresh_center,
    refresh_order,
)


def _hours_between(earlier_iso, later_iso):
    from datetime import datetime

    def parse(value):
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")

    return (parse(later_iso) - parse(earlier_iso)).total_seconds() / 3600


def _award_and_ready(api, lot, supplier):
    make_bid(api, lot["id"], supplier["id"], cost=100,
             quantity=lot["quantity_available"])
    return make_lot_ready(api, award_lot(api, lot), "PASS")


def _choke_scenario(api, *, code="DEMO-NE", region="NE", email="choke@example.com",
                    cycles=(2, 3), max_concurrent_building_cycles=1):
    """One center at a capacity of whichever cap, one PASS lot, N DRAFT orders."""
    return setup_box_scenario(
        api, cycles=cycles, code=code, region=region, email=email,
        max_concurrent_building_cycles=max_concurrent_building_cycles,
        lot_overrides={"category": "FRUIT", "procurement_grade": "SURPLUS",
                       "unit_weight_grams": 100, "unit_cost_cents": 100,
                       "quantity_available": 400},
    )


# ---------------------------------------------------------------------------
# The posture ladder
# ---------------------------------------------------------------------------
def test_center_posture_raises_monotonically_and_locks_the_lane(api):
    """PRD §2.7: "a center whose `serving_cycle_index` has reached exactly the
    cap sits at `CONSTRAINED`; and a center whose `serving_cycle_index` has
    passed the cap — that is, is at least one greater than it — sits at `DEGRADED`."
    PRD §3.4: "an order is refused with `ERR_CENTER_FORWARD_LOCKED` and HTTP
    status 409 unless the owning center's `forward_posture` is exactly `OPEN`."

    Design: Corner/state_machines/center_forward_posture_monotone_raise_locks_the_lane
    """
    scenario = _choke_scenario(api, cycles=(2, 3, 4), max_concurrent_building_cycles=2)
    center, customer, subscription = scenario["center"], scenario["customer"], scenario["subscription"]
    o1, o2, o3 = scenario["orders"]

    # Two finalisations take the counter to the cap of two.
    # The first finalisation takes the counter to one, still below the cap.
    validate_success(
        api.finalize_box_order(o1["id"], {"expected_box_order_version": o1["version"]}, ADMIN),
        200,
    )
    center_read = refresh_center(api, center)
    assert center_read["serving_cycle_index"] == 1
    assert center_read["forward_posture"] == "OPEN"

    second = get_success_data(
        api.finalize_box_order(o2["id"], {"expected_box_order_version": o2["version"]}, ADMIN)
    )
    center_read = refresh_center(api, center)
    assert center_read["serving_cycle_index"] == 2
    assert center_read["forward_posture"] == "CONSTRAINED"

    # A CONSTRAINED center still admits a finalisation — the deliberate asymmetry.
    third = get_success_data(
        api.finalize_box_order(
            o3["id"], {"expected_box_order_version": o3["version"]}, ADMIN
        )
    )
    center_read = refresh_center(api, center)
    assert center_read["serving_cycle_index"] == 3
    assert center_read["forward_posture"] == "DEGRADED"
    # The DEGRADED cascade reroutes every in-flight order of the center.
    assert refresh_order(api, o3)["status"] == "REROUTED"

    # A DEGRADED center refuses a new order.
    response = api.create_box_order(
        {"customer_id": customer["id"], "subscription_id": subscription["id"],
         "serving_cycle_index": 4, "cuisine_preference": "STANDARD"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_CENTER_FORWARD_LOCKED, 409)


def test_build_is_refused_while_the_center_sits_at_its_cycle_cap(api):
    """PRD §3.9: "The owning center's `forward_posture` must be exactly `OPEN`
    for order creation and for a build start"
    PRD §2.7: "opening a new order and starting a build at a `CONSTRAINED`
    center are both refused by the posture permit rule"

    Design: Difficulty/resource_temporal_overlap/capacity_interval_requires_strict_gain_against_the_full_pool
    """
    scenario = _choke_scenario(api, cycles=(2,), max_concurrent_building_cycles=1)
    center, lot = scenario["center"], scenario["lot"]
    order = scenario["orders"][0]

    # Taking the counter to its cap of one leaves the center CONSTRAINED.
    order = refresh_order(api, order)
    finalize_order(api, order)
    center_read = refresh_center(api, center)
    assert center_read["serving_cycle_index"] == 1
    assert center_read["forward_posture"] == "CONSTRAINED"

    # Promotion still fires, but the CONSTRAINED posture refuses the build —
    # its own order holds the lane's only unallocated remainder.
    buildable = make_order_buildable(api, order, center)
    assert buildable["status"] == "READY_TO_BUILD"

    response = api.build_box_order(
        buildable["id"],
        {"expected_box_order_version": buildable["version"],
         "line_plan": line_plan((lot["id"], 6))},
        make_operator_headers(center["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CENTER_FORWARD_LOCKED, 409)

    read = refresh_order(api, buildable)
    assert read["status"] == "READY_TO_BUILD"
    assert len(order_items(api, buildable)) == 0
    lot_read = get_success_data(api.get_supply_lot(lot["id"], ADMIN))
    assert lot_read["quantity_available"] == 400


# ---------------------------------------------------------------------------
# Recovering the lane
# ---------------------------------------------------------------------------
def test_advance_cycle_reopens_the_center_and_readmits_the_build(api):
    """PRD §3.5: "the center's build cycle is rolled forward by decrementing
    its `serving_cycle_index` to whichever is larger of zero and the counter
    minus one, and the decrement recomputes the forward posture from the new counter."
    PRD §2.7: "finalising an order remains admitted at a `CONSTRAINED` center
    precisely so that the counter can still be advanced and the center worked
    back down toward `OPEN`."

    Design: Difficulty/resource_temporal_overlap/maintenance_interval_blocks_the_center_between_two_helped_windows
    """
    scenario = _choke_scenario(api, cycles=(2, 3), max_concurrent_building_cycles=1)
    center, lot = scenario["center"], scenario["lot"]
    o1, o2 = scenario["orders"]

    validate_success(
        api.finalize_box_order(
            o1["id"], {"expected_box_order_version": o1["version"]}, ADMIN
        ),
        200,
    )
    center_read = refresh_center(api, center)
    assert center_read["forward_posture"] == "CONSTRAINED"

    # Closing the cycle returns the center to OPEN and re-admits the next window.
    advance_cycle = validate_success(
        api.advance_center_cycle(
            center["id"],
            {"expected_fulfillment_center_version": center_read["version"]},
            ADMIN,
        ),
        200,
    )
    assert advance_cycle["serving_cycle_index"] == 0
    assert advance_cycle["forward_posture"] == "OPEN"

    validate_success(
        api.finalize_box_order(
            o2["id"], {"expected_box_order_version": o2["version"]}, ADMIN
        ),
        200,
    )
    read = make_order_buildable(api, o2, center)
    built = build_order(api, read, center, line_plan((lot["id"], 6)), make_buildable=False)
    assert built["status"] == "BUILDING"
    assert len(order_items(api, built, "INCLUDED")) == 1


# ---------------------------------------------------------------------------
# Order cutoff precedence and the window arithmetic
# ---------------------------------------------------------------------------
def test_finalize_after_the_ready_deadline_is_refused(api):
    """PRD §3.4: "The much-discussed `cutoff_met` flag is then simply the
    statement that the order's `created_at` is strictly before its
    `ready_deadline` — an order created at the deadline itself has not met the cutoff."
    PRD §3.9: "Eighth is the order cutoff: an order must have been created
    strictly before its `ready_deadline`, and a finalise attempt on an order
    that was created at or after that instant is refused with
    `ERR_ORDER_CUTOFF_MISSED` and HTTP status 422."

    Design: Difficulty/priority_pair_validation_conflict/order_cutoff_breach_outranks_the_center_forward_lock
    """
    reset_clock(api)
    center = make_center(api, code="CHOKE", region="NE", max_concurrent_building_cycles=1)
    supplier = make_supplier(api, name="Choke Farms", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=200,
                   unit_cost_cents=100, quantity_available=200)
    lot = _award_and_ready(api, lot, supplier)
    customer, subscription = setup_subscriber(api, region="NE", email="choke@example.com")
    peer, peer_subscription = setup_subscriber(api, region="NE", email="choke-peer@example.com")
    # The cycle-1 order is opened after its own ready deadline has already
    # passed (the default clock is the cycle-1 start, and the deadline sits 36
    # hours before it), so its cutoff was never met.
    o1 = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 1, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    o2 = get_success_data(
        api.create_box_order(
            {"customer_id": peer["id"], "subscription_id": peer_subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    assert o1["cutoff_met"] is False, (
        "Setup failed: the cycle-1 order was created after its ready_deadline"
    )

    # Finalising the cycle-2 order takes the counter to its cap of one, so the
    # centre is CONSTRAINED when the cyclic-cutoff finalisation is attempted.
    validate_success(
        api.finalize_box_order(
            o2["id"], {"expected_box_order_version": o2["version"]}, ADMIN
        ),
        200,
    )
    center_read = refresh_center(api, center)
    assert center_read["forward_posture"] == "CONSTRAINED"

    # The cutoff breach (rung 8) is reported ahead of the lane posture (rung 9).
    response = api.finalize_box_order(
        o1["id"], {"expected_box_order_version": o1["version"]}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_ORDER_CUTOFF_MISSED, 422)

    read = refresh_order(api, o1)
    assert read["cutoff_met"] is False
    assert read["status"] == "DRAFT"
    center_after = refresh_center(api, center)
    assert center_after["serving_cycle_index"] == 1


def test_order_window_cutoff_lead_hours_differ_by_center_region(api):
    """PRD §3.4: "the `ready_deadline` for an order is that start instant minus
    a regional cutoff lead: 36 hours in `NE`, 48 hours in `MW`, 48 hours in
    `SO`, and 60 hours in `WE`."
    PRD §3.4: "The `build_deadline` is the cycle's start instant plus a build
    window of 72 hours"

    Design: Corner/calculations/order_window_cutoff_lead_hours_differ_by_center_region
    """
    reset_clock(api)
    ne_center = make_center(api, code="DEMO-NE", region="NE")
    we_center = make_center(api, code="DEMO-WE", region="WE")
    _ = (ne_center, we_center)  # the centers only pin each subscriber's region
    ne_customer, ne_sub = setup_subscriber(api, region="NE", email="winne@example.com")
    we_customer, we_sub = setup_subscriber(api, region="WE", email="winwe@example.com")

    # Cycle 1's start is the default clock and its ready deadline sits before
#     that instant, so the order is opened one cycle later — at the clock's
#     own reading — which is the only window that still meets the cutoff.
    ne_order = get_success_data(
        api.create_box_order(
            {"customer_id": ne_customer["id"], "subscription_id": ne_sub["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    we_order = get_success_data(
        api.create_box_order(
            {"customer_id": we_customer["id"], "subscription_id": we_sub["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )

    # Both orders were created at the default clock, so both met their cutoff.
    assert ne_order["cutoff_met"] is True
    assert we_order["cutoff_met"] is True
    assert ne_order["build_blocked"] is False
    assert we_order["build_blocked"] is False
    # The regional cutoff leads differ: NE by 36 hours, WE by 60, so the two
    # deadlines sit 24 hours apart on the same cycle.
    assert (
        _hours_between(we_order["ready_deadline"], ne_order["ready_deadline"]) == 24
    )
    # Both windows close 72 hours after the same cycle start.
    assert (
        _hours_between(ne_order["ready_deadline"], ne_order["build_deadline"]) == 108
    )
    assert ne_order["build_deadline"] == we_order["build_deadline"]