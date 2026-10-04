"""The route revert loop, the order fork-join, and the tool wear-band cycle."""

from test_helpers import (
    create_replenishment_satellite,
    add_tool_fitment,
    advance_order_to,
    api_client,
    attach_stop_ok,
    confirm_order,
    create_account,
    create_hub,
    create_part,
    create_route,
    create_satellite,
    create_tool,
    dispatch_order,
    dispatch_route,
    get_success_data,
    pick_order,
    plan_route,
    reload_loan,
    reload_order,
    request_and_checkout_loan,
    revert_route,
    set_clock,
    stock,
    write_simple_order,
)


def _loop_route_setup():
    """A 22-mile satellite with a hub above it, one order picked and a draft route."""
    set_clock("2026-09-01T08:00:00.000Z")
    hub = create_hub(store_code="S200", name="Loop Hub", delivery_radius_miles=40.0,
                     promise_time_minutes=90)
    satellite = create_satellite(hub_store_id=hub["id"], store_code="S100",
                                 name="Loop Satellite",
                                 delivery_radius_miles=22.0)
    battery = create_part(sku="BATTERY-1", list_price_cents=18000,
                          core_charge_cents=2200, line_code="ELC")
    stock(hub["id"], battery["id"], 10)
    account = create_account(satellite["id"], delivery_service_level="HOTSHOT")
    order = write_simple_order(account["id"], battery["id"], quantity=1)
    confirmed = confirm_order(order["id"], account["id"])
    allocated = advance_order_to(confirmed["id"], account["id"], "ALLOCATED")
    picked = pick_order(allocated["id"])
    route = create_route(driver_id="drv-loop", route_code="R-N1")
    stop = attach_stop_ok(route["id"], account["id"], order_ids=[order["id"]],
                          delivery_window_start="2026-09-02T14:00:00.000Z",
                          delivery_window_end="2026-09-02T15:00:00.000Z")
    return {"satellite": satellite, "hub": hub, "account": account,
            "order": picked, "route": route, "stop": stop}


def test_revert_to_draft_runs_the_route_cycle_backwards(api, route_dispatcher_headers):
    """PRD §3.5: "A planned route can also be pulled back: reverting to draft
    requires `PLANNED` (otherwise `ERR_ROUTE_NOT_PLANNED`), returns the route to
    `DRAFT`, and pushes every stop back to `PLANNED` with its `stop_sequence` and
    projected fields cleared."

    Design: Difficulty/non_linear_state_machine/service_route_cycle_and_part_order_fork_join
    """
    ctx = _loop_route_setup()
    planned = plan_route(ctx["route"]["id"])
    assert planned["status"] == "PLANNED"

    reverted = revert_route(ctx["route"]["id"])
    assert reverted["status"] == "DRAFT", "the cycle really runs backwards"

    stop = get_success_data(
        api_client.get_route_stop(ctx["route"]["id"], ctx["stop"]["id"],
                                  route_dispatcher_headers))
    assert stop["status"] == "PLANNED"
    assert stop.get("stop_sequence") is None, (
        "reverting clears the stop's sequencing"
    )


def test_re_planning_the_reverted_route_re_derives_sequencing(api,
                                                              route_dispatcher_headers):
    """PRD §3.5: "`stop_sequence` is then numbered from 1 upward over that
    ordering, and the projection chain is walked in the same order."

    Design: Difficulty/non_linear_state_machine/service_route_cycle_and_part_order_fork_join
    """
    ctx = _loop_route_setup()
    plan_route(ctx["route"]["id"])
    revert_route(ctx["route"]["id"])

    re_planned = plan_route(ctx["route"]["id"])
    assert re_planned["status"] == "PLANNED", "the loop is re-enterable"

    stop = get_success_data(
        api_client.get_route_stop(ctx["route"]["id"], ctx["stop"]["id"],
                                  route_dispatcher_headers))
    assert stop["stop_sequence"] == 1
    assert stop["projected_arrival_at"] == "2026-09-02T13:20:00.000Z"


def test_the_route_cycle_does_not_disturb_the_order_fork(api, sales_rep_headers,
                                                         route_dispatcher_headers):
    """PRD §3.5: "The route's `status` must be `DRAFT` (otherwise
    `ERR_ROUTE_NOT_DRAFT`)"
    PRD §3.3: "Picking is a simple progression: an order in `ALLOCATED`
    (otherwise `ERR_ORDER_NOT_ALLOCATED`) moves to `PICKING`."

    Design: Difficulty/non_linear_state_machine/service_route_cycle_and_part_order_fork_join
    """
    ctx = _loop_route_setup()
    plan_route(ctx["route"]["id"])
    revert_route(ctx["route"]["id"])
    plan_route(ctx["route"]["id"])

    order = reload_order(ctx["order"]["id"], sales_rep_headers)
    assert order["status"] == "PICKING", (
        "the route cycle does not disturb the order's own progression"
    )


