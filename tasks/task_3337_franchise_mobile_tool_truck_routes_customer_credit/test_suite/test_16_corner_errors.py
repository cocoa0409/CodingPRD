"""Corner queue B — errors: each rejection pinned to its identifier."""
from test_helpers import (
    CREDIT_OFFICER,
    MANAGER,
    ApiErrorId,
    activate_route,
    advance_route,
    advance_territory,
    api_client,
    book_payment,
    create_certified_franchisee,
    create_delivered_order,
    create_order,
    create_route,
    deliver_order,
    file_claim,
    get_account,
    get_order,
    get_route,
    list_warranty_claims,
    order_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_error,
    validate_success,
)


def test_closing_an_account_with_a_balance_is_refused(api):
    """PRD §3.5: "close an account whose balance is zero; a charge-off requested too early is refused with
    `ERR_CHARGE_OFF_NOT_DUE` and a closure requested with a non-zero balance with `ERR_ACCOUNT_HAS_BALANCE`."
    PRD §2.13: "a request to terminate a line while the technician still carries a
    balance is refused with `ERR_ACCOUNT_HAS_BALANCE` at HTTP status 422"

    Design: Corner/errors/error_account_has_balance_on_close_with_outstanding_principal
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="POWER_TOOLS")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    create_delivered_order(store["franchisee"], store["route"], people["technician"],
                           account, [order_line(product, 3)],
                           mix_profile="DIAGNOSTIC_WEIGHTED")

    read = get_account(account["id"])
    assert read["current_balance_cents"] == 45338

    close = api_client.advance_account_status(account["id"], {"action": "CLOSE"},
                                              CREDIT_OFFICER)
    validate_error(close, ApiErrorId.ERR_ACCOUNT_HAS_BALANCE, 422)
    assert get_account(account["id"])["account_status"] == "ACTIVE"
    assert get_account(account["id"])["credit_available_cents"] == 4662


def test_claim_line_index_outside_the_order_is_refused(api):
    """PRD §2.9: "a claim whose
    `line_index` falls outside the parent order's `lines` array is rejected with
    `ERR_WARRANTY_LINE_OUT_OF_RANGE`, also at HTTP status 422."
    PRD §3.8: "The `line_index`
    must fall within the parent order's lines array; one that does not is refused with
    `ERR_WARRANTY_LINE_OUT_OF_RANGE` at HTTP status 422."

    Design: Corner/errors/error_warranty_line_index_out_of_range_on_submit
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_delivered_order(store["franchisee"], store["route"],
                                   people["technician"], account, [order_line(product, 1)])
    assert get_order(order["id"], store["franchisee"]["rep_headers"])["line_count"] == 1

    response = file_claim(store["franchisee"], order, "idem-range-1", line_index=5,
                          apply_to_account_id=account["id"])
    validate_error(response, ApiErrorId.ERR_WARRANTY_LINE_OUT_OF_RANGE, 422)

    assert list_warranty_claims(store["franchisee"], {"order_id": order["id"]}) == []


def test_resale_filing_requires_a_qualified_territory(api):
    """PRD §3.1: "A resale filing that is attempted with no live qualification behind it is refused
    as `ERR_TERRITORY_NOT_QUALIFIED`."
    PRD §2.10: "a round qualifies when the route's `territory_points`
    reach at least 60 while the route's `route_status` is `IN_SERVICE`."

    Design: Corner/errors/error_territory_not_qualified_on_resale_filing
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    developing = validate_success(advance_territory(franchisee, route, "DEVELOP", 10))
    assert developing["territory_development_status"] == "IN_DEVELOPMENT"

    filing = {"action": "FILE", "buyer_training_status": "ENROLLED",
              "buyer_training_points": 10}
    validate_error(api_client.resale_action(route["id"], filing, franchisee["owner_headers"]),
                   ApiErrorId.ERR_TERRITORY_NOT_QUALIFIED, 409)

    activate_route(franchisee, route)
    qualified = validate_success(advance_territory(franchisee, route, "DEVELOP", 90))
    assert qualified["territory_development_status"] == "QUALIFIED"

    filed = validate_success(api_client.resale_action(
        route["id"], filing, franchisee["owner_headers"]))
    assert filed["resale_status"] == "PENDING"
    assert filed["reopening_fee_cents"] == 635000


def test_second_activation_is_refused(api):
    """PRD §3.1: "an activation attempted against a route that is not
    `DRAFT` is reported as `ERR_ROUTE_ALREADY_IN_SERVICE`."

    Design: Corner/errors/error_route_already_in_service_on_second_activation
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    activated = validate_success(advance_route(franchisee, route, "ACTIVATE"))
    assert activated["route_status"] == "IN_SERVICE"

    validate_error(advance_route(franchisee, route, "ACTIVATE"),
                   ApiErrorId.ERR_ROUTE_ALREADY_IN_SERVICE, 409)

    from test_helpers import get_franchisee
    assert get_franchisee(franchisee["id"])["active_route_count"] == 1


