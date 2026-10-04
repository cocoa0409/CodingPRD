"""Corner queue B — cross-cutting complexity layers: OCC, cascades, idempotency."""
from test_helpers import (
    CREDIT_OFFICER,
    MANAGER,
    ApiErrorId,
    activate_route,
    advance_product_order,
    advance_territory,
    api_client,
    create_certified_franchisee,
    create_order,
    create_product,
    create_product_order,
    create_route,
    create_shop,
    create_technician,
    edit_order,
    file_pledge,
    get_franchisee,
    get_order,
    get_product_order,
    get_route,
    get_shop,
    get_technician,
    list_positions,
    order_line,
    pledged_line,
    qualify_territory,
    requested_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_confirm_carrying_a_superseded_order_version_is_refused(api):
    """PRD §2.8: "Confirming a `SalesOrder` requires `expected_sales_order_version` matching the order's
    current `version`; a mismatch is rejected with `ERR_STALE_VERSION` and HTTP status 412."
    PRD §3.4: "Because editing lines is a legitimate re-confirmation path, the confirmation
    write requires `expected_sales_order_version`"

    Design: Corner/cross-cutting complexity layers/occ_stale_version_on_sales_order_confirm
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 1)])
    stale_version = order["version"]

    edited = validate_success(edit_order(store["franchisee"], order,
                                         [order_line(product, 2)]))
    assert edited["version"] > stale_version
    assert edited["gross_total_cents"] == 30225

    refused = api_client.advance_sales_order(
        order["id"], {"action": "CONFIRM", "expected_sales_order_version": stale_version},
        store["franchisee"]["rep_headers"])
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, 412)
    assert get_order(order["id"])["order_status"] == "DRAFT"

    fresh = get_order(order["id"], store["franchisee"]["rep_headers"])["version"]
    confirmed = validate_success(api_client.advance_sales_order(
        order["id"], {"action": "CONFIRM", "expected_sales_order_version": fresh},
        store["franchisee"]["rep_headers"]))
    assert confirmed["order_status"] == "CONFIRMED"


def test_second_mint_with_a_superseded_application_version_is_refused(api):
    """PRD §2.8: "Minting a `CreditAccount` against a `CreditApplication` requires `expected_application_version`
    matching the application's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` and HTTP
    status 412."
    PRD §3.5: "an application that was reopened
    and re-approved legitimately mints a second account, so a strictly sequential second mint would
    otherwise succeed"

    Design: Corner/cross-cutting complexity layers/occ_stale_version_on_credit_account_mint
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    from test_helpers import approve_application, file_application
    application = file_application(store["franchisee"], people["shop"],
                                   people["technician"], requested_limit_cents=50_000)
    approved = approve_application(store["franchisee"], application)
    stale_version = approved["version"]

    first = validate_success(api_client.mint_credit_account(
        application["id"], {"expected_application_version": stale_version},
        CREDIT_OFFICER), 201)

    current = validate_success(api_client.get_credit_application(
        application["id"], CREDIT_OFFICER))
    assert current["version"] > stale_version
    assert current["application_status"] == "APPROVED"

    refused = api_client.mint_credit_account(
        application["id"], {"expected_application_version": stale_version}, CREDIT_OFFICER)
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, 412)

    second = validate_success(api_client.mint_credit_account(
        application["id"], {"expected_application_version": current["version"]},
        CREDIT_OFFICER), 201)
    assert second["id"] != first["id"]


