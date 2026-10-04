"""Constant application: the delivery fee, the entitled core credit and the frozen base."""

from test_helpers import (
    create_replenishment_satellite,
    advance_order_to,
    advance_order_to_delivered,
    api_client,
    confirm_order,
    create_account,
    create_hub,
    create_part,
    create_satellite,
    get_success_data,
    line_item,
    reload_account,
    reload_order,
    set_clock,
    stock,
    transit_core_return,
    open_core_return,
    validate_error,
    write_simple_order,
)


def test_the_free_delivery_clause_holds_for_hub_daily_and_fails_for_a_near_miss(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §2.7: "the entire basket takes a single band's rate"
    PRD §3.4: "Delivery is free when the order's `fulfillment_route` is exactly
    `STORE`, or when the route is exactly `HUB` and the account's
    `delivery_service_level` is exactly `HUB_DAILY`."

    Design: Corner/calculations/delivery_fee_constants_and_free_route_equality
    """
    set_clock("2026-09-01T08:00:00.000Z")
    hub = create_hub(store_code="S200", name="Fee Hub", delivery_radius_miles=40.0,
                     promise_time_minutes=90)
    satellite = create_satellite(hub_store_id=hub["id"], store_code="S100",
                                 name="Fee Satellite")
    part = create_part(sku="P-D", list_price_cents=1673)
    stock(hub["id"], part["id"], 20)
    hub_daily = create_account(satellite["id"], tax_id="TX-C008",
                               shop_name="Fee Garage D",
                               delivery_service_level="HUB_DAILY")
    hub_short = create_account(satellite["id"], tax_id="TX-C009",
                               shop_name="Fee Garage S",
                               delivery_service_level="DELIVERY_DESK")

    free = write_simple_order(hub_daily["id"], part["id"], quantity=2)
    charged = write_simple_order(hub_short["id"], part["id"], quantity=2)

    assert free["fulfillment_route"] == "HUB"
    assert free["delivery_fee_cents"] == 0
    assert charged["fulfillment_route"] == "HUB"
    assert charged["delivery_fee_cents"] == 795
    assert free["parts_subtotal_cents"] == charged["parts_subtotal_cents"] == 3346, (
        "the only difference between the two orders is the service-level equality test"
    )


def test_the_point_of_sale_fee_survives_confirmation_and_allocation(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.4: "The fee is not recomputed at allocation and not recomputed at
    delivery, so the point-of-sale figure is what stands unless the source itself
    moved."

    Design: Corner/calculations/delivery_fee_constants_and_free_route_equality
    """
    set_clock("2026-09-01T08:00:00.000Z")
    hub = create_hub(store_code="S201", name="Fee Hub Two", delivery_radius_miles=40.0,
                     promise_time_minutes=90)
    satellite = create_satellite(hub_store_id=hub["id"], store_code="S100",
                                 name="Fee Satellite Two")
    part = create_part(sku="P-D2", list_price_cents=1673)
    stock(hub["id"], part["id"], 20)
    account = create_account(satellite["id"], tax_id="TX-C008B",
                             shop_name="Fee Garage Two",
                             delivery_service_level="HUB_DAILY")

    order = write_simple_order(account["id"], part["id"], quantity=2)
    assert order["delivery_fee_cents"] == 0

    confirmed = confirm_order(order["id"], account["id"])
    assert confirmed["delivery_fee_cents"] == 0

    allocated = advance_order_to(order["id"], account["id"], "ALLOCATED")
    assert allocated["delivery_fee_cents"] == 0


def test_the_free_delivery_clause_holds_for_a_store_route(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.4: "Delivery is free when the order's `fulfillment_route` is exactly
    `STORE`"

    Design: Corner/calculations/delivery_fee_constants_and_free_route_equality
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Fee Satellite Three")
    part = create_part(sku="P-D3", list_price_cents=1673)
    stock(satellite["id"], part["id"], 20)
    account = create_account(satellite["id"], tax_id="TX-C008C",
                             shop_name="Fee Garage Three",
                             delivery_service_level="SHOP_DELIVERY")

    order = write_simple_order(account["id"], part["id"], quantity=2)

    assert order["fulfillment_route"] == "STORE"
    assert order["delivery_fee_cents"] == 0


def test_the_core_subtotal_counts_every_returned_core(api, sales_rep_headers,
                                                      parts_manager_headers):
    """PRD §3.7: "It starts in `INITIATED` with its `core_subtotal_cents` computed
    as the sum over its lines of the `core_charge_cents` of the line's part
    multiplied by the line quantity."

    Design: Corner/calculations/ordered_quantity_credit_excludes_unordered_quantity
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Quant Satellite")
    part = create_part(sku="P-CORE", list_price_cents=5000, core_charge_cents=750,
                       line_code="BRK")
    stock(satellite["id"], part["id"], 10)
    account = create_account(satellite["id"], tax_id="TX-C010",
                             shop_name="Quant Garage",
                             delivery_service_level="SHOP_DELIVERY")
    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(part["id"], 2)],
                                           driver_id="drv-quant",
                                           route_code="R-QUANT")

    core_return = open_core_return(delivered["order"]["id"],
                                   [line_item(part["id"], 6)])

    assert core_return["core_subtotal_cents"] == 4500, (
        "six returned cores at 750 cents each"
    )


def test_the_entitled_figure_differs_from_what_the_order_actually_bought(
        api, sales_rep_headers):
    """PRD §3.7: "`core_subtotal_cents` is the gross core value of the returned
    lines and is not capped"
    PRD §3.7: "Unordered credit is never allowed, so a core line for a part the
    order never contained contributes nothing."

    Design: Corner/calculations/ordered_quantity_credit_excludes_unordered_quantity
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Quant Satellite Two")
    part = create_part(sku="P-CORE2", list_price_cents=5000, core_charge_cents=750,
                       line_code="BRK")
    stock(satellite["id"], part["id"], 10)
    account = create_account(satellite["id"], tax_id="TX-C010B",
                             shop_name="Quant Garage Two",
                             delivery_service_level="SHOP_DELIVERY")
    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(part["id"], 2)],
                                           driver_id="drv-quant2",
                                           route_code="R-QUANT2")
    order = delivered["order"]
    assert order["core_charge_total_cents"] == 1500, (
        "the order only bought two cores"
    )

    core_return = open_core_return(order["id"], [line_item(part["id"], 6)])
    assert core_return["core_subtotal_cents"] != order["core_charge_total_cents"], (
        "the entitled figure and the ordered figure differ"
    )