def test_reversing_a_payment_that_was_never_collected_is_refused(api):
    """PRD §3.5: "A
    reversal attempted against a payment that is not `COLLECTED` is refused with
    `ERR_PAYMENT_NOT_COLLECTED`."
    PRD §3.5: "A new payment starts at
    `payment_status` `BOOKED` and has a null `effective_iso_week`"

    Design: Corner/errors/error_payment_not_collected_on_reverse_of_booking
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    payment = book_payment(store["franchisee"], account, "2026-09-07T00:00:00Z")
    assert payment["payment_status"] == "BOOKED"
    assert payment["effective_iso_week"] is None

    validate_error(api_client.advance_payment(
        account["id"], payment["id"], {"action": "REVERSE"}, CREDIT_OFFICER),
        ApiErrorId.ERR_PAYMENT_NOT_COLLECTED, 409)

    read = get_account(account["id"])
    assert read["principal_balance_cents"] == 0


def test_delivery_requires_a_confirmed_order(api):
    """PRD §3.4: "Delivery requires the order to be `CONFIRMED` and is otherwise refused as
    `ERR_ORDER_NOT_DELIVERABLE`"
    PRD §3.4: "the target credit account's `principal_balance_cents` is increased by
    `financed_principal_cents`"

    Design: Corner/errors/error_order_not_deliverable_from_draft
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 1)])
    assert order["order_status"] == "DRAFT"

    early = api_client.advance_sales_order(order["id"], {"action": "DELIVER"},
                                           store["franchisee"]["rep_headers"])
    validate_error(early, ApiErrorId.ERR_ORDER_NOT_DELIVERABLE, 409)
    assert get_order(order["id"])["order_status"] == "DRAFT"
    assert get_account(account["id"])["principal_balance_cents"] == 0

    from test_helpers import confirm_order
    confirm_order(store["franchisee"], order, order["version"])
    deliver_order(store["franchisee"], order)
    assert get_order(order["id"])["order_status"] == "DELIVERED"
    assert get_account(account["id"])["principal_balance_cents"] == 15113


def test_draft_summary_needs_an_active_shop_for_the_fallback(api):
    """PRD §2.10: "A franchisor-draft collection
    that needs the fallback but finds none is refused with `ERR_FALLBACK_LOCATION_MISSING` and HTTP status
    422."
    PRD §2.10: "when the
    franchisee has no `ACTIVE` shop on any route the summary is refused with the same
    `ERR_FALLBACK_LOCATION_MISSING` identifier at HTTP status 422 rather than returning a null fallback."

    Design: Corner/errors/error_fallback_location_missing_on_draft_summary
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")

    validate_error(api_client.get_draft_summary(franchisee["id"], CREDIT_OFFICER),
                   ApiErrorId.ERR_FALLBACK_LOCATION_MISSING, 422)

    from test_helpers import create_shop
    shop = create_shop(franchisee, route)
    summary = validate_success(api_client.get_draft_summary(franchisee["id"],
                                                            CREDIT_OFFICER))
    assert summary["fallback_shop_location_id"] == shop["id"]
    assert summary["active_account_count"] == 0


def test_resale_decision_without_a_filing_reports_not_pending(api):
    """PRD §3.1: "a decision attempted while no filing is pending is
    refused with `ERR_RESALE_NOT_PENDING`; both carry HTTP status 409."
    PRD §3.1: "Resale is a third parallel axis, enabled by certification and by qualification."

    Design: Corner/errors/error_invalid_state_on_resale_decision_without_filing
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    assert route["resale_status"] == "NONE"
    assert route["territory_development_status"] == "UNASSIGNED"

    decision = api_client.resale_action(route["id"], {"action": "APPROVE"}, MANAGER)
    validate_error(decision, ApiErrorId.ERR_RESALE_NOT_PENDING, 409)
