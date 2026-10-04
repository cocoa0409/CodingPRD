"""Difficulty queue A — cross_entity_state_dependency: another row decides."""
from test_helpers import (
    CREDIT_OFFICER,
    ApiErrorId,
    activate_route,
    api_client,
    create_certified_franchisee,
    create_order,
    create_route,
    create_shop,
    create_technician,
    get_account,
    get_order,
    get_route,
    get_technician,
    order_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    update_shop,
    validate_error,
    validate_success,
)


def test_confirm_is_gated_on_the_credit_account_state(api):
    """PRD §3.4: "Confirmation additionally requires that the order be `DRAFT`, that
    `line_count` be at least 1, and that the credit account named on the order be `ACTIVE`; an order that
    is not `DRAFT` is refused as `ERR_ORDER_NOT_CONFIRMABLE` and an account that is not `ACTIVE` as
    `ERR_ACCOUNT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_sales_order_confirm_requires_active_account
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="DIAGNOSTIC_WEIGHTED")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=0)

    order = create_order(store["franchisee"], store["route"], people["technician"],
                         account, [order_line(product, 1)],
                         mix_profile="DIAGNOSTIC_WEIGHTED")
    suspended = validate_success(api_client.advance_account_status(
        account["id"], {"action": "SUSPEND"}, CREDIT_OFFICER))
    assert suspended["account_status"] == "SUSPENDED"

    confirm = api_client.advance_sales_order(
        order["id"],
        {"action": "CONFIRM", "expected_sales_order_version": order["version"]},
        store["franchisee"]["rep_headers"])
    validate_error(confirm, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, 409)

    assert get_order(order["id"])["order_status"] == "DRAFT"
    assert get_route(store["route"]["id"])["inventory_at_risk_cents"] == 0
    assert get_account(account["id"])["account_status"] == "SUSPENDED"


def test_shop_change_is_gated_on_the_target_shop_state(api):
    """PRD §3.2: "A shop change is refused unless the technician is currently `ACTIVE`, the
    target shop is `ACTIVE`, and every credit account the technician holds is in one of the standing
    postures `ACTIVE`, `SUSPENDED`, `DELINQUENT` or `CHARGED_OFF`"
    PRD §3.2: "The move immediately repoints `current_shop_location_id` at the target
    shop, recomputes `home_route_id` from the new shop, and refreshes the source and target shops'
    `active_technician_count`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_shop_change_requires_active_target_shop
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route_one = create_route(franchisee, route_code="R1", zip_codes=["75001"])
    route_two = create_route(franchisee, route_code="R2", zip_codes=["75002"],
                             visit_weekday=1, truck_label="T-02",
                             mix_plan="TOOL_STORAGE")
    activate_route(franchisee, route_one)
    activate_route(franchisee, route_two)
    shop_one = create_shop(franchisee, route_one)
    shop_two = create_shop(franchisee, route_two, shop_name="Southside Garage",
                           street_line="9 Oak", zip_code="75002")
    technician = create_technician(franchisee, shop_one)

    updated = validate_success(update_shop(franchisee, shop_two,
                                           shop_status="INACTIVE"))
    assert updated["shop_status"] == "INACTIVE"

    refused = api_client.advance_technician_status(
        technician["id"],
        {"action": "CHANGE_SHOP", "target_shop_location_id": shop_two["id"]},
        franchisee["owner_headers"])
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_technician(technician["id"])["technician_status"] == "ACTIVE"
    assert get_technician(technician["id"])["current_shop_location_id"] == shop_one["id"]

    moved = validate_success(api_client.advance_technician_status(
        technician["id"],
        {"action": "CHANGE_SHOP", "target_shop_location_id": shop_one["id"]},
        franchisee["owner_headers"]))
    assert moved["technician_status"] == "SHOP_CHANGE_PENDING"
    assert moved["current_shop_location_id"] == shop_one["id"]
