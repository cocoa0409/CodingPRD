"""Corner design — section: calculations."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_member,
    create_product,
    set_clock,
    setup_operating_store,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_assortment_item,
    create_approved_distributor,
    create_supply_order,
    drive_order_to_received,
)
from test_helpers.test_users import make_licensee_manager_headers


def test_par_replenishment_boundary_equality_no_line():
    """PRD §3.5: "Alternatively, setting `auto_replenish` to true asks the
    system to generate lines from par shortfalls: for each active assortment
    item, the shortfall is `par_level` minus `on_hand`; a shortfall of zero or
    less — and note the boundary, an item exactly at par produces nothing —
    yields no line, while a positive shortfall yields a `quantity_ordered`
    equal to the shortfall rounded up to a whole multiple of the product's
    `case_pack_units`."

    Design: Corner/calculations/par_replenishment_boundary_equality_no_line
    """
    set_clock()
    bundle = setup_operating_store()
    lic_id = bundle["licensee_id"]
    store_id = bundle["store"]["id"]
    product = create_product(unit_cost_cents=500, case_pack_units=4)
    assortment = add_assortment_item(store_id, lic_id, product["id"], par_level=10)
    distributor = create_approved_distributor()
    order = create_supply_order(
        store_id, lic_id, distributor["id"],
        lines=[{"product_item_id": product["id"], "quantity": 10}])
    drive_order_to_received(
        order, lic_id,
        [{"product_item_id": product["id"], "quantity_received": 10}])
    refreshed = validate_success(api_client.get_assortment_item(assortment["id"], ADMIN))
    assert refreshed["on_hand"] == 10
    resp = api_client.create_supply_order(
        store_id,
        {"distributor_id": distributor["id"], "auto_replenish": True, "lines": []},
        make_licensee_manager_headers(lic_id))
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)


def test_par_replenishment_case_pack_rounding():
    """PRD §3.5: "Alternatively, setting `auto_replenish` to true asks the
    system to generate lines from par shortfalls: for each active assortment
    item, the shortfall is `par_level` minus `on_hand`; a shortfall of zero or
    less — and note the boundary, an item exactly at par produces nothing —
    yields no line, while a positive shortfall yields a `quantity_ordered`
    equal to the shortfall rounded up to a whole multiple of the product's
    `case_pack_units`."

    Design: Corner/calculations/par_replenishment_case_pack_rounding
    """
    set_clock()
    bundle = setup_operating_store()
    lic_id = bundle["licensee_id"]
    store_id = bundle["store"]["id"]
    product = create_product(unit_cost_cents=500, case_pack_units=4)
    add_assortment_item(store_id, lic_id, product["id"], par_level=10)
    distributor = create_approved_distributor()
    order = create_supply_order(
        store_id, lic_id, distributor["id"],
        lines=[{"product_item_id": product["id"], "quantity": 9}])
    drive_order_to_received(
        order, lic_id,
        [{"product_item_id": product["id"], "quantity_received": 9}])
    order2 = validate_success(api_client.create_supply_order(
        store_id,
        {"distributor_id": distributor["id"], "auto_replenish": True, "lines": []},
        make_licensee_manager_headers(lic_id)), expected_status=201)
    lines, _meta = validate_paginated(
        api_client.list_supply_order_lines(ADMIN, params={"supply_order_id": order2["id"]}))
    assert len(lines) == 1
    assert lines[0]["quantity_ordered"] == 4  # ceil(1/4)*4
    assert lines[0]["discount_bps"] == 0


def test_loyalty_company_format_earns_double():
    """PRD §3.9: "An `EARN` credits one point per whole 200 cents of purchase
    at a licensed store, but two points per whole 200 cents at a
    company-operated store — fractional remainders never earn."

    Design: Corner/calculations/loyalty_company_format_earns_double
    """
    set_clock()
    bundle = setup_operating_store()
    member_a = create_member()
    member_b = create_member()
    earn_a = validate_success(api_client.create_loyalty_event(
        member_a["id"],
        {"event_type": "EARN", "store_format": "LICENSED",
         "store_id": bundle["store"]["id"], "purchase_cents": 10000},
        make_licensee_manager_headers(bundle["licensee_id"])), expected_status=201)
    earn_b = validate_success(api_client.create_loyalty_event(
        member_b["id"],
        {"event_type": "EARN", "store_format": "COMPANY_OPERATED",
         "purchase_cents": 10000},
        ADMIN), expected_status=201)
    assert earn_a["points"] == 50
    assert earn_b["points"] == 100


def test_loyalty_redeem_over_balance_rejected():
    """PRD §3.9: "A `REDEEM` debits the requested points capped three ways: by
    the member's `points_balance`, and by a redemption ceiling equal to 50
    percent of the purchase at a licensed store versus 75 percent at a
    company-operated store, expressed in points at 100 cents per point with the
    cap floored to a whole point. Exceeding balance or cap is
    `ERR_LOYALTY_INSUFFICIENT_POINTS`."

    Design: Corner/calculations/loyalty_redeem_over_balance_rejected
    """
    set_clock()
    bundle = setup_operating_store()
    lic_headers = make_licensee_manager_headers(bundle["licensee_id"])
    member = create_member()
    validate_success(api_client.create_loyalty_event(
        member["id"],
        {"event_type": "EARN", "store_format": "LICENSED",
         "store_id": bundle["store"]["id"], "purchase_cents": 1000},
        lic_headers), expected_status=201)  # earns 5 points
    resp = api_client.create_loyalty_event(
        member["id"],
        {"event_type": "REDEEM", "store_format": "LICENSED",
         "store_id": bundle["store"]["id"], "purchase_cents": 50000,
         "points": 6},
        lic_headers)
    validate_error(resp, ApiErrorId.ERR_LOYALTY_INSUFFICIENT_POINTS.value)
    member = validate_success(api_client.get_loyalty_member(member["id"], ADMIN))
    assert member["points_balance"] == 5
