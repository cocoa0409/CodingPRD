"""Cross-entity state dependencies and temporal overlap geometry."""

from test_helpers import (
    create_replenishment_satellite,
    close_loan,
    attach_stop_ok,
    advance_order_to_delivered,
    api_client,
    attach_stop,
    cancel_route,
    confirm_order,
    create_account,
    create_part,
    create_route,
    create_sales_rep,
    create_satellite,
    create_tool,
    get_success_data,
    line_item,
    plan_route,
    reload_account,
    reload_loan,
    reload_order,
    request_loan,
    return_desk_stop,
    return_loan,
    checkout_loan,
    inspect_loan,
    set_clock,
    stock,
    validate_error,
    write_simple_order,
)


def test_a_live_loaned_order_frees_the_desk_precondition(api, sales_rep_headers,
                                                         driver_headers,
                                                         tool_crib_headers):
    """PRD §3.6: "A `RETURN_DESK` `RouteStop` for the owning account must exist on
    a `ServiceRoute` that is not `CANCELLED` (otherwise
    `ERR_RETURN_DESK_STOP_MISSING`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/loan_inspection_requires_live_loaned_order
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Loan Dep Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    stock(satellite["id"], plug["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    order = write_simple_order(account["id"], plug["id"], quantity=2)
    confirmed = confirm_order(order["id"], account["id"])
    tool = create_tool(tool_sku="TOOL-DEP", tool_name="Torque Wrench",
                       deposit_amount_cents=6000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-loandep", route_code="R-D1")
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=6000,
                        loaned_order_id=confirmed["id"])
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=6000)
    return_loan(loan["id"])

    inspected = inspect_loan(loan["id"], return_condition="GOOD")

    assert inspected["status"] == "INSPECTED", (
        "while the order was still CONFIRMED the inspection succeeds"
    )


def test_voiding_the_loaned_order_freezes_the_loan_with_no_mutation(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §3.6: "A `RETURN_DESK` `RouteStop` for the owning account must exist on
    a `ServiceRoute` that is not `CANCELLED` (otherwise
    `ERR_RETURN_DESK_STOP_MISSING`, HTTP 409)."
    PRD §3.3: "The order's `status` must be in `{DRAFT, CONFIRMED}`"

    Design: Difficulty/cross_entity_state_dependency/loan_inspection_requires_live_loaned_order
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Loan Dep Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    stock(satellite["id"], plug["id"], 10)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    order = write_simple_order(account["id"], plug["id"], quantity=2)
    confirmed = confirm_order(order["id"], account["id"])
    tool = create_tool(tool_sku="TOOL-DEP2", tool_name="Torque Wrench Two",
                       deposit_amount_cents=6000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-loandep2", route_code="R-D2")
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=6000,
                        loaned_order_id=confirmed["id"])
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=6000)
    return_loan(loan["id"])

    voided = get_success_data(api_client.void_order(confirmed["id"], {},
                                                    sales_rep_headers))
    assert voided["status"] == "VOID"

    response = api_client.inspect_loan(loan["id"], {"return_condition": "GOOD"},
                                       tool_crib_headers)
    assert response.status_code == 409, (
        "the dependent inspection is now rejected"
    )

    loan_after = reload_loan(loan["id"], tool_crib_headers)
    assert loan_after["status"] == "RETURNED", (
        "the rejected inspection mutated nothing on the loan"
    )
    assert loan_after["replacement_part_id"] is None
    assert loan_after["deposit_state"] == "HELD"
    assert reload_account(account["id"])["petty_cash_cents"] == 6000


def test_cancelling_the_return_desk_route_removes_the_desk_stop_the_close_depends_on(
        api, sales_rep_headers, driver_headers, tool_crib_headers,
        route_dispatcher_headers):
    """PRD §3.6: "A `RETURN_DESK` `RouteStop` for the owning account must exist on
    a `ServiceRoute` that is not `CANCELLED`"

    Design: Difficulty/cross_entity_state_dependency/loan_close_requires_return_desk_stop_on_uncancelled_route
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Desk Route Satellite")
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    tool = create_tool(tool_sku="TOOL-DESK", tool_name="Flare Wrench Set",
                       deposit_amount_cents=4500, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=4500)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=4500)
    return_desk_stop(account["id"], driver_id="drv-deskroute", route_code="R-D2R")
    route_id = get_success_data(api_client.list_routes(
        route_dispatcher_headers, params={"driver_id": "drv-deskroute"}))[0]["id"]

    return_loan(loan["id"])
    inspect_loan(loan["id"], return_condition="GOOD")

    cancelled = cancel_route(route_id)
    assert cancelled["status"] == "CANCELLED"
    stops = get_success_data(api_client.list_route_stops(route_id,
                                                         route_dispatcher_headers))
    assert all(s["status"] == "REJECTED" for s in stops), (
        "every stop on the route is REJECTED by the cancellation"
    )

    response = api_client.close_loan(loan["id"], {}, tool_crib_headers)
    assert response.status_code == 409
    assert response.json()["data"]["error_id"] == "ERR_RETURN_DESK_STOP_MISSING"


