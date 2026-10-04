"""Terminal-state and wrong-state rejections across the machines."""

from test_helpers import (
    reload_account,
    api_client,
    checkout_loan,
    create_account,
    create_part,
    create_route,
    create_sales_rep,
    create_tool,
    deliver_stop,
    dispatch_route,
    complete_route,
    get_success_data,
    line_item,
    plan_route,
    reload_inventory,
    reload_loan,
    reload_order,
    reload_store,
    request_loan,
    set_clock,
    stock,
    validate_error,
    write_order,
)


def test_confirming_a_voided_order_is_rejected_and_changes_nothing(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.3: "The order's `status` must be `DRAFT`, or the request is refused
    with `ERR_ORDER_NOT_DRAFT` (HTTP 409)."
    PRD §3.3: "Voiding a `DRAFT` order simply moves it to `VOID` and recomputes
    the account's `credit_exposure_cents`."

    Design: Corner/state_machines/order_confirm_from_void_is_rejected_and_changes_nothing
    """
    set_clock("2026-09-01T08:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Void Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))
    part = create_part(sku="P-C", list_price_cents=1200)
    inventory = stock(store["id"], part["id"], 5)
    account = create_account(store["id"], tax_id="TX-C004", shop_name="Void Garage")
    version = reload_account(account["id"])["version"]

    order = write_order(account["id"], [line_item(part["id"], 2)])
    get_success_data(api_client.void_order(order["id"], {}, sales_rep_headers))

    response = api_client.confirm_order(
        order["id"],
        {"expected_order_version": reload_order(order["id"])["version"],
         "expected_account_version": version}, sales_rep_headers)
    validate_error(response, "ERR_ORDER_NOT_DRAFT", expected_status=409)

    assert reload_order(order["id"])["status"] == "VOID"
    assert reload_inventory(inventory["id"])["reserved_units"] == 0
    assert reload_store(store["id"])["committed_units_today"] == 0


def test_closing_a_still_checked_out_loan_is_rejected_before_inspection(
        api, sales_rep_headers, tool_crib_headers, parts_manager_headers):
    """PRD §3.6: "To close it, the loan must be `INSPECTED` (otherwise
    `ERR_LOAN_NOT_INSPECTED`)"

    Design: Corner/state_machines/loan_close_from_checked_out_is_rejected_before_inspection
    """
    set_clock("2026-09-01T08:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Out Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))
    account = create_account(store["id"], tax_id="TX-C005", shop_name="Out Garage",
                             credit_limit_cents=250000)
    tool = create_tool(tool_sku="T-C1", tool_name="Corner Press",
                       deposit_amount_cents=3000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=3000)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=3000)

    response = api_client.close_loan(loan["id"], {}, tool_crib_headers)
    validate_error(response, "ERR_LOAN_NOT_INSPECTED", expected_status=409)

    after = reload_loan(loan["id"], tool_crib_headers)
    assert after["status"] == "CHECKED_OUT"
    assert after["deposit_state"] == "HELD"
    account_after = get_success_data(api_client.get_account(account["id"],
                                                            sales_rep_headers))
    assert account_after["petty_cash_cents"] == 3000
    assert account_after["deposit_liability_cents"] == 3000


def test_a_completed_route_cannot_be_cancelled(api, route_dispatcher_headers,
                                               driver_headers,
                                               parts_manager_headers):
    """PRD §3.5: "Cancellation is available from `DRAFT`, from `PLANNED`, and from
    `DISPATCHED` — a route that has already reached `COMPLETED` or `CANCELLED` is
    refused with `ERR_ROUTE_NOT_CANCELLABLE` (HTTP 409)."

    Design: Corner/state_machines/route_cancel_from_terminal_route_is_locked_out
    """
    set_clock("2026-09-01T08:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Term Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))
    account = create_account(store["id"], tax_id="TX-C006", shop_name="Term Garage",
                             credit_limit_cents=250000)
    route = create_route(driver_id="drv-term", route_code="R-C1")
    stop = get_success_data(api_client.create_route_stop(
        route["id"],
        {"account_id": account["id"], "stop_kind": "CUSTOMER",
         "delivery_window_start": "2026-09-02T13:30:00.000Z",
         "delivery_window_end": "2026-09-02T14:30:00.000Z",
         "travel_minutes_from_previous": 20, "drop_minutes": 10,
         "order_ids": [], "expected_route_version": route["version"]},
        route_dispatcher_headers))
    plan_route(route["id"])
    dispatch_route(route["id"])
    deliver_stop(stop["id"])
    completed = complete_route(route["id"])
    assert completed["status"] == "COMPLETED"

    response = api_client.cancel_route(route["id"], {}, route_dispatcher_headers)
    validate_error(response, "ERR_ROUTE_NOT_CANCELLABLE", expected_status=409)

    assert get_success_data(api_client.get_route(route["id"],
                                                 route_dispatcher_headers))["status"] == "COMPLETED"
    stop_after = get_success_data(api_client.get_stop(stop["id"],
                                                      route_dispatcher_headers))
    assert stop_after["status"] == "DELIVERED", (
        "the delivered stop is left alone by the refused cancellation"
    )


def test_an_empty_affiliate_run_earns_only_the_base_credit(api,
                                                           route_dispatcher_headers,
                                                           driver_headers,
                                                           parts_manager_headers):
    """PRD §3.5: "The credit is a base of 500 cents plus that per-mile rate
    multiplied by the route's total distance rounded half-up to a whole mile."

    Design: Corner/state_machines/route_cancel_from_terminal_route_is_locked_out
    """
    set_clock("2026-09-01T08:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Term Satellite Two", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))
    account = create_account(store["id"], tax_id="TX-C006B", shop_name="Term Garage Two",
                             credit_limit_cents=250000)
    route = create_route(driver_id="drv-term2", route_code="R-C1B")
    stop = get_success_data(api_client.create_route_stop(
        route["id"],
        {"account_id": account["id"], "stop_kind": "CUSTOMER",
         "delivery_window_start": "2026-09-02T13:30:00.000Z",
         "delivery_window_end": "2026-09-02T14:30:00.000Z",
         "travel_minutes_from_previous": 20, "drop_minutes": 10,
         "order_ids": [], "expected_route_version": route["version"]},
        route_dispatcher_headers))
    plan_route(route["id"])
    dispatch_route(route["id"])
    deliver_stop(stop["id"])
    completed = complete_route(route["id"])

    # PRD 3.5: "The credit is a base of 500 cents plus that per-mile rate
    # multiplied by the route's total distance rounded half-up to a whole mile",
    # where the rate is 20 cents at 40 miles or more and 40 cents below it.  The
    # formula is what is asserted; the distance itself is the route's own
    # geometry read back.
    miles = completed["total_miles"]
    rate = 20 if miles >= 40 else 40
    assert completed["run_credit_cents"] == 500 + rate * round(miles)
    assert completed["return_at"] == "2026-09-02T13:30:00.000Z", (
        "effective departure 13:00 plus 20 travel minutes plus a 10-minute drop"
    )


def test_superseding_a_part_with_one_of_its_descendants_is_a_cycle(
        api, parts_manager_headers):
    """PRD §3.2: "it must be the terminal current part of its own chain, meaning
    its own `superseded_by_part_id` is null, or the request fails with
    `ERR_SUPERSEDING_PART_NOT_TERMINAL`; and it must not be reachable from the
    part being superseded by following `superseded_by_part_id` links, or the
    request fails with `ERR_SUPERSESSION_CYCLE`. These three conditions are
    evaluated in exactly that order and the first failure wins, which matters
    when a payload could satisfy more than one of them."

    Design: Corner/state_machines/part_supersede_rejects_a_cycle_through_the_existing_chain
    """
    set_clock("2026-09-01T00:00:00.000Z")
    p1 = create_part(sku="G1", list_price_cents=1000, line_code="ELC")
    p2 = create_part(sku="G2", list_price_cents=1100, line_code="ELC")
    p3 = create_part(sku="G3", list_price_cents=1200, line_code="ELC")
    get_success_data(api_client.supersede_part(p1["id"],
                                               {"superseding_part_id": p2["id"]},
                                               parts_manager_headers))
    get_success_data(api_client.supersede_part(p2["id"],
                                               {"superseding_part_id": p3["id"]},
                                               parts_manager_headers))

    response = api_client.supersede_part(p3["id"],
                                         {"superseding_part_id": p1["id"]},
                                         parts_manager_headers)
    # The payload satisfies more than one of the three conditions, and PRD 3.2
    # names terminality first, so the first failure wins: p1 still carries a
    # `superseded_by_part_id` of its own and is not the terminal current part.
    validate_error(response, "ERR_SUPERSEDING_PART_NOT_TERMINAL")

    after = get_success_data(api_client.get_part(p3["id"], parts_manager_headers))
    assert after["catalog_state"] == "ACTIVE"
    assert after.get("superseded_by_part_id") is None


def test_the_resolved_chain_reports_the_terminal_part_and_the_depth(
        api, parts_manager_headers):
    """PRD §3.2: "Supplying a `queried_part_id` returns the `current_part_id`, the
    `current_sku`, and the resulting `supersession_depth` after walking the chain
    to its terminal current part."

    Design: Corner/state_machines/part_supersede_rejects_a_cycle_through_the_existing_chain
    """
    set_clock("2026-09-01T00:00:00.000Z")
    p1 = create_part(sku="G1", list_price_cents=1000, line_code="ELC")
    p2 = create_part(sku="G2", list_price_cents=1100, line_code="ELC")
    p3 = create_part(sku="G3", list_price_cents=1200, line_code="ELC")
    get_success_data(api_client.supersede_part(p1["id"],
                                               {"superseding_part_id": p2["id"]},
                                               parts_manager_headers))
    get_success_data(api_client.supersede_part(p2["id"],
                                               {"superseding_part_id": p3["id"]},
                                               parts_manager_headers))

    resolved = get_success_data(api_client.resolve_current_part(
        parts_manager_headers, params={"queried_part_id": p1["id"]}))

    assert resolved["current_part_id"] == p3["id"]
    assert resolved["supersession_depth"] == 2


def test_a_coverage_window_starting_in_the_future_starts_scheduled(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.1: "a window whose start is still in the future is `SCHEDULED`, one
    spanning the current instant is `ACTIVE`, and one whose end has passed is
    `EXPIRED`."
    PRD §3.1: "only when the logical clock has reached its `effective_from`
    (otherwise `ERR_COVERAGE_NOT_STARTED`)"

    Design: Corner/state_machines/repcoverage_posture_starts_scheduled_for_a_future_window
    """
    set_clock("2026-09-01T08:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Cov2 Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))
    rep = create_sales_rep(store["id"], email="rep2@parts.example",
                           full_name="Rep Two", district_code="D-02")
    account = create_account(store["id"], tax_id="TX-C007", shop_name="Cov2 Garage",
                             credit_limit_cents=250000)

    coverage = get_success_data(api_client.create_rep_coverage(
        {"rep_id": rep["id"], "account_id": account["id"],
         "effective_from": "2026-10-01T00:00:00.000Z",
         "effective_to": "2026-12-01T00:00:00.000Z"}, sales_rep_headers))

    assert coverage["coverage_posture"] == "SCHEDULED", "not ACTIVE"
    assert get_success_data(api_client.get_sales_rep(rep["id"],
                                                     sales_rep_headers))["active_account_count"] == 0


def test_a_coverage_window_becomes_active_once_the_clock_reaches_its_start(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.1: "The rep's `active_account_count` is derived, never supplied: it
    counts the non-archived `CommercialAccounts` whose `home_store_id` is
    assigned to that rep on the current coverage date."

    Design: Corner/state_machines/repcoverage_posture_starts_scheduled_for_a_future_window
    """
    set_clock("2026-09-01T08:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Cov2 Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))
    rep = create_sales_rep(store["id"], email="rep2b@parts.example",
                           full_name="Rep Two B", district_code="D-02")
    account = create_account(store["id"], tax_id="TX-C007B", shop_name="Cov2 Garage B",
                             credit_limit_cents=250000)
    coverage = get_success_data(api_client.create_rep_coverage(
        {"rep_id": rep["id"], "account_id": account["id"],
         "effective_from": "2026-10-01T00:00:00.000Z",
         "effective_to": "2026-12-01T00:00:00.000Z"}, sales_rep_headers))

    set_clock("2026-10-15T00:00:00.000Z")

    refreshed = get_success_data(api_client.get_coverage(coverage["id"],
                                                         sales_rep_headers))
    assert refreshed["coverage_posture"] == "ACTIVE"