def test_retire_carrying_a_superseded_route_version_is_refused(api):
    """PRD §2.8: "Retiring a `Route` requires `expected_route_version` matching
    the route's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` and HTTP status 412."
    PRD §2.8: "a resale
    filing legitimately advances; a stale version would retire a route the client believed had no pending
    resale."

    Design: Corner/cross-cutting complexity layers/occ_stale_version_on_route_retire_after_resale_filing
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    activate_route(franchisee, route)
    qualify_territory(franchisee, route, 90)
    suspended = validate_success(api_client.advance_route_status(
        route["id"], {"action": "SUSPEND"}, MANAGER))
    stale_version = suspended["version"]

    filed = validate_success(api_client.resale_action(
        route["id"], {"action": "FILE", "buyer_training_status": "ENROLLED",
                      "buyer_training_points": 10},
        franchisee["owner_headers"]))
    assert filed["version"] > stale_version

    refused = api_client.advance_route_status(
        route["id"], {"action": "RETIRE", "expected_route_version": stale_version}, MANAGER)
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, 412)

    blocked = api_client.advance_route_status(
        route["id"], {"action": "RETIRE", "expected_route_version": filed["version"]}, MANAGER)
    # PRD names ERR_RESALE_ALREADY_PENDING for a second filing; the retire rule
    # states the refusal without naming an identifier, so either identifier fits.
    assert blocked.status_code == 409
    validate_error_is_one_of(blocked, [ApiErrorId.ERR_RESALE_ALREADY_PENDING,
                                       ApiErrorId.ERR_INVALID_STATE])
    assert get_route(route["id"])["route_status"] == "SUSPENDED"


def test_parent_versions_advance_by_one_on_every_accepted_write(api):
    """PRD §2.5: "The `version` field is an integer that starts at 1 and increments by exactly 1 on every modification
    to the resource."
    PRD §3.6: "the filing increments the parent order's `version`."

    Design: Corner/cross-cutting complexity layers/occ_version_increments_on_every_parent_write
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    assert route["version"] == 1
    activated = validate_success(api_client.advance_route_status(
        route["id"], {"action": "ACTIVATE"}, franchisee["owner_headers"]))
    assert activated["version"] == 2

    product = create_product(sku="P1", category="DIAGNOSTICS", unit_cost_cents=30000,
                             retail_price_cents=39000)
    shop = create_shop(franchisee, route)
    technician = create_technician(franchisee, shop)
    account = setup_account(franchisee, shop, technician, requested_limit_cents=50_000)

    positioned = validate_success(api_client.write_inventory_position(
        route["id"], {"product_id": product["id"], "on_hand_qty": 1},
        franchisee["owner_headers"]), 201)
    assert positioned["version"] == 1
    assert get_route(route["id"])["version"] == 3

    order = create_product_order(franchisee, route, [requested_line(product["id"], 2)],
                                 ceiling=60000)
    created_version = order["version"]
    submitted = validate_success(advance_product_order(franchisee, order, "SUBMIT"))
    assert submitted["version"] == created_version + 1

    refused = file_pledge(franchisee, order, account, [pledged_line(product["id"], 1)],
                          created_version)
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, 412)


def test_route_suspension_deactivates_shops_but_not_technicians(api):
    """PRD §3.1: "Every shop on that route whose `shop_status` is `ACTIVE` becomes `INACTIVE`, and each of those shops
    in turn affects the technicians who work there, as Section 3.2 describes."
    PRD §3.2: "because the shop's
    `active_technician_count` counts only technicians whose own standing is `ACTIVE`, an inactive shop
    reports the reduced count immediately."

    Design: Corner/cross-cutting complexity layers/cascading_side_effects_route_suspend_deactivates_shops
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1", zip_codes=["75001", "75002"])
    activate_route(franchisee, route)
    first_shop = create_shop(franchisee, route)
    second_shop = create_shop(franchisee, route, shop_name="Southside Garage",
                              street_line="9 Oak", zip_code="75002")
    first_technician = create_technician(franchisee, first_shop)
    create_technician(franchisee, second_shop, full_name="Ravi Shah", months_in_trade=60)

    suspended = validate_success(api_client.advance_route_status(
        route["id"], {"action": "SUSPEND"}, MANAGER))
    assert suspended["route_status"] == "SUSPENDED"

    assert get_shop(first_shop["id"])["shop_status"] == "INACTIVE"
    assert get_shop(second_shop["id"])["shop_status"] == "INACTIVE"
    assert get_technician(first_technician["id"])["technician_status"] == "ACTIVE"
    assert get_franchisee(franchisee["id"])["active_route_count"] == 0


def test_repeated_draft_summary_reads_are_side_effect_free(api):
    """PRD §2.10: "The franchisor's draft eligibility summary for a franchisee reports the resolved fallback
    together with the franchisee's `franchisee_id`, its `active_account_count` and its
    `recourse_exposure_cents`, and that summary is the read a franchisor runs before drafting"
    PRD §2.5: "`updated_at` field is an ISO 8601 UTC timestamp with three fractional digits, refreshed on
    every mutation of the row"

    Design: Corner/cross-cutting complexity layers/idempotency_draft_summary_read_is_repeatable
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)

    before = get_franchisee(store["franchisee"]["id"], MANAGER)["version"]
    first = validate_success(api_client.get_draft_summary(
        store["franchisee"]["id"], MANAGER))
    second = validate_success(api_client.get_draft_summary(
        store["franchisee"]["id"], MANAGER))

    assert first["fallback_shop_location_id"] == people["shop"]["id"]
    assert second["fallback_shop_location_id"] == people["shop"]["id"]
    assert first["active_account_count"] == second["active_account_count"] == 0
    assert first["recourse_exposure_cents"] == second["recourse_exposure_cents"] == 0
    assert get_franchisee(store["franchisee"]["id"], MANAGER)["version"] == before


