"""Order-void cascades that release capacity, and the account-hold cascade."""

from test_helpers import (
    create_replenishment_satellite,
    advance_order_to,
    api_client,
    attach_stop_ok,
    confirm_order,
    create_account,
    create_part,
    create_route,
    create_satellite,
    create_tool,
    deliver_directly,
    deliver_order,
    get_success_data,
    pick_order,
    plan_route,
    reload_account,
    reload_inventory,
    reload_order,
    reload_store,
    request_and_checkout_loan,
    set_clock,
    TEST_USERS,
    stock,
    validate_error,
    write_simple_order,
)


def _cascade_setup(daily_capacity_units=6, on_hand_units=10, first_quantity=4,
                   second_quantity=4):
    """A six-unit satellite with a draft order, a second draft order and a draft route.

    On-hand sits above the ceiling on purpose: PRD 3.4/3.3 make the daily
    capacity ceiling the binding constraint, not stock, so the refusal names
    `ERR_CAPACITY_EXCEEDED` rather than `ERR_INSUFFICIENT_STOCK`.
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Cascade Satellite",
                                 delivery_radius_miles=6.0,
                                 daily_capacity_units=daily_capacity_units)
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    inv = stock(satellite["id"], plug["id"], on_hand_units)
    account = create_account(satellite["id"])
    order_a = write_simple_order(account["id"], plug["id"], quantity=first_quantity)
    confirmed_a = confirm_order(order_a["id"], account["id"])
    order_b = write_simple_order(account["id"], plug["id"], quantity=second_quantity)
    route = create_route(driver_id="drv-cascade", route_code="R-C1")
    other = create_account(satellite["id"], shop_name="Cascade Second Shop",
                           tax_id="TX-9961")
    stop_a = attach_stop_ok(route["id"], account["id"], order_ids=[order_a["id"]],
                            delivery_window_start="2026-09-02T14:00:00.000Z",
                            delivery_window_end="2026-09-02T15:00:00.000Z")
    stop_b = attach_stop_ok(route["id"], other["id"], order_ids=[],
                            delivery_window_start="2026-09-02T14:40:00.000Z",
                            delivery_window_end="2026-09-02T15:30:00.000Z",
                            travel_minutes_from_previous=15, drop_minutes=5)
    return {"satellite": satellite, "part": plug, "inventory": inv,
            "account": account, "other_account": other, "order_a": confirmed_a,
            "order_b": order_b, "route": route, "stop_a": stop_a, "stop_b": stop_b}


def test_voiding_the_confirmed_order_releases_the_reservation_and_the_committed_capacity(
        api, sales_rep_headers):
    """PRD §3.3: "for every line the reserved source's `reserved_units` and
    `committed_units_today` are both reduced by the line quantity."

    Design: Difficulty/transitive_cascade/order_confirm_cascades_to_route_stop_resequencing
    """
    ctx = _cascade_setup()
    assert reload_store(ctx["satellite"]["id"])["committed_units_today"] == 4
    assert reload_inventory(ctx["inventory"]["id"])["reserved_units"] == 4

    get_success_data(api_client.void_order(ctx["order_a"]["id"], {},
                                           sales_rep_headers))

    assert reload_inventory(ctx["inventory"]["id"])["reserved_units"] == 0, (
        "hop A: the void released the reservation"
    )
    assert reload_store(ctx["satellite"]["id"])["committed_units_today"] == 0, (
        "hop A: the void released the committed capacity"
    )


def test_the_released_capacity_is_what_lets_the_second_order_confirm(
        api, sales_rep_headers):
    """PRD §3.3: "a store whose `committed_units_today` would exceed its
    `daily_capacity_units` causes the confirmation to be refused with
    `ERR_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/transitive_cascade/order_confirm_cascades_to_route_stop_resequencing
    """
    ctx = _cascade_setup()
    blocked = api_client.confirm_order(
        ctx["order_b"]["id"],
        {"expected_order_version": reload_order(ctx["order_b"]["id"])["version"],
         "expected_account_version": reload_account(ctx["account"]["id"])["version"]},
        sales_rep_headers)
    validate_error(blocked, "ERR_CAPACITY_EXCEEDED")

    get_success_data(api_client.void_order(ctx["order_a"]["id"], {},
                                           sales_rep_headers))

    confirmed = confirm_order(ctx["order_b"]["id"], ctx["account"]["id"])
    assert confirmed["status"] == "CONFIRMED", (
        "hop B: the released capacity is what lets the second order confirm"
    )
    assert reload_store(ctx["satellite"]["id"])["committed_units_today"] == 4


def test_the_second_order_can_take_the_freed_route_slot(
        api, sales_rep_headers, route_dispatcher_headers):
    """PRD §3.3: "A successful refit clears the order's `service_route_id`"
    PRD §2.5: "For each voided order that carried a non-null `service_route_id`,
    the `RouteStop` it was dropped at is moved to `REJECTED` and every later stop
    on that `ServiceRoute` is re-derived"

    Design: Difficulty/transitive_cascade/order_confirm_cascades_to_route_stop_resequencing
    """
    ctx = _cascade_setup()
    get_success_data(api_client.void_order(ctx["order_a"]["id"], {},
                                           sales_rep_headers))
    confirmed_b = confirm_order(ctx["order_b"]["id"], ctx["account"]["id"])

    plan_route(ctx["route"]["id"])
    response = api_client.create_route_stop(
        ctx["route"]["id"],
        {"account_id": ctx["account"]["id"],
         "stop_kind": "CUSTOMER",
         "delivery_window_start": "2026-09-02T16:00:00.000Z",
         "delivery_window_end": "2026-09-02T17:00:00.000Z",
         "travel_minutes_from_previous": 15,
         "drop_minutes": 5,
         "order_ids": [confirmed_b["id"]],
         "expected_route_version": get_success_data(
             api_client.get_route(ctx["route"]["id"], route_dispatcher_headers))["version"]},
        route_dispatcher_headers)
    assert response.status_code in (200, 201), response.text

    order_a = reload_order(ctx["order_a"]["id"], sales_rep_headers)
    order_b = reload_order(confirmed_b["id"], sales_rep_headers)
    assert order_b["status"] == "CONFIRMED", (
        "hop C: the second order is live on the account"
    )
    assert order_a["status"] == "VOID"
    assert order_a.get("service_route_id") is None, (
        "hop C: the voided order's route reference is cleared"
    )


def test_the_neighbouring_stop_is_re_sequenced_by_the_confirmed_order(
        api, sales_rep_headers, route_dispatcher_headers):
    """PRD §3.5: "Every non-`REJECTED` stop on the route is ordered by a key that
    compares `delivery_window_start` ascending and then `created_at` ascending."
    PRD §3.5: "Each stop's `projected_departure_at` is its `projected_arrival_at`
    plus its `drop_minutes`."

    Design: Difficulty/transitive_cascade/order_confirm_cascades_to_route_stop_resequencing
    """
    ctx = _cascade_setup()
    get_success_data(api_client.void_order(ctx["order_a"]["id"], {},
                                           sales_rep_headers))
    confirm_order(ctx["order_b"]["id"], ctx["account"]["id"])

    plan_route(ctx["route"]["id"])

    stops = get_success_data(
        api_client.list_route_stops(ctx["route"]["id"], route_dispatcher_headers))
    sequenced = [s for s in stops if s["status"] == "SEQUENCED"]
    assert sequenced, "hop D: planning left the route's stops sequenced"

    # PRD 3.5: the route departs at 13:00, and the first stop is 15 travel
    # minutes out with a 5-minute dwell, so it projects 13:15 -> 13:20 and
    # finishes well inside its 14:40 window.
    first = [s for s in sequenced if s["stop_sequence"] == 1][0]
    assert first["projected_arrival_at"] == "2026-09-02T13:15:00.000Z"
    assert first["projected_departure_at"] == "2026-09-02T13:20:00.000Z"
    assert first["lateness_minutes"] == 0


def test_a_rejected_stop_leaves_the_route_in_a_genuinely_rejectable_state(
        api, route_dispatcher_headers):
    """PRD §3.5: "A stop may be rejected before it is ever run, from either
    `PLANNED` or `SEQUENCED` — any other state is refused with
    `ERR_STOP_NOT_REJECTABLE`"

    Design: Difficulty/transitive_cascade/order_confirm_cascades_to_route_stop_resequencing
    """
    ctx = _cascade_setup()
    plan_route(ctx["route"]["id"])

    rejected = get_success_data(
        api_client.reject_stop(ctx["stop_b"]["id"], {}, route_dispatcher_headers))
    assert rejected["status"] == "REJECTED", (
        "the chain left it in a genuinely rejectable SEQUENCED state"
    )


# ── the account-hold cascade ──────────────────────────────────────────────

def _hold_setup():
    """An over-limit account holding a live order, a draft order and a checked-out loan."""
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Hold Satellite",
                                 delivery_radius_miles=6.0)
    plug = create_part(sku="PLUG-100", list_price_cents=2000)
    machined = create_part(sku="MACHINED-1", list_price_cents=90000, line_code="BRK")
    inv_plug = stock(satellite["id"], plug["id"], 5)
    stock(satellite["id"], machined["id"], 5)
    account = create_account(satellite["id"], credit_limit_cents=100000)

    # An old delivered order leaves a receivable behind.
    big = write_simple_order(account["id"], machined["id"], quantity=1)
    confirmed_big = confirm_order(big["id"], account["id"])
    allocated_big = advance_order_to(confirmed_big["id"], account["id"], "ALLOCATED")
    picked_big = pick_order(allocated_big["id"])
    # PRD 3.4: a delivery requires the order to be DISPATCHED and its carrying
    # stop to be active, so the order must be committed to a route and the stop
    # dispatched before the shop can receive it.
    delivered = deliver_directly(
        account["id"], picked_big, driver_id="drv-hold-big",
        route_code="R-HB", service_date="2026-09-02T00:00:00.000Z",
        departure_at="2026-09-02T07:00:00.000Z",
        shift_end_at="2026-09-02T20:00:00.000Z",
        delivery_window_start="2026-09-02T09:00:00.000Z",
        delivery_window_end="2026-09-02T10:00:00.000Z")["order"]
    assert delivered["status"] == "DELIVERED"

    live = write_simple_order(account["id"], plug["id"], quantity=1)
    confirmed_live = confirm_order(live["id"], account["id"])
    allocated_live = advance_order_to(confirmed_live["id"], account["id"], "ALLOCATED")
    picked_live = pick_order(allocated_live["id"])

    route = create_route(driver_id="drv-hold", route_code="R-H1")
    stop_cust = attach_stop_ok(route["id"], account["id"],
                               order_ids=[picked_live["id"]],
                               delivery_window_start="2026-09-02T13:30:00.000Z",
                               delivery_window_end="2026-09-02T14:30:00.000Z")
    attach_stop_ok(route["id"], account["id"], order_ids=[],
                   stop_kind="RETURN_DESK",
                   delivery_window_start="2026-09-02T15:30:00.000Z",
                   delivery_window_end="2026-09-02T16:30:00.000Z",
                   travel_minutes_from_previous=15, drop_minutes=5)

    draft = write_simple_order(account["id"], plug["id"], quantity=1)
    tool = create_tool(tool_sku="TOOL-HOLD", tool_name="Slide Hammer",
                       deposit_amount_cents=4000, replacement_part_id=plug["id"],
                       replacement_unit_cost_cents=900)
    # PRD 3.6 gates the checkout on the ceiling too ("the account's
    # `credit_exposure_cents` plus the loan's `deposit_amount_cents` must not
    # exceed the account's `credit_limit_cents`"), so the loan is taken while the
    # account is still inside its terms.  The credit review then revises the
    # ceiling down under the live work, which is what makes the hold legal.
    loan = request_and_checkout_loan(account["id"], tool["id"],
                                     deposit_amount_cents=4000)

    get_success_data(api_client.update_account(
        account["id"],
        {"credit_limit_cents": 2000,
         "expected_account_version": reload_account(account["id"])["version"]},
        TEST_USERS["credit_analyst_headers"]))

    return {"satellite": satellite, "plug": plug, "inv_plug": inv_plug,
            "account": account, "delivered_order": delivered,
            "live_order": picked_live, "draft_order": draft,
            "route": route, "stop_cust": stop_cust, "tool": tool, "loan": loan}


def test_holding_an_over_limit_account_voids_its_live_and_draft_orders(
        api, credit_analyst_headers, sales_rep_headers):
    """PRD §2.5: "Every `PartOrder` on that account sitting in `DRAFT`,
    `CONFIRMED`, `ALLOCATED`, `PICKING`, or `DISPATCHED` is moved to `VOID`."

    Design: Difficulty/transitive_cascade/account_hold_cascades_order_void_loan_due_and_capacity_release
    """
    ctx = _hold_setup()
    held = get_success_data(api_client.hold_account(ctx["account"]["id"], {},
                                                    credit_analyst_headers))
    assert held["account_posture"] == "ON_HOLD"
    assert held["credit_exposure_cents"] > 0

    assert reload_order(ctx["live_order"]["id"], sales_rep_headers)["status"] == "VOID", (
        "hop A -> B: the live order is voided"
    )
    assert reload_order(ctx["draft_order"]["id"], sales_rep_headers)["status"] == "VOID", (
        "hop A -> B: the draft order is voided too"
    )


def test_the_hold_cascade_releases_reservations_and_committed_capacity(
        api, credit_analyst_headers):
    """PRD §2.5: "For each of those orders that had reserved units, the reserved
    source's `reserved_units` is released by the order's `reserved_unit_count`,
    and the reserved source's `committed_units_today` is reduced by the same
    count."

    Design: Difficulty/transitive_cascade/account_hold_cascades_order_void_loan_due_and_capacity_release
    """
    ctx = _hold_setup()
    get_success_data(api_client.hold_account(ctx["account"]["id"], {},
                                             credit_analyst_headers))

    assert reload_inventory(ctx["inv_plug"]["id"])["reserved_units"] == 0, (
        "hop B -> C: the void released the units the live order was holding"
    )
    assert reload_store(ctx["satellite"]["id"])["committed_units_today"] == 0


def test_the_hold_cascade_rejects_the_route_stop_that_carried_the_voided_order(
        api, credit_analyst_headers, route_dispatcher_headers):
    """PRD §2.5: "For each voided order that carried a non-null `service_route_id`,
    the `RouteStop` it was dropped at is moved to `REJECTED`"

    Design: Difficulty/transitive_cascade/account_hold_cascades_order_void_loan_due_and_capacity_release
    """
    ctx = _hold_setup()
    get_success_data(api_client.hold_account(ctx["account"]["id"], {},
                                             credit_analyst_headers))

    stop = get_success_data(
        api_client.get_route_stop(ctx["route"]["id"], ctx["stop_cust"]["id"],
                                  route_dispatcher_headers))
    assert stop["status"] == "REJECTED", (
        "hop B -> C: the stop rejection only happens because the order void ran"
    )


def test_the_hold_leaves_the_delivered_order_and_the_receivable_untouched(
        api, credit_analyst_headers):
    """PRD §2.5: "Every `PartOrder` on that account sitting in `DRAFT`,
    `CONFIRMED`, `ALLOCATED`, `PICKING`, or `DISPATCHED` is moved to `VOID`."
    PRD §2.6: "Orders in `DELIVERED`, `RETURNED` or `VOID` contribute nothing"

    Design: Difficulty/transitive_cascade/account_hold_cascades_order_void_loan_due_and_capacity_release
    """
    ctx = _hold_setup()
    before = reload_account(ctx["account"]["id"])
    get_success_data(api_client.hold_account(ctx["account"]["id"], {},
                                             credit_analyst_headers))
    after = reload_account(ctx["account"]["id"])

    assert reload_order(ctx["delivered_order"]["id"])["status"] == "DELIVERED", (
        "the already-delivered order is untouched by the cascade"
    )
    # PRD 2.6: "Orders in `DELIVERED`, `RETURNED` or `VOID` contribute nothing"
    # to credit exposure, but they stay on the receivable; the hold voids the
    # live and draft orders and leaves the delivered one's invoice alone.
    assert after["receivable_balance_cents"] == before["receivable_balance_cents"]


def test_the_hold_keeps_the_checked_out_deposit_held_and_never_suspends(
        api, credit_analyst_headers, tool_crib_headers):
    """PRD §2.6: "An account in `ON_HOLD` stays `ON_HOLD` until it is explicitly
    released, even if the aging condition would otherwise push it elsewhere."

    Design: Difficulty/transitive_cascade/account_hold_cascades_order_void_loan_due_and_capacity_release
    """
    ctx = _hold_setup()
    get_success_data(api_client.hold_account(ctx["account"]["id"], {},
                                             credit_analyst_headers))

    loan = api_client.get_loan(ctx["loan"]["id"], tool_crib_headers).json()["data"]
    assert loan["deposit_state"] == "HELD", "the held tool deposit is still on the loan"
    assert reload_account(ctx["account"]["id"])["account_posture"] == "ON_HOLD"
    assert reload_account(ctx["account"]["id"])["account_posture"] != "CREDIT_SUSPENDED"


def test_confirming_a_voided_order_reports_the_state_precondition_first(
        api, sales_rep_headers):
    """PRD §3.3: "The order's `status` must be `DRAFT`, or the request is refused
    with `ERR_ORDER_NOT_DRAFT` (HTTP 409)."
    PRD §2.12: "a state mismatch is the error the caller sees even when a later
    business rule would also have failed."

    Design: Difficulty/transitive_cascade/account_hold_cascades_order_void_loan_due_and_capacity_release
    """
    ctx = _hold_setup()
    get_success_data(api_client.hold_account(ctx["account"]["id"], {},
                                             TEST_USERS["credit_analyst_headers"]))

    response = api_client.confirm_order(
        ctx["live_order"]["id"],
        {"expected_order_version": reload_order(ctx["live_order"]["id"])["version"],
         "expected_account_version": reload_account(ctx["account"]["id"])["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_ORDER_NOT_DRAFT", expected_status=409)