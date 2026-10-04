"""Capacity, candidate-set, slice-position and record-id boundaries."""

from test_helpers import (
    create_replenishment_satellite,
    deliver_order,
    advance_order_to,
    api_client,
    attach_stop_ok,
    checkout_loan,
    commit_units_to_store,
    confirm_order,
    create_account,
    create_part,
    create_route,
    create_satellite,
    create_tool,
    dispatch_route,
    get_success_data,
    inspect_loan,
    line_item,
    pick_order,
    plan_route,
    reload_account,
    reload_inventory,
    reload_loan,
    reload_order,
    reload_store,
    reload_tool,
    request_loan,
    return_desk_stop,
    return_loan,
    set_clock,
    stock,
    validate_error,
    write_order,
    write_simple_order,
)


def test_an_order_landing_exactly_on_the_capacity_ceiling_succeeds(
        api, sales_rep_headers):
    """PRD §2.8: "A store's `committed_units_today` may never exceed its
    `daily_capacity_units`; that ceiling is re-checked after reservation."

    Design: Difficulty/boundary_precision_check/daily_capacity_boundary_inclusive_at_limit_exclusive_above
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Capacity Satellite",
                                 daily_capacity_units=6)
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    inv = stock(satellite["id"], plug["id"], 10)
    account = create_account(satellite["id"])

    first = write_simple_order(account["id"], plug["id"], quantity=4)
    confirm_order(first["id"], account["id"])
    second = write_simple_order(account["id"], plug["id"], quantity=2)
    confirmed = confirm_order(second["id"], account["id"])

    assert confirmed["status"] == "CONFIRMED", (
        "an order landing on exactly daily_capacity_units succeeds"
    )
    assert reload_store(satellite["id"])["committed_units_today"] == 6
    assert reload_inventory(inv["id"])["reserved_units"] == 6


def test_one_unit_past_the_capacity_ceiling_is_refused(api, sales_rep_headers):
    """PRD §3.3: "a store whose `committed_units_today` would exceed its
    `daily_capacity_units` causes the confirmation to be refused with
    `ERR_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/daily_capacity_boundary_inclusive_at_limit_exclusive_above
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Capacity Satellite",
                                 daily_capacity_units=6)
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    inv = stock(satellite["id"], plug["id"], 10)
    account = create_account(satellite["id"])

    first = write_simple_order(account["id"], plug["id"], quantity=4)
    confirm_order(first["id"], account["id"])
    second = write_simple_order(account["id"], plug["id"], quantity=2)
    confirm_order(second["id"], account["id"])
    third = write_simple_order(account["id"], plug["id"], quantity=1)

    response = api_client.confirm_order(
        third["id"],
        {"expected_order_version": reload_order(third["id"])["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_CAPACITY_EXCEEDED")

    assert reload_store(satellite["id"])["committed_units_today"] == 6, (
        "the failed reservation rolled back atomically"
    )
    assert reload_order(third["id"])["status"] == "DRAFT"
    assert reload_inventory(inv["id"])["reserved_units"] == 6, (
        "only the two confirmed orders hold reservations"
    )


def test_the_capacity_ceiling_is_reachable_with_a_helper_that_lands_on_it_exactly(
        api, sales_rep_headers):
    """PRD §3.3: "Because those two increments can push a store past its ceiling,
    the store's `daily_capacity_units` is re-checked in a second pass after
    reservation and the capacity epoch has been applied"

    Design: Difficulty/boundary_precision_check/daily_capacity_boundary_inclusive_at_limit_exclusive_above
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Capacity Satellite",
                                 daily_capacity_units=6)
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    stock(satellite["id"], plug["id"], 10)
    account = create_account(satellite["id"])

    commit_units_to_store(satellite["id"], account["id"], plug["id"], 6,
                          quantity_per_order=2)
    assert reload_store(satellite["id"])["committed_units_today"] == 6

    blocked = write_simple_order(account["id"], plug["id"], quantity=1)
    response = api_client.confirm_order(
        blocked["id"],
        {"expected_order_version": reload_order(blocked["id"])["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_CAPACITY_EXCEEDED")


def test_an_empty_candidate_set_leaves_the_replacement_part_null(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §3.6: "If every candidate set at every level is empty, the loan's
    `replacement_part_id` stays null, no replacement is offered, and the tool's
    deposit is retained in full, with the loan's `forfeiture_rate` pinned to
    1.00."

    Design: Difficulty/boundary_precision_check/replacement_selector_empty_candidate_set_boundary
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Empty Satellite")
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    tool = create_tool(tool_sku="TOOL-NONE", tool_name="Orphan Puller",
                       deposit_amount_cents=5000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-empty", route_code="R-E1")
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=5000)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=5000)
    return_loan(loan["id"])

    inspected = inspect_loan(loan["id"], return_condition="WORN")

    assert inspected["replacement_part_id"] is None, (
        "every candidate level was empty and the selector invented nothing"
    )
    assert inspected["forfeiture_rate"] == 1.00
    assert inspected["deposit_forfeited_cents"] == 5000


def test_a_selector_miss_still_bumps_the_tool_wear(api, tool_crib_headers):
    """PRD §3.6: "A return recorded as `WORN` or `BROKEN` advances the catalogue
    tool's `wear_accumulated` by 0.4."

    Design: Difficulty/boundary_precision_check/replacement_selector_empty_candidate_set_boundary
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Empty Satellite")
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    tool = create_tool(tool_sku="TOOL-NONE2", tool_name="Orphan Puller Two",
                       deposit_amount_cents=5000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-empty2", route_code="R-E2")
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=5000)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=5000)
    return_loan(loan["id"])
    inspect_loan(loan["id"], return_condition="WORN")

    assert reload_tool(tool["id"])["wear_accumulated"] == 0.4, (
        "the wear bump happens even on a selector miss"
    )
    assert reload_loan(loan["id"], tool_crib_headers)["status"] == "INSPECTED"


def test_closing_a_fully_forfeited_loan_leaves_the_deposit_with_the_store(
        api, sales_rep_headers, tool_crib_headers):
    """PRD §3.6: "Closing refunds the unearned deposit: `deposit_state` moves to
    `REFUNDED`, the account's `petty_cash_cents` is reduced by the deposit amount
    less the forfeited amount"

    Design: Difficulty/boundary_precision_check/replacement_selector_empty_candidate_set_boundary
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Empty Satellite")
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    tool = create_tool(tool_sku="TOOL-NONE3", tool_name="Orphan Puller Three",
                       deposit_amount_cents=5000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-empty3", route_code="R-E3")
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=5000)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=5000)
    return_loan(loan["id"])
    inspect_loan(loan["id"], return_condition="WORN")

    assert reload_account(account["id"])["petty_cash_cents"] == 5000


def test_only_the_final_order_of_a_stop_slice_may_be_delivered_first(
        api, sales_rep_headers, driver_headers):
    """PRD §3.4: "If several orders are dropped at the same stop, delivering one
    while another order at that stop has not yet been delivered is refused with
    `ERR_ROUTE_SLICE_INCOMPLETE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/delivery_slice_last_order_boundary_and_already_delivered
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Slice Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    stock(satellite["id"], plug["id"], 20)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    orders = []
    for _ in range(3):
        order = write_simple_order(account["id"], plug["id"], quantity=1)
        order = confirm_order(order["id"], account["id"])
        order = advance_order_to(order["id"], account["id"], "ALLOCATED")
        orders.append(pick_order(order["id"]))

    route = create_route(driver_id="drv-slice", route_code="R-S1")
    attach_stop_ok(route["id"], account["id"], order_ids=[o["id"] for o in orders],
                   delivery_window_start="2026-09-02T13:30:00.000Z",
                   delivery_window_end="2026-09-02T15:00:00.000Z")
    plan_route(route["id"])
    dispatch_route(route["id"])

    response = api_client.deliver_order(orders[0]["id"], {}, driver_headers)
    validate_error(response, "ERR_ROUTE_SLICE_INCOMPLETE", expected_status=409)