def test_inspection_rejects_a_core_line_beyond_the_purchased_quantity(
        api, sales_rep_headers, driver_headers, tool_crib_headers):
    """PRD §3.7: "for every line the line quantity must not exceed the quantity of
    that same part on the referenced order — a line claiming more than was bought
    is refused with `ERR_CORE_QUANTITY_EXCEEDS_PURCHASE` (HTTP 409)."

    Design: Corner/calculations/ordered_quantity_credit_excludes_unordered_quantity
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Quant Satellite Three")
    part = create_part(sku="P-CORE3", list_price_cents=5000, core_charge_cents=750,
                       line_code="BRK")
    stock(satellite["id"], part["id"], 10)
    account = create_account(satellite["id"], tax_id="TX-C010C",
                             shop_name="Quant Garage Three",
                             delivery_service_level="SHOP_DELIVERY")
    delivered = advance_order_to_delivered(account["id"],
                                           [line_item(part["id"], 2)],
                                           driver_id="drv-quant3",
                                           route_code="R-QUANT3")
    core_return = open_core_return(delivered["order"]["id"],
                                   [line_item(part["id"], 6)])
    transit_core_return(core_return["id"])

    response = api_client.inspect_core_return(core_return["id"], {},
                                              tool_crib_headers)
    validate_error(response, "ERR_CORE_QUANTITY_EXCEEDS_PURCHASE", expected_status=409)


def test_a_line_added_after_creation_leaves_the_satisfaction_score_alone(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.3: "Because `order_base_cents` is frozen at creation, adding a line to
    the order afterwards changes nothing in this score — the recompute reads the
    stored base, not a fresh basket."

    Design: Corner/calculations/satisfaction_constant_is_frozen_after_creation
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Sat Satellite")
    part_e = create_part(sku="P-E", list_price_cents=8000)
    part_f = create_part(sku="P-F", list_price_cents=9000)
    stock(satellite["id"], part_e["id"], 10)
    stock(satellite["id"], part_f["id"], 10)
    account = create_account(satellite["id"], tax_id="TX-C011",
                             shop_name="Sat Garage",
                             delivery_service_level="SHOP_DELIVERY")

    order = write_simple_order(account["id"], part_e["id"], quantity=1)
    before = reload_order(order["id"])

    updated = get_success_data(api_client.update_order(
        order["id"],
        {"line_items": [line_item(part_e["id"], 1), line_item(part_f["id"], 1)],
         "expected_order_version": before["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers))

    assert updated["parts_subtotal_cents"] == 17000, (
        "the basket subtotal is recomputed from the new lines"
    )
    assert updated["satisfaction_cents"] == before["satisfaction_cents"], (
        "the score reads the stored creation-time base, so a later line changes nothing"
    )


def test_the_frozen_base_reflects_only_the_creation_time_basket(
        api, sales_rep_headers):
    """PRD §3.3: "The order's `order_base_cents` is computed once, at creation, from
    the creation-time line basket and then stored: it is the sum over those lines
    of the resolved list amount multiplied by the quantity, with the total scaled
    by a base fraction of 0.015, rounded half-up to the cent."

    Design: Corner/calculations/satisfaction_constant_is_frozen_after_creation
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Sat Satellite Two")
    part_e = create_part(sku="P-E2", list_price_cents=8000)
    part_f = create_part(sku="P-F2", list_price_cents=9000)
    stock(satellite["id"], part_e["id"], 10)
    stock(satellite["id"], part_f["id"], 10)
    account = create_account(satellite["id"], tax_id="TX-C011B",
                             shop_name="Sat Garage Two",
                             delivery_service_level="SHOP_DELIVERY")

    order = write_simple_order(account["id"], part_e["id"], quantity=1)
    created = reload_order(order["id"])
    updated = get_success_data(api_client.update_order(
        order["id"],
        {"line_items": [line_item(part_e["id"], 1), line_item(part_f["id"], 1)],
         "expected_order_version": created["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers))

    assert updated["parts_subtotal_cents"] == 8000 + 9000, (
        "the subtotal is the sum over lines of the line's unit price times its "
        "quantity, and neither line is discounted at BRONZE"
    )
    assert updated["satisfaction_cents"] == created["satisfaction_cents"], (
        "the score is derived from the frozen base, not from the doubled basket"
    )
    assert updated["pricing_band"] == "BRONZE"
    assert updated["tier_discount_cents"] == 0, "neither line was discounted"