"""Auth precedence, role denial, path resolution order and aggregate close guards."""

from test_helpers import (
    create_replenishment_satellite,
    advance_order_to_delivered,
    api_client,
    checkout_loan,
    close_loan,
    confirm_order,
    create_account,
    create_part,
    create_satellite,
    create_tool,
    get_success_data,
    inspect_loan,
    line_item,
    reload_account,
    return_desk_stop,
    return_loan,
    return_order,
    set_clock,
    stock,
    validate_error,
    write_simple_order,
)


def test_a_missing_user_context_header_beats_every_other_check(api):
    """PRD §2.1: "If either header is absent, or if the role is not a recognized
    role name, the request is refused with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_user_context_header_beats_every_other_check
    """
    set_clock("2026-09-01T00:00:00.000Z")
    response = api_client.create_account({}, {})
    validate_error(response, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                   expected_status=400)


def test_the_two_auth_failures_are_distinguishable(api, sales_rep_headers):
    """PRD §2.12: "The presence and validity of `X-User-ID` and `X-User-Role` is
    checked before anything else, then the caller's role against the endpoint's
    authorized roles."

    Design: Corner/validations/missing_user_context_header_beats_every_other_check
    """
    set_clock("2026-09-01T00:00:00.000Z")
    malformed = api_client.create_account({}, sales_rep_headers)
    validate_error(malformed, "ERR_INVALID_REQUEST", expected_status=400)