def test_delivering_the_final_order_of_the_slice_succeeds(api, sales_rep_headers,
                                                          driver_headers):
    """PRD §3.4: "The order's `delivered_at` is stamped with the logical clock"

    Design: Difficulty/boundary_precision_check/delivery_slice_last_order_boundary_and_already_delivered
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Slice Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    stock(satellite["id"], plug["id"], 20)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    orders = []
    for _ in range(3):
        order = write_simple_order(account["id"], plug["id"], quantity=1)
        order = confirm_order(order["id"], account["id"])
        order = advance_order_to(order["id"], account["id"], "ALLOCATED")
        orders.append(pick_order(order["id"]))

    route = create_route(driver_id="drv-slice2", route_code="R-S2")
    attach_stop_ok(route["id"], account["id"], order_ids=[o["id"] for o in orders],
                   delivery_window_start="2026-09-02T13:30:00.000Z",
                   delivery_window_end="2026-09-02T15:00:00.000Z")
    plan_route(route["id"])
    dispatch_route(route["id"])

    delivered = deliver_order(orders[-1]["id"])

    assert delivered["status"] == "DELIVERED"
    assert delivered["delivered_at"] is not None
    assert delivered["delivered_payment_due_at"] is not None


def test_a_second_delivery_of_the_same_order_is_refused(api, sales_rep_headers,
                                                        driver_headers):
    """PRD §3.4: "the order's `delivered_at` must still be unset, because a
    delivered order cannot be delivered a second time (otherwise
    `ERR_ORDER_ALREADY_DELIVERED`)."

    Design: Difficulty/boundary_precision_check/delivery_slice_last_order_boundary_and_already_delivered
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Slice Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    stock(satellite["id"], plug["id"], 20)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    order = write_simple_order(account["id"], plug["id"], quantity=1)
    order = confirm_order(order["id"], account["id"])
    order = advance_order_to(order["id"], account["id"], "ALLOCATED")
    order = pick_order(order["id"])
    route = create_route(driver_id="drv-slice3", route_code="R-S3")
    attach_stop_ok(route["id"], account["id"], order_ids=[order["id"]],
                   delivery_window_start="2026-09-02T13:30:00.000Z",
                   delivery_window_end="2026-09-02T15:00:00.000Z")
    plan_route(route["id"])
    dispatch_route(route["id"])
    deliver_order(order["id"])

    response = api_client.deliver_order(order["id"], {}, driver_headers)
    validate_error(response, "ERR_ORDER_ALREADY_DELIVERED")


