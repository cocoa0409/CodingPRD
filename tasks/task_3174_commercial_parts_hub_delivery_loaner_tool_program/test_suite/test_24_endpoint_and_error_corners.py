"""Derived reads, soft-delete visibility, round-trips and window seals."""

from test_helpers import (
    create_replenishment_satellite,
    reload_loan,
    add_fitment,
    advance_order_to_delivered,
    api_client,
    confirm_order,
    create_account,
    create_part,
    create_satellite,
    create_tool,
    create_vehicle,
    get_success_data,
    line_item,
    reload_account,
    reload_inventory,
    reload_order,
    request_loan,
    set_clock,
    stock,
    validate_error,
    validate_paginated,
    write_simple_order,
    checkout_loan,
    return_loan,
)


def test_the_derived_availability_is_recomputed_on_every_read(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.2: "its `available_units` is read-only and always the larger of zero
    and `on_hand_units` minus `reserved_units`, so a shelf can never present a
    negative availability to a shopper."

    Design: Corner/endpoints/inventory_line_list_filters_by_store_and_part
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Inv Satellite")
    part = create_part(sku="P-I", list_price_cents=1000)
    inventory = stock(satellite["id"], part["id"], 10)
    account = create_account(satellite["id"], tax_id="TX-C014",
                             shop_name="Inv Garage",
                             delivery_service_level="SHOP_DELIVERY")
    order = write_simple_order(account["id"], part["id"], quantity=3)
    confirm_order(order["id"], account["id"])

    fetched = reload_inventory(inventory["id"])
    assert fetched["on_hand_units"] == 10
    assert fetched["reserved_units"] == 3
    assert fetched["available_units"] == 7, "derived rather than stored"


def test_the_inventory_list_narrows_by_store_and_by_part(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §4: "listing inventory accepts `store_id` and `part_id`"

    Design: Corner/endpoints/inventory_line_list_filters_by_store_and_part
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Inv Satellite Two")
    part = create_part(sku="P-I2", list_price_cents=1000)
    inventory = stock(satellite["id"], part["id"], 10)

    by_store, meta_store = validate_paginated(api_client.list_inventory_items(
        parts_manager_headers, params={"store_id": satellite["id"]}))
    assert len(by_store) == 1
    assert meta_store["total_count"] == 1

    by_part, _meta = validate_paginated(api_client.list_part_inventory(
        part["id"], parts_manager_headers))
    assert len(by_part) == 1
    assert by_part[0]["id"] == inventory["id"]


def test_the_fitment_lookup_excludes_an_archived_part_by_default(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.2: "it returns the catalogue parts that fit, honouring interchange
    equivalence and following supersession forward to current parts, and excluding
    archived catalogue entries unless archived results were explicitly asked for."

    Design: Corner/endpoints/part_fitment_lookup_excludes_archived_parts
    """
    set_clock("2026-09-01T08:00:00.000Z")
    part_j = create_part(sku="P-J", list_price_cents=1000)
    part_k = create_part(sku="P-K", list_price_cents=1100)
    vehicle = create_vehicle(vin="1HGCM82633A004390")
    add_fitment(part_j["id"])
    add_fitment(part_k["id"])
    get_success_data(api_client.archive_part(part_k["id"], {}, parts_manager_headers))

    results, meta = validate_paginated(api_client.fitment_lookup(
        sales_rep_headers, params={"vehicle_id": vehicle["id"]}))
    assert len(results) == 1
    assert results[0]["id"] == part_j["id"]


def test_the_archived_part_reappears_when_archived_results_are_requested(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.8: "The listing endpoints accept an `include_archived` flag for
    exactly this reason: without it, archived rows are invisible."

    Design: Corner/endpoints/part_fitment_lookup_excludes_archived_parts
    """
    set_clock("2026-09-01T08:00:00.000Z")
    part_j = create_part(sku="P-J2", list_price_cents=1000)
    part_k = create_part(sku="P-K2", list_price_cents=1100)
    vehicle = create_vehicle(vin="1HGCM82633A004391")
    add_fitment(part_j["id"])
    add_fitment(part_k["id"])
    get_success_data(api_client.archive_part(part_k["id"], {}, parts_manager_headers))

    results, _meta = validate_paginated(api_client.fitment_lookup(
        sales_rep_headers,
        params={"vehicle_id": vehicle["id"], "include_archived": True}))
    assert len(results) == 2

    archived = get_success_data(api_client.get_part(part_k["id"],
                                                    parts_manager_headers))
    assert archived["is_archived"] is True

    default_list, _meta2 = validate_paginated(api_client.list_parts(
        parts_manager_headers))
    assert len(default_list) == 1, "the default parts list omits the archived part"


def test_a_single_part_create_returns_one_envelope_object(
        api, parts_manager_headers):
    """PRD §4: "An operation that creates a new stand-alone resource, or adds a new
    distinct resource to a collection, returns `201 Created`"

    Design: Corner/endpoints/bulk_part_creation_returns_one_resource_per_call
    """
    set_clock("2026-09-01T00:00:00.000Z")
    response = api_client.create_part(
        {"sku": "P-L", "description": "Part L", "line_code": "LGT",
         "list_price_cents": 2500, "core_charge_cents": 400,
         "is_hazardous": True, "is_returnable": False}, parts_manager_headers)
    created = response.json()["data"]
    assert response.json()["response_type"] == "object", "not an array"

    fetched = get_success_data(api_client.get_part(created["id"], parts_manager_headers))
    assert fetched["core_charge_cents"] == 400
    assert fetched["is_hazardous"] is True
    assert fetched["is_returnable"] is False


def test_the_registered_part_seeds_its_derived_catalogue_attributes(
        api, parts_manager_headers):
    """PRD §3.2: "Registration seeds the part's derived attributes: `catalog_state`
    becomes `ACTIVE`, `supersession_depth` becomes 0, and `is_archived` becomes
    false."

    Design: Corner/endpoints/bulk_part_creation_returns_one_resource_per_call
    """
    set_clock("2026-09-01T00:00:00.000Z")
    part = create_part(sku="P-L2", list_price_cents=2500, line_code="LGT")

    fetched = get_success_data(api_client.get_part(part["id"], parts_manager_headers))
    assert fetched["catalog_state"] == "ACTIVE"
    assert fetched["supersession_depth"] == 0
    assert fetched["is_archived"] is False
    assert fetched["version"] == 1


def test_a_delivered_order_seals_against_returns_once_the_window_closes(
        api, sales_rep_headers):
    """PRD §3.4: "A `CommercialSalesRep` may return an order only while its
    `status` is `DELIVERED` (otherwise `ERR_ORDER_NOT_DELIVERED`) and only while
    the logical clock is at most the order's `delivered_at` plus the account's
    `credit_terms_days` plus 30 days (otherwise `ERR_RETURN_WINDOW_CLOSED`)."

    Design: Corner/errors/order_return_outside_the_window_returns_return_window_closed
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Win Satellite")
    part = create_part(sku="P-M", list_price_cents=1000)
    stock(satellite["id"], part["id"], 5)
    account = create_account(satellite["id"], tax_id="TX-C015",
                             shop_name="Win Garage",
                             delivery_service_level="SHOP_DELIVERY")
    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(part["id"], 1)],
                                           driver_id="drv-win", route_code="R-WIN")

    set_clock("2026-11-01T08:00:00.000Z")
    response = api_client.return_order(delivered["order"]["id"], {},
                                       sales_rep_headers)
    validate_error(response, "ERR_RETURN_WINDOW_CLOSED", expected_status=409)

    assert reload_order(delivered["order"]["id"])["status"] == "DELIVERED"


def test_the_return_window_boundary_is_the_delivered_due_instant_plus_thirty_days(
        api, sales_rep_headers):
    """PRD §3.4: "Every line on the order must carry a part whose `is_returnable`
    is true"
    PRD §3.4: "return an order only while the logical clock is at most the order's
    `delivered_at` plus the account's `credit_terms_days` plus 30 days"

    Design: Corner/errors/order_return_outside_the_window_returns_return_window_closed
    """
    from datetime import datetime, timedelta, timezone

    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Win Satellite Two")
    part = create_part(sku="P-M2", list_price_cents=1000)
    stock(satellite["id"], part["id"], 5)
    account = create_account(satellite["id"], tax_id="TX-C015B",
                             shop_name="Win Garage Two",
                             delivery_service_level="SHOP_DELIVERY")
    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(part["id"], 1)],
                                           driver_id="drv-win2", route_code="R-WIN2")
    delivered_at = datetime.strptime(delivered["order"]["delivered_at"],
                                     "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)

    # Exactly 60 days after delivery (terms 30 + grace 30) is still inside the window.
    set_clock((delivered_at + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    inside = api_client.return_order(delivered["order"]["id"], {}, sales_rep_headers)
    assert inside.status_code == 200, (
        "at exactly the boundary the return succeeds"
    )


def test_a_returned_loan_cannot_be_returned_a_second_time(api, sales_rep_headers,
                                                          driver_headers):
    """PRD §3.6: "A loan in `IN_USE`, `DUE`, or `OVERDUE` may be returned — any
    other state, including `REQUESTED` or `CHECKED_OUT`, is refused with
    `ERR_LOAN_NOT_OUT`."

    Design: Corner/errors/elapsed_loan_state_returns_loan_not_out_on_return
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Twice Satellite")
    account = create_account(satellite["id"], tax_id="TX-C016",
                             shop_name="Twice Garage", credit_limit_cents=250000)
    tool = create_tool(tool_sku="T-C3", tool_name="Twice Jack",
                       deposit_amount_cents=2000, replacement_part_id=None,
                       replacement_unit_cost_cents=0)
    loan = request_loan(account["id"], tool["id"], deposit_amount_cents=2000)
    checkout_loan(loan["id"], account["id"], accepted_deposit_cents=2000)
    first = return_loan(loan["id"])
    returned_at = first["returned_at"]

    response = api_client.return_loan(loan["id"], {}, driver_headers)
    validate_error(response, "ERR_LOAN_NOT_OUT", expected_status=409)

    after = reload_loan(loan["id"])
    assert after["status"] == "RETURNED"
    assert after["returned_at"] == returned_at, (
        "the second attempt left the instant unchanged"
    )
    assert reload_account(account["id"])["petty_cash_cents"] == 2000, (
        "the repeated call moved no cash"
    )