def test_the_close_refunds_while_the_route_is_still_live(api, sales_rep_headers,
                                                         driver_headers,
                                                         tool_crib_headers):
    """PRD §3.6: "Closing refunds the unearned deposit: `deposit_state` moves to
    `REFUNDED`, the account's `petty_cash_cents` is reduced by the deposit amount
    less the forfeited amount"

    Design: Difficulty/cross_entity_state_dependency/loan_close_requires_return_desk_stop_on_uncancelled_route
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Desk Live Satellite")
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    tool = create_tool(tool_sku="TOOL-LIVE", tool_name="Flare Wrench Live",
                       deposit_amount_cents=4500, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=4500)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=4500)
    return_desk_stop(account["id"], driver_id="drv-desk-live", route_code="R-D2L")
    return_loan(loan["id"])
    inspect_loan(loan["id"], return_condition="GOOD")

    closed = close_loan(loan["id"])

    assert closed["status"] == "CLOSED"
    assert closed["deposit_state"] == "REFUNDED"
    assert reload_account(account["id"])["petty_cash_cents"] == 0, (
        "the refund drew the whole deposit back down"
    )


def test_an_order_whose_parts_are_all_returnable_returns_cleanly(
        api, sales_rep_headers):
    """PRD §3.4: "A `CommercialSalesRep` may return an order only while its
    `status` is `DELIVERED`"

    Design: Difficulty/cross_entity_state_dependency/order_return_limited_by_parts_own_returnability
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Ret Satellite")
    battery = create_part(sku="BATTERY-1", list_price_cents=18000,
                          core_charge_cents=2200, line_code="ELC",
                          is_returnable=True)
    stock(satellite["id"], battery["id"], 5)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(battery["id"], 1)],
                                           driver_id="drv-ret", route_code="R-RET")

    returned = get_success_data(api_client.return_order(delivered["order"]["id"],
                                                        {}, sales_rep_headers))
    assert returned["status"] == "RETURNED"


def test_an_order_carrying_a_non_returnable_part_is_refused(api, sales_rep_headers,
                                                            parts_manager_headers):
    """PRD §3.4: "Every line on the order must carry a part whose `is_returnable`
    is true; a non-returnable part anywhere on the order is refused with
    `ERR_PART_NOT_RETURNABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/order_return_limited_by_parts_own_returnability
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Ret Satellite")
    module = create_part(sku="MODULE-ECM", list_price_cents=42000,
                         core_charge_cents=0, line_code="ELC",
                         is_returnable=False)
    stock(satellite["id"], module["id"], 5)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(module["id"], 1)],
                                           driver_id="drv-ret2", route_code="R-RET2")

    response = api_client.return_order(delivered["order"]["id"], {},
                                       sales_rep_headers)
    validate_error(response, "ERR_PART_NOT_RETURNABLE")

    assert reload_order(delivered["order"]["id"])["status"] == "DELIVERED"
    core_returns = get_success_data(api_client.list_order_core_returns(
        delivered["order"]["id"], sales_rep_headers))
    assert core_returns == [], "no core return was created against the rejected order"


def test_a_returnable_order_with_a_core_opens_exactly_one_core_return(
        api, sales_rep_headers):
    """PRD §3.4: "when at least one line's part carries a `core_charge_cents`
    above zero — opens a `CoreReturn` in `INITIATED` against the order and the
    owning account."

    Design: Difficulty/cross_entity_state_dependency/order_return_limited_by_parts_own_returnability
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Ret Satellite")
    battery = create_part(sku="BATTERY-1", list_price_cents=18000,
                          core_charge_cents=2200, line_code="ELC",
                          is_returnable=True)
    stock(satellite["id"], battery["id"], 5)
    account = create_account(satellite["id"], credit_limit_cents=5000000)
    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(battery["id"], 1)],
                                           driver_id="drv-ret3", route_code="R-RET3")
    get_success_data(api_client.return_order(delivered["order"]["id"], {},
                                             sales_rep_headers))

    core_returns = get_success_data(api_client.list_order_core_returns(
        delivered["order"]["id"], sales_rep_headers))
    assert len(core_returns) == 1
    assert core_returns[0]["status"] == "INITIATED", (
        "the battery carries a 2200-cent core, so a core return is opened"
    )


