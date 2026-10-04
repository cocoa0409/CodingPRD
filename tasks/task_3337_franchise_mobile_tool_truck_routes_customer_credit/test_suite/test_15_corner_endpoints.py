"""Corner queue B — endpoints: envelope, listing filters, conditional actions."""
from test_helpers import (
    CREDIT_OFFICER,
    MANAGER,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    ApiErrorId,
    advance_route,
    advance_territory,
    activate_route,
    api_client,
    create_certified_franchisee,
    create_delivered_order,
    create_order,
    create_product,
    create_product_order,
    create_route,
    create_shop,
    edit_order,
    file_claim,
    file_pledge,
    get_account,
    get_product_order,
    get_order,
    get_route,
    list_pledges,
    list_warranty_claims,
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
    validate_paginated,
    validate_success,
)


def test_list_reads_return_the_standard_envelope_with_pagination(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    PRD §2.3: "The `meta` object of a list response carries the four pagination fields
    `limit`, `offset`, `total_count` and `has_more`."

    Design: Corner/endpoints/endpoint_success_envelope_and_pagination_defaults
    """
    first = create_certified_franchisee(legal_name="First Franchisee LLC")
    second = create_certified_franchisee(legal_name="Second Franchisee LLC")
    create_route(first, route_code="R1")
    create_route(second, route_code="R2", route_tier="B", zip_codes=["75002"],
                 visit_weekday=2, truck_label="T-02", inventory_invested_cents=50000,
                 mix_plan="TOOL_STORAGE")

    response = api_client.list_routes(PLATFORM_ADMIN)
    rows, meta = validate_paginated(response)
    body = response.json()
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["response_type"] == "array"
    assert len(rows) == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_claim_listing_honours_a_compound_filter(api):
    """PRD §4: "warranty claims by `order_id`,
    `apply_to_account_id`, `claim_status` and `claim_kind`;"
    PRD §2.3: "When a caller
    supplies a `limit` below 1 or above 100, or a non-integer value for either parameter, the request is
    refused with `ERR_INVALID_REQUEST` and HTTP status 400."

    Design: Corner/endpoints/endpoint_listing_filter_combinations_narrow_the_page
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_delivered_order(store["franchisee"], store["route"],
                                   people["technician"], account,
                                   [order_line(product, 1), order_line(product, 1)])

    open_claim = validate_success(file_claim(
        store["franchisee"], order, "idem-list-a",
        apply_to_account_id=account["id"]), 201)
    replacement = validate_success(file_claim(
        store["franchisee"], order, "idem-list-b", line_index=1,
        claim_kind="WARRANTY_REPLACEMENT"), 201)
    submitted = validate_success(api_client.advance_warranty_claim(
        order["id"], replacement["id"], {"action": "SUBMIT"},
        store["franchisee"]["rep_headers"]))
    assert submitted["claim_status"] == "SUBMITTED"

    unfiltered = list_warranty_claims(store["franchisee"], {"order_id": order["id"]})
    assert len(unfiltered) == 2

    rows, meta = validate_paginated(api_client.list_warranty_claims(
        store["franchisee"]["rep_headers"],
        {"order_id": order["id"], "claim_status": "OPEN", "claim_kind": "CLAIM"}))
    assert len(rows) == 1
    assert rows[0]["id"] == open_claim["id"]
    assert rows[0]["claim_status"] == "OPEN"
    assert meta["total_count"] == 1


def test_unknown_order_and_nested_claim_paths_report_not_found(api):
    """PRD §2.6: "A child identifier that is syntactically present but does not
    belong to the parent named ahead of it in the same path — a payment that is not on the named account,
    a claim that is not on the named order — is reported with the same 404 identifier as a wholly absent
    row."

    Design: Corner/endpoints/endpoint_order_not_found_returns_404
    """
    validate_error(api_client.get_sales_order(NON_EXISTENT_UUID, PLATFORM_ADMIN),
                   ApiErrorId.ERR_ORDER_NOT_FOUND, 404)
    nested = api_client.advance_warranty_claim(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, {"action": "SUBMIT"},
        {"X-User-ID": "test-routesalesrep-1", "X-User-Role": "RouteSalesRep",
         "Content-Type": "application/json"})
    validate_error(nested, ApiErrorId.ERR_ORDER_NOT_FOUND, 404)


def test_editing_an_order_to_an_empty_line_set_is_refused(api):
    """PRD §2.9: "A sales order created
    or edited with an empty `lines` array, and a replenishment order submitted with empty
    `requested_lines`, are rejected with `ERR_EMPTY_MIX_LINES` and HTTP status 422"

    Design: Corner/endpoints/endpoint_patch_order_rejects_empty_line_array
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront(mix_plan="DIAGNOSTIC_WEIGHTED")
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 2)], mix_profile="DIAGNOSTIC_WEIGHTED")
    assert order["gross_total_cents"] == 30225
    assert order["line_count"] == 1

    empty = edit_order(store["franchisee"], order, [])
    validate_error(empty, ApiErrorId.ERR_EMPTY_MIX_LINES, 422)

    unchanged = get_order(order["id"], store["franchisee"]["rep_headers"])
    assert unchanged["gross_total_cents"] == 30225
    assert unchanged["line_count"] == 1


def test_account_read_reconciles_its_derived_fields(api):
    """PRD §2.13: "An account's `credit_available_cents` is `credit_limit_cents` minus `current_balance_cents`,
    floored at zero"
    PRD §3.5: "The tier is read from the account's
    current balance, never from the value the formula is about to produce"

    Design: Corner/endpoints/endpoint_computed_read_account_derived_fields_reconcile
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

    set_clock("2026-09-14T00:00:00Z")
    read = get_account(account["id"])
    assert read["principal_balance_cents"] == 45338
    assert read["accrued_finance_charge_cents"] == 136
    assert read["current_balance_cents"] == 45474
    assert read["current_balance_cents"] == (read["principal_balance_cents"]
                                             + read["accrued_finance_charge_cents"])
    assert read["credit_available_cents"] == 4526
    assert read["credit_available_cents"] == read["credit_limit_cents"] - read["current_balance_cents"]
    assert read["minimum_payment_due_cents"] == 4547


def test_route_update_recomputes_the_schedule_anchor(api):
    """PRD §3.1: "a revision that changes `visit_weekday` forces
    `schedule_anchor_utc` to be recomputed."
    PRD §2.12: "if the logical clock reads exactly Monday `08:00:00Z` and the route's
    `visit_weekday` is 1, the anchor is the previous Monday at `08:00:00Z`, seven days earlier, not the
    current instant."

    Design: Corner/endpoints/endpoint_route_update_recomputes_schedule_anchor
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1", visit_weekday=1)
    assert route["schedule_anchor_utc"] == "2026-08-31T08:00:00Z"

    updated = validate_success(api_client.update_route(
        route["id"], {"visit_weekday": 5}, franchisee["owner_headers"]))
    assert updated["visit_weekday"] == 5
    assert updated["schedule_anchor_utc"] == "2026-09-04T08:00:00Z"
    assert updated["schedule_anchor_utc"] != "2026-09-07T08:00:00Z"


def test_pledge_naming_an_unknown_account_is_refused(api):
    """PRD §2.6: "When a body references a product or an account, a missing target is
    reported as `ERR_PRODUCT_NOT_FOUND` or `ERR_ACCOUNT_NOT_FOUND` respectively, and only after the path
    has been validated."

    Design: Corner/endpoints/endpoint_cross_reference_pledge_requires_existing_account
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    product = create_product(sku="P1", category="DIAGNOSTICS", unit_cost_cents=30000,
                             retail_price_cents=39000)
    order = create_product_order(store["franchisee"], store["route"],
                                 [requested_line(product["id"], 2)], ceiling=60000)

    response = file_pledge(store["franchisee"], order,
                           {"id": NON_EXISTENT_UUID},
                           [pledged_line(product["id"], 1)], order["version"])
    validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND, 404)

    assert list_pledges(store["franchisee"], {"product_order_id": order["id"]}) == []
    assert get_product_order(order["id"], store["franchisee"]["owner_headers"])[
        "product_order_status"] == "DRAFT"