def test_dispatching_then_rejecting_the_stop_pushes_the_order_back_to_confirmed(
        api, route_dispatcher_headers, sales_rep_headers):
    """PRD §3.3: "A successful refit clears the order's `service_route_id`, returns
    its `status` to `CONFIRMED`, removes the rejected stop from its route, and
    re-derives every later stop on that route."
    PRD §3.5: "rejection has the same downstream effects as a miss: the stop
    becomes `REJECTED`, its orders revert to `CONFIRMED` with their route
    cleared, and later stops are re-derived."

    Design: Difficulty/non_linear_state_machine/service_route_cycle_and_part_order_fork_join
    """
    ctx = _loop_route_setup()
    plan_route(ctx["route"]["id"])
    dispatch_route(ctx["route"]["id"])

    dispatched_order = reload_order(ctx["order"]["id"], sales_rep_headers)
    assert dispatched_order["status"] == "DISPATCHED"

    rejected = get_success_data(
        api_client.reject_stop(ctx["stop"]["id"], {}, route_dispatcher_headers))
    assert rejected["status"] == "REJECTED"

    reverted_order = reload_order(ctx["order"]["id"], sales_rep_headers)
    assert reverted_order["status"] == "CONFIRMED", (
        "the DISPATCHED branch rejoins the forward path through the rejection"
    )
    assert reverted_order.get("service_route_id") is None


def test_the_rejoined_order_walks_the_forward_path_without_revisiting_confirmed(
        api, sales_rep_headers, route_dispatcher_headers):
    """PRD §3.3: "The order's `status` must be `CONFIRMED` (otherwise
    `ERR_ORDER_NOT_CONFIRMED`)"
    PRD §3.3: "Dispatch by a `DeliveryDriver` requires the order to be in
    `PICKING`"

    Design: Difficulty/non_linear_state_machine/service_route_cycle_and_part_order_fork_join
    """
    ctx = _loop_route_setup()
    plan_route(ctx["route"]["id"])
    dispatch_route(ctx["route"]["id"])
    get_success_data(api_client.reject_stop(ctx["stop"]["id"], {},
                                            route_dispatcher_headers))

    allocated = advance_order_to(ctx["order"]["id"], ctx["account"]["id"], "ALLOCATED")
    assert allocated["status"] == "ALLOCATED"
    picked = pick_order(allocated["id"])
    assert picked["status"] == "PICKING"

    second_route = create_route(driver_id="drv-loop-2", route_code="R-N2")
    attach_stop_ok(second_route["id"], ctx["account"]["id"], order_ids=[picked["id"]],
                   delivery_window_start="2026-09-02T16:00:00.000Z",
                   delivery_window_end="2026-09-02T17:00:00.000Z")
    plan_route(second_route["id"])
    redispatch = dispatch_order(picked["id"])
    assert redispatch["status"] == "DISPATCHED"
    assert redispatch["service_route_id"] == second_route["id"]


def _wear_setup():
    """A satellite with two fitting brake parts and a checked-out loan on the tool."""
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Wear Satellite",
                                 delivery_radius_miles=4.0)
    pad = create_part(sku="PAD-1", list_price_cents=2000, line_code="BRK")
    bolt = create_part(sku="BOLT-1", list_price_cents=1500, line_code="BRK")
    stock(satellite["id"], pad["id"], 20)
    stock(satellite["id"], bolt["id"], 20)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    tool = create_tool(tool_sku="TOOL-PRESS", tool_name="Ball Joint Press",
                       deposit_amount_cents=9000,
                       replacement_part_id=bolt["id"],
                       replacement_unit_cost_cents=1100)
    add_tool_fitment(tool["id"], pad["id"], placement="FRONT", depth_index=2)
    add_tool_fitment(tool["id"], bolt["id"], placement="FRONT", depth_index=5)
    loan = request_and_checkout_loan(account["id"], tool["id"],
                                     deposit_amount_cents=9000)
    return {"satellite": satellite, "pad": pad, "bolt": bolt,
            "account": account, "tool": tool, "loan": loan}