def test_the_new_accounts_first_order_is_priced_at_bronze(api, sales_rep_headers):
    """PRD §2.7: "A new account starts at the `BRONZE` tier."
    PRD §3.3: "A member sequence of 1 or 2 is `BRONZE`"

    Design: Difficulty/cross_entity_state_dependency/order_pricing_band_depends_on_owner_account_sequence
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Band Sat B")
    fog = create_part(sku="FOG-3", list_price_cents=1199, line_code="LGT")
    stock(satellite["id"], fog["id"], 40)
    account = create_account(satellite["id"], credit_limit_cents=5000000)

    order = write_simple_order(account["id"], fog["id"], quantity=3)
    assert order["member_sequence"] == 1
    assert order["pricing_band"] == "BRONZE"
    assert order["tier_discount_cents"] == 0


def test_the_same_basket_prices_higher_on_a_more_tenured_account(
        api, sales_rep_headers):
    """PRD §3.3: "A member sequence of 1 or 2 is `BRONZE`; 3, 4 or 5 is `SILVER`"
    PRD §2.7: "The band is a step function of the account's `order_sequence`
    captured at creation, not a marginal schedule: the entire basket takes a
    single band's rate."

    Design: Difficulty/cross_entity_state_dependency/order_pricing_band_depends_on_owner_account_sequence
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Band Sat B")
    fog = create_part(sku="FOG-3", list_price_cents=1199, line_code="LGT")
    stock(satellite["id"], fog["id"], 40)
    veteran = create_account(satellite["id"], credit_limit_cents=5000000,
                             shop_name="Band Garage One", tax_id="TX-10002")
    newcomer = create_account(satellite["id"], credit_limit_cents=5000000,
                              shop_name="Band Garage Two", tax_id="TX-10003")

    for _ in range(5):
        order = write_simple_order(veteran["id"], fog["id"], quantity=1)
        confirm_order(order["id"], veteran["id"])

    fifth = write_simple_order(veteran["id"], fog["id"], quantity=1)
    new = write_simple_order(newcomer["id"], fog["id"], quantity=3)

    assert fifth["pricing_band"] != new["pricing_band"]
    assert fifth["pricing_band"] == "GOLD"
    assert new["pricing_band"] == "BRONZE"


def test_a_band_pinning_update_onto_another_account_is_refused(api,
                                                               sales_rep_headers):
    """PRD §3.3: "An order may only ever be priced at the band its own account has
    reached, so any attempt to repoint an order at a different account whose
    `order_sequence` would imply a different band is refused with
    `ERR_ACCOUNT_TIER_MISMATCH` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/order_pricing_band_depends_on_owner_account_sequence
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Band Sat B")
    fog = create_part(sku="FOG-3", list_price_cents=1199, line_code="LGT")
    stock(satellite["id"], fog["id"], 40)
    veteran = create_account(satellite["id"], credit_limit_cents=5000000,
                             shop_name="Band Garage One", tax_id="TX-10002")
    newcomer = create_account(satellite["id"], credit_limit_cents=5000000,
                              shop_name="Band Garage Two", tax_id="TX-10003")
    for _ in range(5):
        order = write_simple_order(veteran["id"], fog["id"], quantity=1)
        confirm_order(order["id"], veteran["id"])

    draft = write_simple_order(newcomer["id"], fog["id"], quantity=3)
    response = api_client.update_order(
        draft["id"],
        {"account_id": veteran["id"],
         "line_items": [line_item(fog["id"], 3)],
         "expected_order_version": reload_order(draft["id"])["version"],
         "expected_account_version": reload_account(newcomer["id"])["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_ACCOUNT_TIER_MISMATCH")


def test_a_window_that_only_touches_an_existing_one_is_not_an_overlap(
        api, route_dispatcher_headers):
    """PRD §3.5: "a new `CUSTOMER` stop's window may not overlap an existing
    non-`REJECTED` `CUSTOMER` stop's window for the same account on the same
    service date"

    Design: Difficulty/resource_temporal_overlap/account_delivery_window_half_open_overlap_detection
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Window Satellite")
    account = create_account(satellite["id"], credit_limit_cents=1000000)
    route = create_route(driver_id="drv-win", route_code="R-W1")
    attach_stop_ok(route["id"], account["id"], order_ids=[],
                   delivery_window_start="2026-09-02T14:00:00.000Z",
                   delivery_window_end="2026-09-02T15:00:00.000Z")

    adjacent = get_success_data(attach_stop(
        route["id"], account["id"], order_ids=[],
        delivery_window_start="2026-09-02T15:00:00.000Z",
        delivery_window_end="2026-09-02T16:00:00.000Z",
        travel_minutes_from_previous=15, drop_minutes=5))
    assert adjacent["status"] == "PLANNED", (
        "a shared endpoint is not an overlap under half-open semantics"
    )