def test_retire_is_refused_while_a_resale_is_pending(api):
    """PRD §3.1: "A cultivating route whose `resale_status` is `PENDING` may not be retired, because the filing is still
    live."
    PRD §3.1: "When a route retires
    while its `territory_development_status` is `QUALIFIED`, the territory is moved to `SURRENDERED` at the
    same moment and its `in_force_to_week` is stamped."

    Design: Corner/endpoints/endpoint_conditional_retire_refused_while_resale_pending
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    activate_route(franchisee, route)
    qualify_territory(franchisee, route, 90)
    suspended = validate_success(advance_route(franchisee, route, "SUSPEND"))
    assert suspended["route_status"] == "SUSPENDED"

    filed = validate_success(api_client.resale_action(
        route["id"], {"action": "FILE", "buyer_training_status": "ENROLLED",
                      "buyer_training_points": 10},
        franchisee["owner_headers"]))
    assert filed["resale_status"] == "PENDING"

    version = get_route(route["id"])["version"]
    retire = api_client.advance_route_status(
        route["id"], {"action": "RETIRE", "expected_route_version": version}, MANAGER)
    # PRD names ERR_RESALE_ALREADY_PENDING for a second filing; the retire rule
    # states the refusal without naming an identifier, so either identifier fits.
    assert retire.status_code == 409
    validate_error_is_one_of(retire, [ApiErrorId.ERR_RESALE_ALREADY_PENDING,
                                      ApiErrorId.ERR_INVALID_STATE])
    assert get_route(route["id"])["route_status"] == "SUSPENDED"

    validate_success(api_client.resale_action(route["id"], {"action": "DECLINE"}, MANAGER))
    fresh = get_route(route["id"])["version"]
    retired = validate_success(api_client.advance_route_status(
        route["id"], {"action": "RETIRE", "expected_route_version": fresh},
        MANAGER))
    assert retired["route_status"] == "RETIRED"
    assert retired["territory_development_status"] == "SURRENDERED"