def test_wear_adjustment_crosses_into_the_next_band_and_reselects_the_catalogue_part(
        api, tool_crib_headers):
    """PRD §3.6: "A band advance writes the new band and its three companion values:
    at `LEVEL_2` the multiplier becomes 1.20, the forfeiture rate 0.40, and the
    grace period 36 hours"

    Design: Difficulty/non_linear_state_machine/tool_catalog_cyclic_wear_bands_and_loan_self_transition
    """
    ctx = _wear_setup()
    adjusted = get_success_data(api_client.adjust_tool_wear(
        ctx["tool"]["id"], {"wear_delta_units": 26.0}, tool_crib_headers))

    assert adjusted["wear_accumulated"] == 26.0
    assert adjusted["wear_band"] == "LEVEL_2"
    assert adjusted["wear_multiplier_rate"] == 1.20
    assert adjusted["wear_forfeiture_rate"] == 0.40
    assert adjusted["wear_grace_period_hours"] == 36


def test_the_checked_out_loan_self_transition_refreshes_its_replacement_part(
        api, tool_crib_headers):
    """PRD §3.6: "refresh the `replacement_part_id` of every loan on that tool that
    is in `CHECKED_OUT`, `IN_USE`, `DUE`, or `OVERDUE`"

    Design: Difficulty/non_linear_state_machine/tool_catalog_cyclic_wear_bands_and_loan_self_transition
    """
    ctx = _wear_setup()
    get_success_data(api_client.adjust_tool_wear(
        ctx["tool"]["id"], {"wear_delta_units": 26.0}, tool_crib_headers))

    loan = reload_loan(ctx["loan"]["id"], tool_crib_headers)
    assert loan["replacement_part_id"] == ctx["pad"]["id"], (
        "the FRONT part outranks the other FRONT part on depth index alone"
    )
    assert loan["status"] == "CHECKED_OUT", (
        "the pair was observed without leaving that state"
    )
    assert loan["deposit_state"] == "HELD", "no re-checkout happened"


def test_a_further_crossing_reaches_the_top_band_and_reset_returns_to_the_base_band(
        api, tool_crib_headers):
    """PRD §3.6: "A `ToolCribAttendant` may reset an inspection-free tool's wear from
    any of `LEVEL_2`, `LEVEL_3`, `LEVEL_4`, or `LEVEL_5`"
    PRD §3.6: "The reset sets `wear_accumulated` to 0, returns the band to
    `LEVEL_1`, and restores the companion values to a multiplier of 1.00, a
    forfeiture rate of 0.00, and a grace period of 48 hours."

    Design: Difficulty/non_linear_state_machine/tool_catalog_cyclic_wear_bands_and_loan_self_transition
    """
    ctx = _wear_setup()
    get_success_data(api_client.adjust_tool_wear(
        ctx["tool"]["id"], {"wear_delta_units": 26.0}, tool_crib_headers))
    top = get_success_data(api_client.adjust_tool_wear(
        ctx["tool"]["id"], {"wear_delta_units": 59.0}, tool_crib_headers))
    assert top["wear_accumulated"] == 85.0
    assert top["wear_band"] == "LEVEL_5"

    reset = get_success_data(api_client.reset_tool_wear(ctx["tool"]["id"], {},
                                                        tool_crib_headers))
    assert reset["wear_accumulated"] == 0
    assert reset["wear_band"] == "LEVEL_1"
    assert reset["wear_multiplier_rate"] == 1.00
    assert reset["wear_forfeiture_rate"] == 0.00
    assert reset["wear_grace_period_hours"] == 48


def test_a_negative_wear_correction_floors_at_zero(api, tool_crib_headers):
    """PRD §3.6: "The tool's `wear_accumulated` becomes the larger of zero and its
    current value plus that delta, so a negative correction can never drive
    accumulated wear below zero."

    Design: Difficulty/non_linear_state_machine/tool_catalog_cyclic_wear_bands_and_loan_self_transition
    """
    ctx = _wear_setup()
    get_success_data(api_client.adjust_tool_wear(
        ctx["tool"]["id"], {"wear_delta_units": 26.0}, tool_crib_headers))

    floored = get_success_data(api_client.adjust_tool_wear(
        ctx["tool"]["id"], {"wear_delta_units": -100.0}, tool_crib_headers))
    assert floored["wear_accumulated"] == 0, (
        "a negative correction floors at zero rather than going negative"
    )
    assert floored["wear_band"] == "LEVEL_1", "the band is recomputed from the new accumulation"