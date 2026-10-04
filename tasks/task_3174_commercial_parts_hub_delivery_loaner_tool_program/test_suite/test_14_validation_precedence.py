"""Which rule is reported when more than one would fire."""

from test_helpers import (
    create_replenishment_satellite,
    add_fitment,
    advance_order_to,
    api_client,
    confirm_order,
    create_account,
    create_part,
    create_satellite,
    create_vehicle,
    line_item,
    reload_account,
    reload_inventory,
    reload_order,
    set_clock,
    stock,
    validate_error,
    write_order,
    write_simple_order,
)


def test_a_state_mismatch_outranks_the_hazardous_delivery_safety_rule(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §2.12: "State preconditions follow. The target resource must be in the
    state its transition starts from, and a state mismatch is the error the
    caller sees even when a later business rule would also have failed."
    PRD §2.12: "Business rules then apply in this order. A hazardous part on a
    `DELIVERY_DESK` order is rejected before fitment is considered."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_hazardous_delivery_safety
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Hazard Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    hazardous = create_part(sku="HAZ-1", list_price_cents=900, line_code="CHM",
                            is_hazardous=True)
    vehicle = create_vehicle(vin="1HGCM82633A004361")
    add_fitment(plug["id"])
    stock(satellite["id"], plug["id"], 10)
    stock(satellite["id"], hazardous["id"], 10)
    account = create_account(satellite["id"], delivery_service_level="DELIVERY_DESK")

    picking = write_simple_order(account["id"], plug["id"], quantity=1,
                                 vehicle_id=vehicle["id"])
    picking = advance_order_to(confirm_order(picking["id"], account["id"])["id"],
                               account["id"], "PICKING")

    response = api_client.update_order(
        picking["id"],
        {"line_items": [line_item(hazardous["id"], 2)],
         "expected_order_version": reload_order(picking["id"])["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_ORDER_NOT_DRAFT", expected_status=409)


def test_the_hazardous_delivery_safety_rule_is_live_and_reachable(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.3: "A line whose part has `is_hazardous` true may not be added to an
    order whose owning account has a `delivery_service_level` of
    `DELIVERY_DESK`; such a line is refused with
    `ERR_HAZARDOUS_PART_NOT_DELIVERABLE` (HTTP 400)."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_hazardous_delivery_safety
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Hazard Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    hazardous = create_part(sku="HAZ-1", list_price_cents=900, line_code="CHM",
                            is_hazardous=True)
    vehicle = create_vehicle(vin="1HGCM82633A004362")
    add_fitment(plug["id"])
    stock(satellite["id"], plug["id"], 10)
    stock(satellite["id"], hazardous["id"], 10)
    account = create_account(satellite["id"], delivery_service_level="DELIVERY_DESK")

    draft = write_simple_order(account["id"], plug["id"], quantity=1,
                               vehicle_id=vehicle["id"])
    response = api_client.update_order(
        draft["id"],
        {"line_items": [line_item(hazardous["id"], 2)],
         "expected_order_version": reload_order(draft["id"])["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_HAZARDOUS_PART_NOT_DELIVERABLE", expected_status=400)


def test_each_rejected_order_keeps_its_own_state_and_reservations(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.3: "This guard is evaluated on both the line-mutation write and the
    confirmation write."
    PRD §3.3: "The order's `status` must be `DRAFT`, or the request is refused
    with `ERR_ORDER_NOT_DRAFT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_hazardous_delivery_safety
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Hazard Satellite")
    plug = create_part(sku="PLUG-100", list_price_cents=1673)
    hazardous = create_part(sku="HAZ-1", list_price_cents=900, line_code="CHM",
                            is_hazardous=True)
    vehicle = create_vehicle(vin="1HGCM82633A004363")
    add_fitment(plug["id"])
    inventory = stock(satellite["id"], plug["id"], 10)
    stock(satellite["id"], hazardous["id"], 10)
    account = create_account(satellite["id"], delivery_service_level="DELIVERY_DESK")

    picking = write_simple_order(account["id"], plug["id"], quantity=1,
                                 vehicle_id=vehicle["id"])
    picking = advance_order_to(confirm_order(picking["id"], account["id"])["id"],
                               account["id"], "PICKING")
    draft = write_simple_order(account["id"], plug["id"], quantity=1,
                               vehicle_id=vehicle["id"])
    reserved_before = reload_inventory(inventory["id"])["reserved_units"]

    api_client.update_order(
        picking["id"],
        {"line_items": [line_item(hazardous["id"], 2)],
         "expected_order_version": reload_order(picking["id"])["version"]},
        sales_rep_headers)
    api_client.update_order(
        draft["id"],
        {"line_items": [line_item(hazardous["id"], 2)],
         "expected_order_version": reload_order(draft["id"])["version"]},
        sales_rep_headers)

    assert reload_order(picking["id"])["status"] == "PICKING"
    assert reload_order(draft["id"])["status"] == "DRAFT"
    assert reload_inventory(inventory["id"])["reserved_units"] == reserved_before, (
        "no reservation moved for either order"
    )


def test_a_referential_fitment_failure_outranks_the_stock_constraint(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §2.12: "Order-line fitment matching precedes supersession-chain
    validity."
    PRD §2.12: "The archive guard precedes stock availability."

    Design: Difficulty/priority_pair_validation_conflict/referential_fitment_outranks_constraint_stock
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Fit Satellite")
    hubassy = create_part(sku="HUBASSY-9", list_price_cents=3005, line_code="DRV")
    notfit = create_part(sku="NOTFIT-1", list_price_cents=199, line_code="ACC")
    vehicle = create_vehicle(vin="1HGCM82633A004362")
    add_fitment(hubassy["id"])
    stock(satellite["id"], notfit["id"], 5)
    account = create_account(satellite["id"])

    order = write_order(
        account["id"],
        [line_item(hubassy["id"], 2), line_item(notfit["id"], 2)],
        vehicle_id=vehicle["id"])

    response = api_client.confirm_order(
        order["id"],
        {"expected_order_version": reload_order(order["id"])["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_FITMENT_MISMATCH", expected_status=409)


def test_the_stock_constraint_is_live_for_a_fitting_but_unstocked_line(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.3: "Every line must be reservable: the selected source must hold an
    `available_units` figure at least as large as the line quantity for the
    resolved current part, or the request is refused with
    `ERR_INSUFFICIENT_STOCK` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_fitment_outranks_constraint_stock
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Fit Satellite")
    hubassy = create_part(sku="HUBASSY-9", list_price_cents=3005, line_code="DRV")
    vehicle = create_vehicle(vin="1HGCM82633A004362")
    add_fitment(hubassy["id"])
    account = create_account(satellite["id"])

    order = write_order(account["id"], [line_item(hubassy["id"], 2)],
                        vehicle_id=vehicle["id"])
    response = api_client.confirm_order(
        order["id"],
        {"expected_order_version": reload_order(order["id"])["version"],
         "expected_account_version": reload_account(account["id"])["version"]},
        sales_rep_headers)
    validate_error(response, "ERR_INSUFFICIENT_STOCK", expected_status=409)


def test_neither_rejected_confirmation_reserves_anything(api, sales_rep_headers,
                                                         parts_manager_headers):
    """PRD §3.3: "Every line must be reservable"
    PRD §3.3: "The order's `status` must be `DRAFT`, or the request is refused
    with `ERR_ORDER_NOT_DRAFT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_fitment_outranks_constraint_stock
    """
    set_clock("2026-09-01T08:00:00.000Z")
    satellite = create_replenishment_satellite(store_code="S100", name="Fit Satellite")
    hubassy = create_part(sku="HUBASSY-9", list_price_cents=3005, line_code="DRV")
    notfit = create_part(sku="NOTFIT-1", list_price_cents=199, line_code="ACC")
    vehicle = create_vehicle(vin="1HGCM82633A004363")
    add_fitment(hubassy["id"])
    notfit_inv = stock(satellite["id"], notfit["id"], 5)
    account = create_account(satellite["id"])

    mixed = write_order(account["id"],
                        [line_item(hubassy["id"], 2), line_item(notfit["id"], 2)],
                        vehicle_id=vehicle["id"])
    fitting_only = write_order(account["id"], [line_item(hubassy["id"], 2)],
                               vehicle_id=vehicle["id"])

    for order in (mixed, fitting_only):
        api_client.confirm_order(
            order["id"],
            {"expected_order_version": reload_order(order["id"])["version"],
             "expected_account_version": reload_account(account["id"])["version"]},
            sales_rep_headers)

    assert reload_order(mixed["id"])["status"] == "DRAFT"
    assert reload_order(fitting_only["id"])["status"] == "DRAFT"
    assert reload_inventory(notfit_inv["id"])["reserved_units"] == 0