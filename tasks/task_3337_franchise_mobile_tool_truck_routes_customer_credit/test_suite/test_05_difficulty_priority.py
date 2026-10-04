"""Difficulty queue A — priority_pair_validation_conflict: lower priority number wins."""
from test_helpers import (
    CREDIT_OFFICER,
    MANAGER,
    ApiErrorId,
    advance_route,
    advance_territory,
    api_client,
    confirm_order,
    create_certified_franchisee,
    create_order,
    create_route,
    get_account,
    get_order,
    get_route,
    order_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_error,
    validate_success,
)


def test_deliver_reports_state_check_before_the_fiscal_check(api):
    """PRD §3.9: "State admissibility comes sixth with `ERR_INVALID_STATE`
    at HTTP status 409 and its entity-specific variants `ERR_ROUTE_NOT_IN_SERVICE`,
    `ERR_APPLICATION_ALREADY_DECIDED`, `ERR_ACCOUNT_NOT_ACTIVE`, ..."
    PRD §3.9: "The fiscal rules come last, and their ordering is deliberate: the account ceiling is checked before
    the shared line, and both are checked before the absolute cap."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_over_business_fiscal_on_suspended_over_limit_account
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="DIAGNOSTIC_WEIGHTED")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=0)
    assert account["credit_available_cents"] == 0

    order = create_order(store["franchisee"], store["route"], people["technician"],
                         account, [order_line(product, 1)],
                         mix_profile="DIAGNOSTIC_WEIGHTED")
    confirmed = confirm_order(store["franchisee"], order, order["version"])
    assert confirmed["financed_principal_cents"] == 15113

    suspended = validate_success(api_client.advance_account_status(
        account["id"], {"action": "SUSPEND"}, CREDIT_OFFICER))
    assert suspended["account_status"] == "SUSPENDED"

    deliver = api_client.advance_sales_order(order["id"], {"action": "DELIVER"},
                                             store["franchisee"]["rep_headers"])
    validate_error(deliver, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE, 409)

    assert get_account(account["id"])["credit_available_cents"] == 0
    unchanged = get_order(order["id"])
    assert unchanged["order_status"] == "CONFIRMED"
    assert unchanged["financed_principal_cents"] == 15113


def test_surrendered_territory_reports_invalid_state_not_window_conflict(api):
    """PRD §3.1: "a development round may not open while an
    earlier round of the same route is still in force, which is reported as
    `ERR_TERRITORY_WINDOW_CONFLICT`."
    PRD §3.1: "surrender is terminal on this axis and independent of `route_status`"

    Design: Difficulty/priority_pair_validation_conflict/priority_state_over_business_temporal_on_surrendered_territory
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    developed = validate_success(advance_territory(franchisee, route, "DEVELOP", 90))
    assert developed["territory_development_status"] == "IN_DEVELOPMENT"

    surrendered = validate_success(advance_territory(
        franchisee, route, "SURRENDER", 90, headers=MANAGER))
    assert surrendered["territory_development_status"] == "SURRENDERED"
    assert surrendered["in_force_to_week"] is not None

    reopen = advance_territory(franchisee, route, "DEVELOP", 90)
    validate_error(reopen, ApiErrorId.ERR_INVALID_STATE, 409)

    final = get_route(route["id"])
    assert final["territory_development_status"] == "SURRENDERED"
    assert final["in_force_to_week"] is not None
