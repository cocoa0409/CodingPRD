"""Peer-role separation, shared reads, soft delete, the epoch relay and same-request visibility."""

from test_helpers import (
    return_desk_stop,
    create_replenishment_satellite,
    TEST_USERS,
    advance_epoch,
    api_client,
    attach_stop_ok,
    checkout_loan,
    confirm_order,
    create_account,
    create_part,
    create_route,
    create_satellite,
    create_tool,
    get_success_data,
    plan_route,
    reload_account,
    reload_inventory,
    reload_store,
    request_loan,
    return_loan,
    set_clock,
    stock,
    validate_error,
    validate_paginated,
    write_simple_order,
)


def test_the_tool_crib_role_cannot_create_a_commercial_account(
        api, sales_rep_headers, parts_manager_headers, tool_crib_headers):
    """PRD §2.1: "A `CommercialSalesRep` exclusively owns shop-facing writes:
    creating accounts"

    Design: Corner/rbac/tool_crib_attendant_cannot_create_a_commercial_account
    """
    set_clock("2026-09-01T00:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Peer Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))

    denied = api_client.create_account(
        {"shop_name": "Denied Garage", "tax_id": "TX-C017",
         "billing_address": "1 Denied St", "home_store_id": store["id"],
         "credit_limit_cents": 250000, "credit_terms_days": 30,
         "delivery_service_level": "SHOP_DELIVERY"}, tool_crib_headers)
    validate_error(denied, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_the_sales_rep_can_create_the_same_account(api, sales_rep_headers,
                                                   parts_manager_headers):
    """PRD §2.1: "A `CommercialSalesRep` exclusively owns shop-facing writes:
    creating accounts, writing and progressing orders"

    Design: Corner/rbac/tool_crib_attendant_cannot_create_a_commercial_account
    """
    set_clock("2026-09-01T00:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Peer Satellite Two", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))

    response = api_client.create_account(
        {"shop_name": "Allowed Garage", "tax_id": "TX-C017B",
         "billing_address": "2 Allowed St", "home_store_id": store["id"],
         "credit_limit_cents": 250000, "credit_terms_days": 30,
         "delivery_service_level": "SHOP_DELIVERY"}, sales_rep_headers)
    assert response.status_code == 201, "the operation itself is valid for this role"


def test_the_sales_rep_cannot_inspect_a_returned_loan(api, sales_rep_headers,
                                                      driver_headers,
                                                      tool_crib_headers):
    """PRD §2.1: "A `ToolCribAttendant` owns the crib and the core bench: the tool
    catalogue, tool fitments, wear adjustments and resets, tool inspection, loan
    closure and forfeiture"

    Design: Corner/rbac/sales_rep_cannot_inspect_or_close_a_loan
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Peer2 Satellite")
    account = create_account(satellite["id"], tax_id="TX-C018",
                             shop_name="Peer2 Garage", credit_limit_cents=250000)
    tool = create_tool(tool_sku="T-C4", tool_name="Peer Stand",
                       deposit_amount_cents=2500, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=2500)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=2500)
    return_loan(loan["id"])

    denied = api_client.inspect_loan(loan["id"], {"return_condition": "GOOD"},
                                     sales_rep_headers)
    validate_error(denied, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_the_crib_role_can_inspect_the_same_loan_and_the_split_is_narrow(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §2.1: "A `CommercialSalesRep` exclusively owns shop-facing writes:
    creating accounts, writing and progressing orders, opening core returns,
    recording warranties, assigning representative coverage, registering vehicles
    and reps, and requesting loaner tools."
    PRD §2.1: "A `DeliveryDriver` owns the road"

    Design: Corner/rbac/sales_rep_cannot_inspect_or_close_a_loan
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Peer2 Satellite Two")
    account = create_account(satellite["id"], tax_id="TX-C018B",
                             shop_name="Peer2 Garage Two", credit_limit_cents=250000)
    tool = create_tool(tool_sku="T-C4B", tool_name="Peer Stand Two",
                       deposit_amount_cents=2500, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=2500)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=2500)
    # PRD 3.6: inspection requires "A `RETURN_DESK` `RouteStop` for the owning
    # account ... on a `ServiceRoute` that is not `CANCELLED`", so the crib needs
    # a return desk before it can judge the tool at all.
    return_desk_stop(account["id"], driver_id="drv-peer2b", route_code="R-P2B")
    return_loan(loan["id"])

    allowed = api_client.inspect_loan(loan["id"], {"return_condition": "GOOD"},
                                      tool_crib_headers)
    assert allowed.status_code == 200, (
        "the sales rep's own loan request and the driver's own return both succeeded"
    )
    assert allowed.json()["data"]["status"] == "INSPECTED"


def test_the_platform_clock_role_cannot_dispatch_a_route(
        api, credit_analyst_headers, route_dispatcher_headers):
    """PRD §2.1: "`PlatformAdmin` operates only the system clock and the
    business-day epoch and is not a commercial actor."

    Design: Corner/rbac/platform_admin_cannot_dispatch_a_route
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Admin Satellite")
    account = create_account(satellite["id"], tax_id="TX-C019",
                             shop_name="Admin Garage", credit_limit_cents=250000)
    route = create_route(driver_id="drv-admin", route_code="R-C2")
    attach_stop_ok(route["id"], account["id"], order_ids=[],
                   delivery_window_start="2026-09-02T13:30:00.000Z",
                   delivery_window_end="2026-09-02T14:30:00.000Z")
    plan_route(route["id"])

    denied = api_client.dispatch_route(route["id"], {},
                                       TEST_USERS["platform_admin_headers"])
    validate_error(denied, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)

    assert get_success_data(api_client.get_route(route["id"],
                                                 route_dispatcher_headers))["status"] == "PLANNED"


def test_the_dispatcher_can_dispatch_the_same_route(
        api, route_dispatcher_headers):
    """PRD §2.1: "A `RouteDispatcher` owns route construction and stop sequencing."

    Design: Corner/rbac/platform_admin_cannot_dispatch_a_route
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Admin Satellite Two")
    account = create_account(satellite["id"], tax_id="TX-C019B",
                             shop_name="Admin Garage Two", credit_limit_cents=250000)
    route = create_route(driver_id="drv-admin2", route_code="R-C2B")
    attach_stop_ok(route["id"], account["id"], order_ids=[],
                   delivery_window_start="2026-09-02T13:30:00.000Z",
                   delivery_window_end="2026-09-02T14:30:00.000Z")
    plan_route(route["id"])

    allowed = api_client.dispatch_route(route["id"], {}, route_dispatcher_headers)
    assert allowed.status_code == 200
    assert allowed.json()["data"]["status"] == "DISPATCHED"


def test_every_listed_role_can_read_the_account_collection(
        api, sales_rep_headers, credit_analyst_headers, driver_headers,
        parts_manager_headers):
    """PRD §2.1: "`Any` is read-only and shares all GET access with every
    authenticated role."
    PRD §2.1: "Every request must carry two headers."

    Design: Corner/rbac/every_authenticated_role_can_read_the_account_collection
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Share Satellite")
    account = create_account(satellite["id"], tax_id="TX-C020",
                             shop_name="Share Garage", credit_limit_cents=250000)

    analyst_data, analyst_meta = validate_paginated(api_client.list_accounts(
        credit_analyst_headers, params={"limit": 10, "offset": 0}))
    driver_data, driver_meta = validate_paginated(api_client.list_accounts(
        driver_headers, params={"limit": 10, "offset": 0}))
    manager_data, manager_meta = validate_paginated(api_client.list_accounts(
        parts_manager_headers, params={"limit": 10, "offset": 0}))

    assert analyst_meta["total_count"] == 1
    assert driver_meta["total_count"] == 1
    assert manager_meta["total_count"] == 1
    assert driver_data[0]["id"] == analyst_data[0]["id"] == account["id"]
    assert manager_data[0]["id"] == account["id"]


def test_an_archived_store_leaves_the_default_list_but_stays_addressable(
        api, parts_manager_headers):
    """PRD §3.8: "Archiving an account, a part, or a store sets its `is_archived`
    flag so that default list reads stop returning it while it remains addressable
    by identifier"

    Design: Corner/cross_cutting_complexity_layers/archive_soft_delete_excludes_from_lists_and_keeps_reads_working
    """
    set_clock("2026-09-01T00:00:00.000Z")
    first = create_replenishment_satellite(store_code="S100", name="Arch One")
    second = create_replenishment_satellite(store_code="S200", name="Arch Two",
                              delivery_radius_miles=6.0)
    get_success_data(api_client.archive_store(second["id"], {}, parts_manager_headers))

    default_list, _meta = validate_paginated(api_client.list_stores(
        parts_manager_headers, params={"limit": 10, "offset": 0}))
    listed_codes = [s["store_code"] for s in default_list]
    assert "S100" in listed_codes, "the live store is listed by default"
    assert "S200" not in listed_codes, (
        "the archived store is hidden from the default list read"
    )

    archived_list, _meta2 = validate_paginated(api_client.list_stores(
        parts_manager_headers, params={"include_archived": True}))
    archived_codes = [s["store_code"] for s in archived_list]
    assert "S100" in archived_codes and "S200" in archived_codes

    fetched = get_success_data(api_client.get_store(second["id"], parts_manager_headers))
    assert fetched["is_archived"] is True


def test_the_archive_mutation_advances_the_store_version(api, parts_manager_headers):
    """PRD §2.4: "`version` is an integer that starts at its creation value and
    increments by one on every modification."

    Design: Corner/cross_cutting_complexity_layers/archive_soft_delete_excludes_from_lists_and_keeps_reads_working
    """
    set_clock("2026-09-01T00:00:00.000Z")
    store = create_replenishment_satellite(store_code="S300", name="Arch Three")
    before = store["version"]

    archived = get_success_data(api_client.archive_store(store["id"], {},
                                                         parts_manager_headers))
    assert archived["version"] > before, "the archive mutation advanced the version"


def test_the_epoch_relay_resets_only_stores_whose_epoch_is_a_day_old(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.9: "advances the epoch for every store whose `capacity_epoch_at` is at
    least 24 hours behind that instant: those stores have their
    `committed_units_today` reset to zero and their `capacity_epoch_at` stamped to
    the requested instant. Stores whose `capacity_epoch_at` is already within 24
    hours of the requested instant are left untouched."

    Design: Corner/cross_cutting_complexity_layers/epoch_advance_resets_only_aged_stores
    """
    set_clock("2026-09-02T12:00:00.000Z")
    first = create_replenishment_satellite(store_code="S100", name="Epoch One")
    second = create_replenishment_satellite(store_code="S200", name="Epoch Two",
                              delivery_radius_miles=6.0)
    part = create_part(sku="P-N", list_price_cents=1000)
    stock(first["id"], part["id"], 10)
    account = create_account(first["id"], tax_id="TX-C021",
                             shop_name="Epoch Garage",
                             delivery_service_level="SHOP_DELIVERY")
    order = write_simple_order(account["id"], part["id"], quantity=3)
    confirm_order(order["id"], account["id"])

    result = advance_epoch("2026-09-03T00:00:00.000Z")

    assert reload_store(first["id"])["committed_units_today"] == 3, (
        "the advance is only 12 hours after the creation epoch, so neither store resets"
    )
    assert reload_store(second["id"])["committed_units_today"] == 0
    assert result is not None


def test_a_further_epoch_advance_past_a_full_day_clears_the_committed_count(
        api, sales_rep_headers):
    """PRD §3.9: "The relay reports which stores it advanced and the total unit
    quantity it reset."

    Design: Corner/cross_cutting_complexity_layers/epoch_advance_resets_only_aged_stores
    """
    set_clock("2026-09-02T12:00:00.000Z")
    first = create_replenishment_satellite(store_code="S100", name="Epoch One B")
    part = create_part(sku="P-N2", list_price_cents=1000)
    stock(first["id"], part["id"], 10)
    account = create_account(first["id"], tax_id="TX-C021B",
                             shop_name="Epoch Garage B",
                             delivery_service_level="SHOP_DELIVERY")
    order = write_simple_order(account["id"], part["id"], quantity=3)
    confirm_order(order["id"], account["id"])

    advance_epoch("2026-09-04T00:00:00.000Z")

    refreshed = reload_store(first["id"])
    assert refreshed["committed_units_today"] == 0
    assert refreshed["capacity_epoch_at"] == "2026-09-04T00:00:00.000Z"


def test_a_stale_account_version_is_rejected_and_reading_again_fixes_it(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §2.9: "Creating a parts order against an account requires
    `expected_account_version`, the client's last-observed `version` of that
    `CommercialAccount`. If the account's current `version` no longer matches, the
    create is refused with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/order_create_occ_rejects_a_stale_account_version
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Occ Satellite")
    part = create_part(sku="P-O", list_price_cents=1000)
    stock(satellite["id"], part["id"], 20)
    account = create_account(satellite["id"], tax_id="TX-C022",
                             shop_name="Occ Garage")

    stale_version = account["version"]
    get_success_data(api_client.create_order(
        {"account_id": account["id"],
         "line_items": [{"part_id": part["id"], "quantity": 1}],
         "expected_account_version": stale_version}, sales_rep_headers))

    response = api_client.create_order(
        {"account_id": account["id"],
         "line_items": [{"part_id": part["id"], "quantity": 1}],
         "expected_account_version": stale_version}, sales_rep_headers)
    validate_error(response, "ERR_STALE_ACCOUNT_VERSION", expected_status=412)

    fresh = reload_account(account["id"])["version"]
    retried = api_client.create_order(
        {"account_id": account["id"],
         "line_items": [{"part_id": part["id"], "quantity": 1}],
         "expected_account_version": fresh}, sales_rep_headers)
    assert retried.status_code == 201, "the retry carrying the freshly read version succeeds"


def test_the_order_sequence_counts_only_the_two_live_orders(
        api, sales_rep_headers):
    """PRD §3.3: "The account's `order_sequence` counter is read and incremented,
    and the order's `member_sequence` is set to the value the counter held before
    the increment"

    Design: Corner/cross_cutting_complexity_layers/order_create_occ_rejects_a_stale_account_version
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Occ Satellite Two")
    part = create_part(sku="P-O2", list_price_cents=1000)
    stock(satellite["id"], part["id"], 20)
    account = create_account(satellite["id"], tax_id="TX-C022B",
                             shop_name="Occ Garage Two")
    first_version = account["version"]

    get_success_data(api_client.create_order(
        {"account_id": account["id"],
         "line_items": [{"part_id": part["id"], "quantity": 1}],
         "expected_account_version": first_version}, sales_rep_headers))
    api_client.create_order(
        {"account_id": account["id"],
         "line_items": [{"part_id": part["id"], "quantity": 1}],
         "expected_account_version": first_version}, sales_rep_headers)
    get_success_data(api_client.create_order(
        {"account_id": account["id"],
         "line_items": [{"part_id": part["id"], "quantity": 1}],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers))

    orders, meta = validate_paginated(api_client.list_account_orders(
        account["id"], sales_rep_headers))
    assert meta["total_count"] == 2, "only the two accepted creates produced orders"
    assert sorted(o["member_sequence"] for o in orders) == [1, 2]


def test_a_stale_version_on_the_loan_checkout_is_rejected(
        api, sales_rep_headers):
    """PRD §2.9: "Checking out a loaner tool against an account carries the same
    `expected_account_version` requirement and the same rejection."

    Design: Corner/cross_cutting_complexity_layers/loan_checkout_occ_rejects_a_stale_account_version
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Occ2 Satellite")
    part = create_part(sku="P-P", list_price_cents=1000)
    stock(satellite["id"], part["id"], 20)
    account = create_account(satellite["id"], tax_id="TX-C023",
                             shop_name="Occ2 Garage")
    stale_version = account["version"]
    tool = create_tool(tool_sku="T-C5", tool_name="Occ Stand",
                       deposit_amount_cents=2000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=2000)

    order = write_simple_order(account["id"], part["id"], quantity=1)
    confirm_order(order["id"], account["id"])

    response = api_client.checkout_loan(
        loan["id"],
        {"accepted_deposit_cents": 2000,
         "expected_account_version": stale_version}, sales_rep_headers)
    validate_error(response, "ERR_STALE_ACCOUNT_VERSION", expected_status=412)


def test_the_checkout_succeeds_once_the_account_version_is_re_read(
        api, sales_rep_headers):
    """PRD §3.6: "Checkout also carries `expected_account_version`, the account's
    `version` as last observed; a mismatch is refused with
    `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/loan_checkout_occ_rejects_a_stale_account_version
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Occ2 Satellite Two")
    account = create_account(satellite["id"], tax_id="TX-C023B",
                             shop_name="Occ2 Garage Two")
    tool = create_tool(tool_sku="T-C5B", tool_name="Occ Stand Two",
                       deposit_amount_cents=2000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=2000)

    checked_out = get_success_data(api_client.checkout_loan(
        loan["id"],
        {"accepted_deposit_cents": 2000,
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers))

    assert checked_out["deposit_state"] == "HELD"
    refreshed = reload_account(account["id"])
    assert refreshed["petty_cash_cents"] == 2000
    assert refreshed["deposit_liability_cents"] == 2000


def test_the_confirming_response_already_carries_the_recomputed_figures(
        api, sales_rep_headers, driver_headers):
    """PRD §3.3: "The account's `credit_exposure_cents` is recomputed and its
    `order_sequence` advances by one."

    Design: Corner/consistency_model/same_request_visibility_of_exposure_and_reservations
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Imm Satellite")
    part = create_part(sku="P-Q", list_price_cents=1000)
    inventory = stock(satellite["id"], part["id"], 10)
    account = create_account(satellite["id"], tax_id="TX-C024",
                             shop_name="Imm Garage")

    order = write_simple_order(account["id"], part["id"], quantity=2)
    confirmed = confirm_order(order["id"], account["id"])

    assert confirmed["parts_subtotal_cents"] is not None, (
        "the confirm response itself reports the recomputed subtotal"
    )
    assert reload_inventory(inventory["id"])["reserved_units"] == 2
    assert reload_inventory(inventory["id"])["available_units"] == 8
    assert reload_account(account["id"])["credit_exposure_cents"] == \
        confirmed["parts_subtotal_cents"]


def test_the_void_path_shows_the_same_immediate_visibility(
        api, sales_rep_headers):
    """PRD §2.5: "Only after the whole cascade completes is the account's
    `credit_exposure_cents` recomputed."
    PRD §3.3: "Voiding a `DRAFT` order simply moves it to `VOID` and recomputes
    the account's `credit_exposure_cents`."

    Design: Corner/consistency_model/same_request_visibility_of_exposure_and_reservations
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Imm Satellite Two")
    part = create_part(sku="P-Q2", list_price_cents=1000)
    inventory = stock(satellite["id"], part["id"], 10)
    account = create_account(satellite["id"], tax_id="TX-C024B",
                             shop_name="Imm Garage Two")
    order = write_simple_order(account["id"], part["id"], quantity=2)
    confirm_order(order["id"], account["id"])

    voided = get_success_data(api_client.void_order(order["id"], {},
                                                    sales_rep_headers))

    assert reload_inventory(inventory["id"])["reserved_units"] == 0
    assert reload_account(account["id"])["credit_exposure_cents"] == 0
    assert voided["status"] == "VOID"