def test_an_unauthorized_role_is_denied_before_existence_or_state_checks(
        api, parts_manager_headers, credit_analyst_headers):
    """PRD §2.1: "If the headers are valid but the caller's role is not among the
    roles authorized for the target operation, the request is refused with
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/validations/role_denial_on_credit_analyst_operation_returns_insufficient_permissions
    """
    set_clock("2026-09-01T00:00:00.000Z")
    get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Rbac Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))

    response = api_client.create_store(
        {"store_code": "S101", "name": "Denied", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, credit_analyst_headers)
    validate_error(response, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    stores = get_success_data(api_client.list_stores(parts_manager_headers))
    assert [s for s in stores if s["store_code"] == "S101"] == [], (
        "no Store with store_code S101 exists afterwards"
    )


def test_path_identifiers_resolve_left_to_right_for_the_first_missing_one(
        api, driver_headers):
    """PRD §2.10: "When a request addresses a resource through a path that
    contains more than one identifier, the identifiers are validated left to
    right in path order, and the first one that does not resolve to an existing
    resource determines the failure."

    Design: Corner/validations/path_ids_are_resolved_left_to_right_for_the_first_missing_one
    """
    set_clock("2026-09-01T00:00:00.000Z")
    response = api_client.deliver_stop(
        "99999999-0000-0000-0000-000000000001", {}, driver_headers)
    validate_error(response, "ERR_ROUTE_STOP_NOT_FOUND", expected_status=404)


def test_the_route_level_read_on_an_unknown_id_is_separately_reachable(
        api, route_dispatcher_headers):
    """PRD §2.10: "The parent segment is always checked before the child segment,
    so a request for a stop beneath a non-existent route fails on the route,
    never on the stop."

    Design: Corner/validations/path_ids_are_resolved_left_to_right_for_the_first_missing_one
    """
    set_clock("2026-09-01T00:00:00.000Z")
    response = api_client.get_route("99999999-0000-0000-0000-000000000002",
                                    route_dispatcher_headers)
    validate_error(response, "ERR_SERVICE_ROUTE_NOT_FOUND", expected_status=404)


def test_the_stock_constraint_precedes_the_fiscal_ceiling(api, sales_rep_headers,
                                                          parts_manager_headers):
    """PRD §2.12: "Stock reservability precedes the same-day slot rule, which in
    turn precedes the daily-capacity ceiling."
    PRD §2.12: "The credit-limit ceiling precedes the receivable-balance demand."

    Design: Corner/validations/credit_limit_rule_sits_after_capacity_and_stock
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Prio Satellite",
                                 daily_capacity_units=1)
    part = create_part(sku="P-G", list_price_cents=1673)
    account = create_account(satellite["id"], tax_id="TX-C012",
                             shop_name="Prio Garage", credit_limit_cents=100)

    order = write_simple_order(account["id"], part["id"], quantity=1)

    response = api_client.confirm_order(
        order["id"],
        {"expected_order_version": order["version"],
         "expected_account_version": order["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_INSUFFICIENT_STOCK", expected_status=409)


def test_the_fiscal_ceiling_is_violated_and_simply_lower_priority(
        api, sales_rep_headers, credit_analyst_headers):
    """PRD §2.6: "The exposure the ceiling is measured against is
    `credit_exposure_cents`, a read-only figure. It is the sum, over this
    account's `PartOrder`s in `DRAFT`, `CONFIRMED`, `ALLOCATED`, `PICKING`, or
    `DISPATCHED`, of each order's `parts_subtotal_cents`"

    Design: Corner/validations/credit_limit_rule_sits_after_capacity_and_stock
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Prio Satellite Two",
                                 daily_capacity_units=1)
    part = create_part(sku="P-G2", list_price_cents=1673)
    account = create_account(satellite["id"], tax_id="TX-C012B",
                             shop_name="Prio Garage Two", credit_limit_cents=100)
    write_simple_order(account["id"], part["id"], quantity=1)

    assert reload_account(account["id"])["credit_exposure_cents"] > 100, (
        "the fiscal rule is also violated and is simply lower priority"
    )


def test_stocking_the_part_moves_the_failure_to_the_capacity_ceiling(
        api, sales_rep_headers):
    """PRD §2.12: "Stock reservability precedes the same-day slot rule, which in
    turn precedes the daily-capacity ceiling."

    Design: Corner/validations/credit_limit_rule_sits_after_capacity_and_stock
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Prio Satellite Three",
                                 daily_capacity_units=1)
    part = create_part(sku="P-G3", list_price_cents=1673)
    account = create_account(satellite["id"], tax_id="TX-C012C",
                             shop_name="Prio Garage Three", credit_limit_cents=100)

    holder = write_simple_order(account["id"], part["id"], quantity=1)
    stock(satellite["id"], part["id"], 5)
    confirm_order(holder["id"], account["id"])

    blocked = write_simple_order(account["id"], part["id"], quantity=1)
    response = api_client.confirm_order(
        blocked["id"],
        {"expected_order_version": blocked["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers)
    assert response.status_code == 409
    assert response.json()["data"]["error_id"] == "ERR_CAPACITY_EXCEEDED"


def test_an_account_with_every_open_collection_drained_can_close(
        api, sales_rep_headers, driver_headers, tool_crib_headers,
        credit_analyst_headers, route_dispatcher_headers):
    """PRD §3.8: "No `PartOrder` on the account may remain in `DRAFT`,
    `CONFIRMED`, `ALLOCATED`, `PICKING`, or `DISPATCHED` (otherwise
    `ERR_OPEN_ORDERS_EXIST`)."
    PRD §3.8: "And the account's `receivable_balance_cents` must be exactly zero
    (otherwise `ERR_RECEIVABLE_BALANCE_OUTSTANDING`, HTTP 402)."

    Design: Corner/validations/account_close_requires_every_open_collection_drained
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Close Satellite")
    part = create_part(sku="P-H", list_price_cents=5000, core_charge_cents=900,
                       line_code="BRK")
    stock(satellite["id"], part["id"], 5)
    account = create_account(satellite["id"], tax_id="TX-C013",
                             shop_name="Close Garage",
                             delivery_service_level="SHOP_DELIVERY")

    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(part["id"], 1)],
                                           driver_id="drv-close", route_code="R-C3")
    returned = return_order(delivered["order"]["id"])
    assert returned["status"] == "RETURNED"

    tool = create_tool(tool_sku="T-C2", tool_name="Close Puller",
                       deposit_amount_cents=1500, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    return_desk_stop(account["id"], driver_id="drv-closedesk", route_code="R-C3D")
    loan = get_success_data(api_client.request_loan(
        {"account_id": account["id"], "tool_catalog_id": tool["id"],
         "deposit_amount_cents": 1500}, sales_rep_headers))
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=1500)

    loan_open = api_client.close_account(account["id"], {}, credit_analyst_headers)
    assert loan_open.status_code == 409
    assert loan_open.json()["data"]["error_id"] == "ERR_OPEN_LOANS_EXIST"

    return_loan(loan["id"])
    inspect_loan(loan["id"], return_condition="GOOD")
    close_loan(loan["id"])

    core_open = api_client.close_account(account["id"], {}, credit_analyst_headers)
    assert core_open.status_code == 409
    assert core_open.json()["data"]["error_id"] in (
        "ERR_OPEN_CORE_RETURNS_EXIST", "ERR_RECEIVABLE_BALANCE_OUTSTANDING")

    core_returns = get_success_data(api_client.list_account_core_returns(
        account["id"], sales_rep_headers))
    assert core_returns, "the returned order opened a core return"


def test_the_rejected_close_leaves_the_posture_open(api, credit_analyst_headers,
                                                    sales_rep_headers):
    """PRD §3.8: "The account's posture must not already be `CLOSED`."
    PRD §3.8: "Closure is available from `OPEN`, from `ON_HOLD`, and from
    `CREDIT_SUSPENDED`, and from each of those the account moves to `CLOSED`."

    Design: Corner/validations/account_close_requires_every_open_collection_drained
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Close Satellite Two")
    account = create_account(satellite["id"], tax_id="TX-C013B",
                             shop_name="Close Garage Two",
                             delivery_service_level="SHOP_DELIVERY")
    part = create_part(sku="P-H2", list_price_cents=5000, line_code="BRK")
    write_simple_order(account["id"], part["id"], quantity=1)

    response = api_client.close_account(account["id"], {}, credit_analyst_headers)
    assert response.status_code == 409
    assert response.json()["data"]["error_id"] == "ERR_OPEN_ORDERS_EXIST"
    assert reload_account(account["id"])["account_posture"] == "OPEN"