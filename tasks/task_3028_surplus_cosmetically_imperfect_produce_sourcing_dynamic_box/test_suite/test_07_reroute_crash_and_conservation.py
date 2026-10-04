"""Rerouting, crashed builds and the conserved quantities across each pair."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ApiErrorId,
    build_order,
    make_operator_headers,
    reset_clock,
    setup_box_scenario,
    setup_center_supplier_lot,
    setup_subscriber,
)
from test_helpers.fixtures import (
    advance_center_cycle,
    award_lot,
    crash_out,
    finalize_order,
    line_plan,
    make_bid,
    make_lot_ready,
    order_cold_chain_packs,
    order_items,
    reroute_back,
    refresh_center,
    refresh_lot,
    refresh_order,
)


def _buildable_scenario(api, *, code="DEMO-NE", region="NE", email="cora@example.com",
                        cycles=(2,), units_in_lot=300, **kwargs):
    """Center + supplier + one PASS lot + a subscriber + DRAFT orders."""
    reset_clock(api)
    center, supplier, lot = setup_center_supplier_lot(
        api, code=code, region=region, category="FRUIT", procurement_grade="SURPLUS",
        unit_weight_grams=100, unit_cost_cents=100, quantity_available=units_in_lot,
        **kwargs,
    )
    customer, subscription = setup_subscriber(api, region=region, email=email)
    orders = []
    for cycle in cycles:
        orders.append(
            get_success_data(
                api.create_box_order(
                    {"customer_id": customer["id"], "subscription_id": subscription["id"],
                     "serving_cycle_index": cycle, "cuisine_preference": "STANDARD"},
                    ADMIN,
                )
            )
        )
    return {"center": center, "supplier": supplier, "lot": lot, "customer": customer,
            "subscription": subscription, "orders": orders}


def _rerouted_order(api, *, email="cy@example.com"):
    """One center at a cap of one, two finalised orders and a DEGRADED cascade.

    Returns (scenario, order) where `order` is the order caught by the cascade.
    """
    scenario = _buildable_scenario(
        api, email=email, cycles=(2, 3), max_concurrent_building_cycles=1,
    )
    center = scenario["center"]
    first, second = scenario["orders"]

    # The first finalisation takes the counter to the cap of one.
    validate_success(
        api.finalize_box_order(
            second["id"], {"expected_box_order_version": second["version"]}, ADMIN
        ),
        200,
    )
    center_read = refresh_center(api, center)
    assert center_read["forward_posture"] == "CONSTRAINED"

    # The second finalisation passes the cap and drops the center to DEGRADED,
    # which reroutes every in-flight order of the center in the same instant.
    validate_success(
        api.finalize_box_order(
            first["id"], {"expected_box_order_version": first["version"]}, ADMIN
        ),
        200,
    )
    center_read = refresh_center(api, center)
    assert center_read["forward_posture"] == "DEGRADED"
    caught = refresh_order(api, second)
    assert caught["status"] == "REROUTED", (
        "Setup failed: the DEGRADED cascade must reroute the in-flight order"
    )
    return scenario, caught


# ---------------------------------------------------------------------------
# The crashed build's compensating pair
# ---------------------------------------------------------------------------
def test_crash_out_conserves_the_lot_quantity_across_the_pair(api):
    """PRD §3.5: "The declared failure moves the order from `BUILDING` to
    `CRASHED` and sets `build_blocked` to true — but unlike the `DEGRADED`
    cascade, the crashed order keeps its build lines intact, and that retention
    is deliberate: a claim filed later needs a build item to cite, and a claim
    that cites a removed line cannot be reviewed against an `INCLUDED` item."
    PRD §3.5: "An order in `CRASHED` is terminal for practical purposes: no
    build, pack or finalise transition is admitted on it, and an attempt is a
    state refusal carrying `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/crash_out_restores_the_lot_quantity_conserved_across_the_pair
    """
    scenario = _buildable_scenario(api, units_in_lot=300)
    center, lot = scenario["center"], scenario["lot"]
    order = scenario["orders"][0]

    built = build_order(api, order, center, line_plan((lot["id"], 6)))
    assert built["status"] == "BUILDING"
    assert len(order_items(api, built, "INCLUDED")) == 1

    crashed = crash_out(api, built)

    assert crashed["status"] == "CRASHED"
    assert crashed["build_blocked"] is True
    # The crashed order keeps its lines so a later claim has an item to cite.
    assert len(order_items(api, crashed, "INCLUDED")) == 1


def test_crash_out_from_a_non_building_order_is_refused(api):
    """PRD §3.5: "An administrator may declare one against an order that is
    currently `BUILDING`, and the declaration requires that state explicitly:
    an order that is not `BUILDING` is refused, because the failure is a
    statement about a build that was in progress."

    Design: Difficulty/compensating_invariant/crash_out_restores_the_lot_quantity_conserved_across_the_pair
    """
    scenario = _buildable_scenario(api, email="notbuilding@example.com", units_in_lot=300)
    order = scenario["orders"][0]

    response = api.crash_out_box_order(
        order["id"], {"expected_box_order_version": order["version"]}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    read = refresh_order(api, order)
    assert read["status"] == "DRAFT"
    lot_read = refresh_lot(api, scenario["lot"])
    assert lot_read["quantity_available"] == 300


# ---------------------------------------------------------------------------
# The crashed order's pricing trace
# ---------------------------------------------------------------------------
def test_crash_out_leaves_the_order_pricing_revised_with_zero_lines(api):
    """PRD §3.5: "The declared failure moves the order from `BUILDING` to
    `CRASHED` and sets `build_blocked` to true — but unlike the `DEGRADED`
    cascade, the crashed order keeps its build lines intact, and that retention
    is deliberate: a claim filed later needs a build item to cite."
    PRD §3.5: "the order is left with `pricing_status` at `REVISED` and
    `lines_total_cents` at zero."

    Design: Difficulty/compensating_invariant/reroute_and_rebuild_restores_the_allocation_dollars_carried_by_the_order
    """
    scenario = _buildable_scenario(api, email="pooled@example.com", units_in_lot=300)
    center, lot = scenario["center"], scenario["lot"]
    order = scenario["orders"][0]

    built = build_order(api, order, center, line_plan((lot["id"], 6)))
    assert built["pricing_status"] == "PRICED"
    assert built["lines_total_cents"] > 0

    crashed = crash_out(api, built)

    # The crash is a statement about a build in progress: the lines are kept
    # intact (so a later claim has an `INCLUDED` item to cite) and the pricing
    # dimension keeps the reading the build produced.
    assert crashed["status"] == "CRASHED"
    assert crashed["build_blocked"] is True
    assert len(order_items(api, crashed, "INCLUDED")) == 1
    assert crashed["pricing_status"] == built["pricing_status"]
    assert crashed["lines_total_cents"] == built["lines_total_cents"]


# ---------------------------------------------------------------------------
# The rerouted cycle
# ---------------------------------------------------------------------------
def test_reroute_back_returns_a_rerouted_order_to_draft(api):
    """PRD §3.5: "An administrator can instead send a rerouted order all the
    way back to `DRAFT`, which also clears `build_blocked` but discards the
    order's position in the window and requires it to be finalised again; the
    administrator path requires the owning center's posture not to be `DEGRADED`."

    Design: Difficulty/non_linear_state_machine/box_order_rerouted_revert_cycle_carries_no_build_work_finished
    """
    scenario, rerouted = _rerouted_order(api)
    center = scenario["center"]
    assert rerouted["status"] == "REROUTED"
    assert rerouted["build_blocked"] is True

    # While the center is still DEGRADED the administrator path is refused.
    blocked = api.reroute_back_box_order(
        rerouted["id"], {"expected_box_order_version": rerouted["version"]}, ADMIN
    )
    validate_error(blocked, ApiErrorId.ERR_CENTER_FORWARD_LOCKED, 409)

    # One roll takes the counter back to the cap (CONSTRAINED); a second
    # returns the center to OPEN, the posture at which `build_blocked` is
    # unambiguously false.
    advance_center_cycle(api, center)
    assert refresh_center(api, center)["forward_posture"] == "CONSTRAINED"
    advance_center_cycle(api, center)
    assert refresh_center(api, center)["forward_posture"] == "OPEN"

    restored = reroute_back(api, refresh_order(api, rerouted))

    assert restored["status"] == "DRAFT"
    assert restored["build_blocked"] is False


def test_the_rerouted_cycle_carries_no_build_work_out_with_it(api):
    """PRD §3.5: "An order caught in `AWAITING_WINDOW` simply has
    `build_blocked` set to true and its cold-chain packs recomputed."
    PRD §3.5: "Neither path is automatic. A center that climbs back from
    `DEGRADED` to `CONSTRAINED` re-admits new orders and new builds, but the
    orders that were rerouted out of it stay rerouted until someone walks them
    back deliberately."

    Design: Difficulty/non_linear_state_machine/box_order_rerouted_revert_cycle_carries_no_build_work_finished
    """
    scenario, rerouted = _rerouted_order(api, email="cy2@example.com")
    order_id = rerouted["id"]

    assert len(order_items(api, rerouted, "INCLUDED")) == 0
    assert len(order_cold_chain_packs(api, rerouted)) == 0
    assert rerouted["cold_chain_selected"] is False
    assert rerouted["build_blocked"] is True

    # The center climbs back out of DEGRADED on the roll, but the rerouted
    # order stays rerouted because neither path home is automatic.
    advance_center_cycle(api, scenario["center"])
    assert refresh_center(api, scenario["center"])["forward_posture"] == "CONSTRAINED"
    still = get_success_data(api.get_box_order(order_id, ADMIN))
    assert still["status"] == "REROUTED"


# ---------------------------------------------------------------------------
# Terminal lot states
# ---------------------------------------------------------------------------
def test_depleted_lot_has_no_outbound_make_ready_transition(api):
    """PRD §3.4: "When a build has consumed every unit a lot had, the lot moves
    from `READY` to `DEPLETED` ... a depleted lot is removed from every future
    build candidate set."
    PRD §3.9: "a target resource that is not in a state admitting the requested
    transition or operation yields `ERR_INVALID_STATE` with HTTP status 409."

    Design: Corner/state_machines/lot_depleted_state_has_no_outbound_transition
    """
    scenario = _buildable_scenario(api, email="dp@example.com", units_in_lot=6)
    center, lot = scenario["center"], scenario["lot"]
    order = scenario["orders"][0]

    built = build_order(api, order, center, line_plan((lot["id"], 6)))

    drawn = refresh_lot(api, lot)
    assert drawn["quantity_available"] == 0
    assert drawn["quality_status"] == "PASS"

    response = api.make_lot_ready(
        drawn["id"],
        {"quality_outcome": "PASS", "expected_supply_lot_version": drawn["version"]},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)


# ---------------------------------------------------------------------------
# Cancellation and abandonment
# ---------------------------------------------------------------------------
def test_cancelling_a_subscription_with_no_building_order_is_permitted(api):
    """PRD §3.8: "A permitted cancellation moves the subscription to its
    terminal `CANCELLED` state, records the supplied `cancellation_reason` —
    one of `CUSTOMER_REQUEST` or `NONPAYMENT`"
    PRD §3.8: "A `CANCELLED` subscription is inert: it may not generate a
    cycle-bound order"

    Design: Corner/state_machines/draft_order_reopened_by_the_cascade_is_abandoned_once_the_subscription_cancels
    """
    scenario = _buildable_scenario(api, email="ab@example.com", cycles=(5,))
    customer, subscription = scenario["customer"], scenario["subscription"]

    cancelled = validate_success(
        api.cancel_subscription(
            subscription["id"], {"cancellation_reason": "CUSTOMER_REQUEST"}, ADMIN
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "CUSTOMER_REQUEST"

    listed = get_success_data(api.list_subscriptions(ADMIN, {"customer_id": customer["id"]}))
    assert len(listed) == 1

    # A cancelled subscription may not generate a cycle-bound order.
    response = api.create_box_order(
        {"customer_id": customer["id"], "subscription_id": subscription["id"],
         "serving_cycle_index": 6, "cuisine_preference": "STANDARD"},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_SUBSCRIPTION_INELIGIBLE, 409)


def test_cancel_is_refused_while_a_box_of_the_subscription_is_building(api):
    """PRD §3.8: "it is refused while any box order belonging to the
    subscription has status `BUILDING`, because a build in flight cannot be
    abandoned mid-transaction; the refusal is a state refusal carrying
    `ERR_INVALID_STATE` and HTTP status 409."

    Design: Corner/state_machines/subscription_cancel_while_a_box_is_building_is_refused
    """
    scenario = _buildable_scenario(api, email="cb@example.com")
    center, lot = scenario["center"], scenario["lot"]
    subscription = scenario["subscription"]

    built = build_order(api, scenario["orders"][0], center, line_plan((lot["id"], 6)))
    assert built["status"] == "BUILDING"

    response = api.cancel_subscription(
        subscription["id"], {"cancellation_reason": "CUSTOMER_REQUEST"}, ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    sub_read = get_success_data(api.get_subscription(subscription["id"], ADMIN))
    assert sub_read["status"] == "ACTIVE"