def test_a_genuinely_overlapping_window_is_rejected(api, route_dispatcher_headers):
    """PRD §3.5: "And a new `CUSTOMER` stop's window may not overlap an existing
    non-`REJECTED` `CUSTOMER` stop's window for the same account on the same
    service date; an overlap is refused with `ERR_STOP_WINDOW_OVERLAP` (HTTP
    409)."

    Design: Difficulty/resource_temporal_overlap/account_delivery_window_half_open_overlap_detection
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Window Satellite")
    account = create_account(satellite["id"], credit_limit_cents=1000000)
    route = create_route(driver_id="drv-win2", route_code="R-W2")
    attach_stop_ok(route["id"], account["id"], order_ids=[],
                   delivery_window_start="2026-09-02T14:00:00.000Z",
                   delivery_window_end="2026-09-02T15:00:00.000Z")

    response = attach_stop(route["id"], account["id"], order_ids=[],
                           delivery_window_start="2026-09-02T14:30:00.000Z",
                           delivery_window_end="2026-09-02T15:30:00.000Z",
                           travel_minutes_from_previous=15, drop_minutes=5)
    validate_error(response, "ERR_STOP_WINDOW_OVERLAP", expected_status=409)


def test_the_two_accepted_stops_sequence_and_project_in_window_order(
        api, route_dispatcher_headers):
    """PRD §3.5: "Every non-`REJECTED` stop on the route is ordered by a key that
    compares `delivery_window_start` ascending and then `created_at` ascending."

    Design: Difficulty/resource_temporal_overlap/account_delivery_window_half_open_overlap_detection
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Window Satellite")
    account = create_account(satellite["id"], credit_limit_cents=1000000)
    route = create_route(driver_id="drv-win3", route_code="R-W3")
    first = attach_stop_ok(route["id"], account["id"], order_ids=[],
                           delivery_window_start="2026-09-02T14:00:00.000Z",
                           delivery_window_end="2026-09-02T15:00:00.000Z")
    second = get_success_data(attach_stop(
        route["id"], account["id"], order_ids=[],
        delivery_window_start="2026-09-02T15:00:00.000Z",
        delivery_window_end="2026-09-02T16:00:00.000Z",
        travel_minutes_from_previous=15, drop_minutes=5))

    plan_route(route["id"])

    stops = get_success_data(api_client.list_route_stops(route["id"],
                                                         route_dispatcher_headers))
    by_sequence = {s["stop_sequence"]: s for s in stops}
    assert by_sequence[1]["id"] == first["id"]
    assert by_sequence[2]["id"] == second["id"]
    # PRD 3.5: the projection chain begins from the route's departure (13:00);
    # the first stop travels 20 minutes and dwells 10, so the second stop arrives
    # at 13:30 + its own 15 travel minutes.
    assert by_sequence[2]["projected_arrival_at"] == "2026-09-02T13:45:00.000Z"
    assert by_sequence[2]["lateness_minutes"] == 0