def test_pledge_carrying_a_superseded_order_version_is_refused(api):
    """PRD §2.8: "Creating a
    `SharePledge` against a `ProductOrder` requires `expected_product_order_version` matching that order's
    current `version`"
    PRD §3.6: "A
    pledge against any other status is refused with `ERR_PRODUCT_ORDER_NOT_DRAFT`."

    Design: Corner/cross-cutting complexity layers/occ_stale_version_on_pledge_create_against_draft_order
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = create_product(sku="P1", category="DIAGNOSTICS", unit_cost_cents=30000,
                             retail_price_cents=39000)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_product_order(store["franchisee"], store["route"],
                                 [requested_line(product["id"], 2)], ceiling=60000)
    original_version = order["version"]

    first = validate_success(file_pledge(store["franchisee"], order, account,
                                         [pledged_line(product["id"], 1)],
                                         original_version), 201)
    assert first["pledge_status"] == "HELD"

    current = get_product_order(order["id"], store["franchisee"]["owner_headers"])
    assert current["version"] > original_version
    assert current["product_order_status"] == "DRAFT"

    refused = file_pledge(store["franchisee"], order, account,
                          [pledged_line(product["id"], 1)], original_version)
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION, 412)

    second = validate_success(file_pledge(store["franchisee"], order, account,
                                          [pledged_line(product["id"], 1)],
                                          current["version"]), 201)
    assert second["id"] != first["id"]


def test_receive_carrying_a_superseded_order_version_posts_nothing(api):
    """PRD §3.6: "Receiving moves `SHIPPED` to `RECEIVED`, requires `expected_product_order_version` matching the
    order's current `version` per Section 2.8, and posts stock"
    PRD §3.6: "a superseded view would post a quantity the order no longer
    carries."

    Design: Corner/cross-cutting complexity layers/occ_stale_version_on_product_order_receive
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    product = create_product(sku="P1", category="DIAGNOSTICS", unit_cost_cents=30000,
                             retail_price_cents=39000)
    order = create_product_order(store["franchisee"], store["route"],
                                 [requested_line(product["id"], 2)], ceiling=60000)
    submitted = validate_success(advance_product_order(store["franchisee"], order,
                                                       "SUBMIT"))
    shipped = validate_success(advance_product_order(store["franchisee"], order,
                                                     "SHIP"))
    assert shipped["version"] > submitted["version"]

    stale = advance_product_order(store["franchisee"], order, "RECEIVE",
                                  submitted["version"])
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    received = validate_success(advance_product_order(store["franchisee"], order, "RECEIVE",
                                                      shipped["version"]))
    assert received["product_order_status"] == "RECEIVED"

    rows = list_positions(store["franchisee"], store["route"]["id"], product["id"])
    assert len(rows) == 1
    assert rows[0]["on_hand_qty"] == 2