def test_undelivered_orders_keep_their_reservations_and_the_receivable_counts_once(
        api, sales_rep_headers, driver_headers):
    """PRD §2.6: "The receivable is `receivable_balance_cents`, the sum of
    `captured_cents` over all non-`VOID` invoices on the account."

    Design: Difficulty/boundary_precision_check/delivery_slice_last_order_boundary_and_already_delivered
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Slice Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    inventory = stock(satellite["id"], plug["id"], 20)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    orders = []
    for _ in range(3):
        order = write_simple_order(account["id"], plug["id"], quantity=1)
        order = confirm_order(order["id"], account["id"])
        order = advance_order_to(order["id"], account["id"], "ALLOCATED")
        orders.append(pick_order(order["id"]))

    route = create_route(driver_id="drv-slice4", route_code="R-S4")
    attach_stop_ok(route["id"], account["id"], order_ids=[o["id"] for o in orders],
                   delivery_window_start="2026-09-02T13:30:00.000Z",
                   delivery_window_end="2026-09-02T15:00:00.000Z")
    plan_route(route["id"])
    dispatch_route(route["id"])
    delivered = deliver_order(orders[-1]["id"])

    # PRD 3.4: on delivery "the source store's `on_hand_units` is reduced by the
    # line quantity and its `reserved_units` is reduced by the line quantity as
    # well", so the delivered order gives its unit back and only the two
    # undelivered orders keep theirs.
    assert reload_inventory(inventory["id"])["reserved_units"] == 2, (
        "the two undelivered orders keep their reservations"
    )
    assert reload_account(account["id"])["receivable_balance_cents"] == \
        delivered["parts_subtotal_cents"]


def test_a_zero_line_record_id_is_refused_on_the_order_update(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.3: "A line carrying a `record_id` of zero or a negative value is
    refused with `ERR_INVALID_LINE_REFERENCE` (HTTP 400), and that check guards
    order creation, order line mutation, and confirmation alike."

    Design: Difficulty/boundary_precision_check/order_line_record_id_must_be_positive
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="RecId Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    stock(satellite["id"], plug["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    order = write_simple_order(account["id"], plug["id"], quantity=1)
    before = reload_order(order["id"])

    response = api_client.update_order(
        order["id"],
        {"line_items": [line_item(plug["id"], 1, record_id=0)],
         "expected_order_version": before["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_INVALID_LINE_REFERENCE", expected_status=400)


def test_a_positive_line_record_id_is_accepted_and_mutates_the_basket(
        api, sales_rep_headers):
    """PRD §3.3: "Every line's `record_id` must be greater than zero."

    Design: Difficulty/boundary_precision_check/order_line_record_id_must_be_positive
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="RecId Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    stock(satellite["id"], plug["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    order = write_order(account["id"], [line_item(plug["id"], 1, record_id=1)])

    updated = get_success_data(api_client.update_order(
        order["id"],
        {"line_items": [line_item(plug["id"], 2, record_id=1)],
         "expected_order_version": reload_order(order["id"])["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers))

    assert updated["parts_subtotal_cents"] == 3346


def test_a_rejected_record_id_update_mutates_nothing(api, sales_rep_headers):
    """PRD §3.3: "Every line's `record_id` must be greater than zero."
    PRD §2.4: "`version` is an integer that starts at its creation value and
    increments by one on every modification."

    Design: Difficulty/boundary_precision_check/order_line_record_id_must_be_positive
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="RecId Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    stock(satellite["id"], plug["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    order = write_order(account["id"], [line_item(plug["id"], 1, record_id=1)])
    before = reload_order(order["id"])
    assert before["parts_subtotal_cents"] == 1673

    api_client.update_order(
        order["id"],
        {"line_items": [line_item(plug["id"], 1, record_id=0)],
         "expected_order_version": before["version"]},
        sales_rep_headers)

    after = reload_order(order["id"])
    assert after["parts_subtotal_cents"] == 1673, (
        "the rejected update left the basket exactly as it was"
    )
    assert after["status"] == "DRAFT"
    assert after["version"] == before["version"], (
        "the rejected update advanced no version"
    )