def test_a_coverage_window_opening_one_second_after_a_close_is_still_an_overlap(
        api, sales_rep_headers):
    """PRD §3.1: "A request to record coverage for an account whose window would
    overlap an existing non-`EXPIRED` window for that same account is refused
    with `ERR_COVERAGE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/repcoverage_window_separation_buffer_required
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Buf Satellite")
    rep = create_sales_rep(satellite["id"], email="rep1@parts.example",
                           full_name="Rep One", district_code="D-01")
    account = create_account(satellite["id"], credit_limit_cents=1000000)
    get_success_data(api_client.create_rep_coverage(
        {"rep_id": rep["id"], "account_id": account["id"],
         "effective_from": "2026-09-01T00:00:00.000Z",
         "effective_to": "2026-10-31T00:00:00.000Z"}, sales_rep_headers))

    response = api_client.create_rep_coverage(
        {"rep_id": rep["id"], "account_id": account["id"],
         "effective_from": "2026-10-31T00:00:01.000Z",
         "effective_to": "2026-12-01T00:00:00.000Z"}, sales_rep_headers)
    validate_error(response, "ERR_COVERAGE_OVERLAP", expected_status=409)


def test_a_coverage_window_opening_a_full_day_after_a_close_is_accepted(
        api, sales_rep_headers):
    """PRD §3.1: "a window whose start is still in the future is `SCHEDULED`, one
    spanning the current instant is `ACTIVE`, and one whose end has passed is
    `EXPIRED`."

    Design: Difficulty/resource_temporal_overlap/repcoverage_window_separation_buffer_required
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Buf Satellite")
    rep = create_sales_rep(satellite["id"], email="rep2@parts.example",
                           full_name="Rep Two", district_code="D-02")
    account = create_account(satellite["id"], credit_limit_cents=1000000)
    get_success_data(api_client.create_rep_coverage(
        {"rep_id": rep["id"], "account_id": account["id"],
         "effective_from": "2026-09-01T00:00:00.000Z",
         "effective_to": "2026-10-31T00:00:00.000Z"}, sales_rep_headers))

    accepted = get_success_data(api_client.create_rep_coverage(
        {"rep_id": rep["id"], "account_id": account["id"],
         "effective_from": "2026-11-01T00:00:00.000Z",
         "effective_to": "2026-12-01T00:00:00.000Z"}, sales_rep_headers))

    assert accepted["coverage_posture"] == "SCHEDULED"
    assert accepted["effective_from"] == "2026-11-01T00:00:00.000Z", (
        "the buffer rule is what rejected the first window, not a date-format problem"
    )


def test_the_rejected_coverage_window_was_never_recorded(api, sales_rep_headers):
    """PRD §3.1: "New coverage windows must not collide. A request to record
    coverage for an account whose window would overlap an existing non-`EXPIRED`
    window for that same account is refused with `ERR_COVERAGE_OVERLAP` (HTTP
    409)."

    Design: Difficulty/resource_temporal_overlap/repcoverage_window_separation_buffer_required
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Buf Satellite")
    rep = create_sales_rep(satellite["id"], email="rep3@parts.example",
                           full_name="Rep Three", district_code="D-03")
    account = create_account(satellite["id"], credit_limit_cents=1000000)
    get_success_data(api_client.create_rep_coverage(
        {"rep_id": rep["id"], "account_id": account["id"],
         "effective_from": "2026-09-01T00:00:00.000Z",
         "effective_to": "2026-10-31T00:00:00.000Z"}, sales_rep_headers))
    # PRD 3.1: a new window must open strictly after the previous one closes, so
    # the one-second neighbour is refused with ERR_COVERAGE_OVERLAP and never
    # recorded.
    rejected = api_client.create_rep_coverage(
        {"rep_id": rep["id"], "account_id": account["id"],
         "effective_from": "2026-10-31T00:00:01.000Z",
         "effective_to": "2026-12-01T00:00:00.000Z"}, sales_rep_headers)
    validate_error(rejected, "ERR_COVERAGE_OVERLAP")
    # A window opening a full day after the previous one closes is accepted.
    get_success_data(api_client.create_rep_coverage(
        {"rep_id": rep["id"], "account_id": account["id"],
         "effective_from": "2026-11-01T00:00:00.000Z",
         "effective_to": "2026-12-01T00:00:00.000Z"}, sales_rep_headers))

    coverages = get_success_data(api_client.list_account_coverages(
        account["id"], sales_rep_headers))
    assert len(coverages) == 2, (
        "only the original and the accepted window exist for the account"
    )