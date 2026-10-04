"""Corner queue B — entities: creation defaults, required fields, computed values."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    order_line,
    PLATFORM_ADMIN,
    api_client,
    create_certified_franchisee,
    create_order,
    create_route,
    create_shop,
    create_technician,
    get_franchisee,
    get_shop,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_franchisee_starts_unenrolled_with_zeroed_rollups(api):
    """PRD §3.1: "A franchisee begins with a `legal_name` and nothing else: `training_status` starts at `NOT_ENROLLED`,"
    PRD §2.10: "`can_resell_territory` is a derived boolean that is true exactly when `training_status` is"

    Design: Corner/entities/entity_franchisee_creation_defaults_and_computed_zeroes
    """
    created = validate_success(
        api_client.create_franchisee({"legal_name": "Route 3337 Franchising LLC"},
                                     PLATFORM_ADMIN), 201)
    assert created["training_status"] == "NOT_ENROLLED"
    assert created["can_resell_territory"] is False

    fetched = get_franchisee(created["id"], PLATFORM_ADMIN)
    assert fetched["active_route_count"] == 0
    assert fetched["credit_ceiling_cents"] == 0
    assert fetched["certified_on"] is None


def test_route_creation_without_zip_codes_is_refused(api):
    """PRD §2.6: "Malformed requests come first: a body that omits a required field, supplies the wrong type,"
    PRD §4: "route creation takes `route_code`, `route_tier`, `zip_codes`, `visit_weekday`,"
    PRD §3.1: "The `zip_codes` array must be non-empty; an empty one blocks activation."

    Design: Corner/entities/entity_route_creation_missing_required_zip_codes_rejected
    """
    franchisee = create_certified_franchisee()
    response = api_client.create_route(
        franchisee["id"],
        {"route_code": "R1", "route_tier": "A", "visit_weekday": 1, "truck_label": "T-01",
         "inventory_invested_cents": 100000, "mix_plan": "DIAGNOSTIC_WEIGHTED",
         "territory_model": "FRANCHISEE_ASSUMED"},
        franchisee["owner_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    body = validate_success(api_client.list_routes(
        franchisee["owner_headers"], {"franchisee_id": franchisee["id"]}))
    assert body == []


def test_product_with_unknown_category_enum_is_refused(api):
    """PRD §2.6: "Malformed requests come first: a body that omits a required field, supplies the wrong type,"
    PRD §3.7: "the `category` is one of `DIAGNOSTICS`, `TOOL_STORAGE` or `POWER_TOOLS`."

    Design: Corner/entities/entity_product_invalid_category_enum_rejected
    """
    response = api_client.create_product(
        {"sku": "P1", "product_name": "Torque Wrench", "category": "DIAGNOSTIC",
         "unit_cost_cents": 12000, "retail_price_cents": 15000,
         "default_warranty_months": 12, "is_new_launch": False},
        PLATFORM_ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    body = validate_success(api_client.list_products(PLATFORM_ADMIN))
    assert body == []


def test_unknown_shop_identifier_reports_shop_not_found(api):
    """PRD §2.6: "The rejection for a missing path resource is an HTTP
    status 404 whose identifier names the failing entity: `ERR_FRANCHISEE_NOT_FOUND`,"
    PRD §2.6: "`ERR_SHOP_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,"
    PRD §2.6: "`ERR_APPLICATION_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,"
    PRD §2.6: "`ERR_CLAIM_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_ORDER_NOT_FOUND`, and"
    PRD §2.6: "`ERR_INVENTORY_POSITION_NOT_FOUND`."

    Design: Corner/entities/entity_shop_not_found_returns_404
    """
    response = api_client.get_shop(NON_EXISTENT_UUID, PLATFORM_ADMIN)
    validate_error(response, ApiErrorId.ERR_SHOP_NOT_FOUND, 404)


def test_route_listing_filters_by_status_and_honours_limit(api):
    """PRD §2.3: "items are returned; it defaults to 10, its minimum is 1 and its maximum is 100. The `offset`"
    PRD §4: "routes by `franchisee_id`, `route_status`, `territory_development_status` and `resale_status`;"

    Design: Corner/entities/entity_route_listing_filters_by_status_and_paginates
    """
    store = setup_storefront(route_code="R1", activate=True)
    franchisee = store["franchisee"]
    second = create_route(franchisee, route_code="R2", route_tier="B", zip_codes=["75002"],
                          visit_weekday=2, truck_label="T-02",
                          inventory_invested_cents=50000, mix_plan="TOOL_STORAGE")

    draft_rows, meta = validate_paginated(api_client.list_routes(
        franchisee["owner_headers"], {"route_status": "DRAFT", "limit": 1}))
    assert len(draft_rows) == 1, "limit caps the page at one row"
    assert draft_rows[0]["route_status"] == "DRAFT"
    assert draft_rows[0]["id"] == second["id"]

    all_rows, all_meta = validate_paginated(api_client.list_routes(
        franchisee["owner_headers"], {"franchisee_id": franchisee["id"]}))
    assert len(all_rows) == 2
    assert all_meta["total_count"] == 2
    assert {row["route_status"] for row in all_rows} == {"IN_SERVICE", "DRAFT"}


def test_new_technician_derives_home_route_from_the_shop(api):
    """PRD §3.2: "the route that owns the shop — so a technician is always attached to a route through the shop he works"
    PRD §3.2: "The onboarding write refreshes the shop's
    `active_technician_count`."

    Design: Corner/entities/entity_technician_computed_home_route_derived_from_shop
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    shop = create_shop(franchisee, route)

    technician = create_technician(franchisee, shop)
    assert technician["home_route_id"] == route["id"]
    assert technician["revolving_available_cents"] == 100000
    assert technician["open_account_count"] == 0
    assert technician["technician_status"] == "ACTIVE"
    assert technician["credit_line_status"] == "ACTIVE"

    assert get_shop(shop["id"])["active_technician_count"] == 1


def test_draft_order_reports_line_count_gross_total_and_sale_week(api):
    """PRD §3.4: "amounts, evaluated in line order with no further rounding. The order of operations is observable and"
    PRD §2.4: "Weeks in this system are anchored to Monday. A week's start is the Monday `00:00:00Z` of the week in"

    Design: Corner/entities/entity_sales_order_computed_line_count_and_gross_total
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="DIAGNOSTIC_WEIGHTED")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=400_000)

    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 1), order_line(product, 1)],
                         mix_profile="DIAGNOSTIC_WEIGHTED")
    assert order["line_count"] == 2
    assert order["gross_total_cents"] == 30226
    assert order["sale_iso_week"] == "2026-09-07T00:00:00Z"
    assert order["order_status"] == "DRAFT"
    assert order["financed_principal_cents"] == 30226


def test_minted_account_freezes_terms_from_the_application(api):
    """PRD §3.5: "`credit_limit_cents` is taken from the application's `approved_limit_cents`,"
    PRD §3.5: "kind, `payment_due_weekday` is inherited from the opening route's `visit_weekday`, and"

    Design: Corner/entities/entity_credit_account_system_fields_frozen_from_application
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(visit_weekday=3)
    people = setup_shop_and_technician(store)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=45_338)

    assert account["credit_limit_cents"] == 45338
    assert account["account_kind"] == "REVOLVING"
    assert account["payment_due_weekday"] == 3
    assert account["account_status"] == "ACTIVE"
    assert account["account_status_changed_at"] == "2026-09-07T00:00:00Z"
    assert account["is_revolving_program"] is True
    assert account["is_lease_program"] is False
    assert account["credit_available_cents"] == 45338
