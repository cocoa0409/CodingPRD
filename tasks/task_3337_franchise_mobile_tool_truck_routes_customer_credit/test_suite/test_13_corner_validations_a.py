"""Corner queue B — validations (first half): the fixed order of refusals."""
from test_helpers import (
    MANAGER,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    TEST_USERS,
    ApiErrorId,
    advance_route,
    api_client,
    cancel_payment,
    confirm_order,
    create_certified_franchisee,
    create_delivered_order,
    create_order,
    create_route,
    create_shop,
    create_technician,
    deliver_order,
    edit_order,
    file_application,
    get_franchisee,
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


def test_missing_user_context_is_refused_before_existence(api):
    """PRD §2.1: "A request that omits either header, or that names a role
    the service does not recognise, is rejected with `ERR_MISSING_USER_CONTEXT` and HTTP status 400."
    PRD §3.9: "The first two rules are always evaluated before any business logic."

    Design: Corner/validations/validation_missing_user_context_headers_rejected
    """
    response = api_client.get_franchisee(NON_EXISTENT_UUID,
                                         TEST_USERS["unknown_role_headers"])
    validate_error(response, ApiErrorId.ERR_MISSING_USER_CONTEXT, 400)


def test_logical_clock_may_only_move_forward(api):
    """PRD §2.4: "Attempting to set the clock to an instant
    earlier than the current logical clock is rejected with `ERR_WEEK_CLOCK_BEHIND` and HTTP status 422 —
    the clock may only move forward."

    Design: Corner/validations/validation_clock_cannot_move_backwards
    """
    forward = validate_success(api_client.set_clock("2026-09-14T00:00:00Z",
                                                    PLATFORM_ADMIN))
    assert forward["current_utc"] == "2026-09-14T00:00:00Z"
    assert forward["current_week_start"] == "2026-09-14T00:00:00Z"

    backwards = api_client.set_clock("2026-09-07T00:00:00Z", PLATFORM_ADMIN)
    validate_error(backwards, ApiErrorId.ERR_WEEK_CLOCK_BEHIND, 422)

    still = validate_success(api_client.set_clock("2026-09-21T00:00:00Z",
                                                  PLATFORM_ADMIN))
    assert still["current_utc"] == "2026-09-21T00:00:00Z"


def test_path_identifiers_are_resolved_left_to_right(api):
    """PRD §2.6: "the parent is resolved before the child. A path naming a route under a franchisee
    resolves the franchisee first, then the route, and a route that exists but belongs to a different
    franchisee is treated exactly as a missing route."
    PRD §2.6: "`ERR_FRANCHISEE_NOT_FOUND`,
    `ERR_ROUTE_NOT_FOUND`, `ERR_SHOP_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,"

    Design: Corner/validations/validation_route_and_shop_existence_validated_left_to_right
    """
    validate_error(api_client.get_franchisee(NON_EXISTENT_UUID, PLATFORM_ADMIN),
                   ApiErrorId.ERR_FRANCHISEE_NOT_FOUND, 404)
    validate_error(api_client.get_route(NON_EXISTENT_UUID, PLATFORM_ADMIN),
                   ApiErrorId.ERR_ROUTE_NOT_FOUND, 404)


def test_activation_requires_a_certified_franchisee(api):
    """PRD §3.1: "Activating a route moves `route_status` from `DRAFT` to `IN_SERVICE` and is refused unless four
    conditions hold: the route is currently `DRAFT`, its `zip_codes` array is non-empty, the owning
    franchisee is `CERTIFIED`, and its `inventory_invested_cents` is at least 1."
    PRD §2.10: "Certification gates three things and each refusal carries `ERR_FRANCHISEE_NOT_CERTIFIED` at HTTP
    status 409"

    Design: Corner/validations/validation_route_activation_requires_certified_franchisee
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee(training_points=10)
    enrolled = get_franchisee(franchisee["id"], franchisee["owner_headers"])
    assert enrolled["training_status"] == "ENROLLED"
    route = create_route(franchisee, route_code="R1")

    validate_error(advance_route(franchisee, route, "ACTIVATE"),
                   ApiErrorId.ERR_FRANCHISEE_NOT_CERTIFIED, 409)
    assert get_route(route["id"])["route_status"] == "DRAFT"

    validate_success(api_client.advance_training(
        franchisee["id"], {"action": "CERTIFY", "training_points": 45},
        franchisee["owner_headers"]))
    activated = validate_success(advance_route(franchisee, route, "ACTIVATE"))
    assert activated["route_status"] == "IN_SERVICE"


def test_trade_exit_is_refused_while_an_order_is_confirmed(api):
    """PRD §3.2: "A trade exit
    is refused while the technician still has a sales order in `CONFIRMED` status with unreserved stock —
    the request must name only technicians whose open orders are `DELIVERED` or beyond — and the refusal
    carries `ERR_TRADE_EXIT_OPEN_ORDER` at HTTP status 422."

    Design: Corner/validations/validation_trade_exit_refused_while_order_confirmed
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 1)])
    confirm_order(store["franchisee"], order, order["version"])

    exit_attempt = api_client.advance_technician_status(
        people["technician"]["id"], {"action": "EXIT_TRADE"}, MANAGER)
    validate_error(exit_attempt, ApiErrorId.ERR_TRADE_EXIT_OPEN_ORDER, 422)

    cancelled = validate_success(api_client.advance_sales_order(
        order["id"], {"action": "CANCEL"}, store["franchisee"]["rep_headers"]))
    assert cancelled["order_status"] == "CANCELLED"

    exited = validate_success(api_client.advance_technician_status(
        people["technician"]["id"], {"action": "EXIT_TRADE"}, MANAGER))
    assert exited["technician_status"] == "TRADE_EXITED"
    assert exited["current_shop_location_id"] is None


def test_warranty_filing_requires_a_delivered_order(api):
    """PRD §3.8: "The parent order must
    be `DELIVERED` or `SETTLED`, so a claim against a draft or merely confirmed order is refused before any
    credit arithmetic runs, with `ERR_WARRANTY_ORDER_NOT_DELIVERED` and HTTP status 422."

    Design: Corner/validations/validation_warranty_decision_requires_delivered_order
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 1)])
    confirm_order(store["franchisee"], order, order["version"])

    from test_helpers import file_claim
    early = file_claim(store["franchisee"], order, "idem-too-early-1",
                       apply_to_account_id=account["id"])
    validate_error(early, ApiErrorId.ERR_WARRANTY_ORDER_NOT_DELIVERED, 422)
    assert list_warranty_claims(store["franchisee"], {"order_id": order["id"]}) == []

    deliver_order(store["franchisee"], order)
    filed = validate_success(file_claim(store["franchisee"], order, "idem-after-delivery-1",
                                        apply_to_account_id=account["id"]), 201)
    assert filed["claim_status"] == "OPEN"
    assert filed["filed_iso_week"] == "2026-09-07T00:00:00Z"


def test_lease_application_requires_a_term(api):
    """PRD §3.3: "A lease application that
    omits `requested_term_months` is refused with `ERR_LEASE_TERM_REQUIRED` at HTTP status 422; a
    revolving application that carries a term is accepted, and the value is simply ignored."

    Design: Corner/validations/validation_lease_application_requires_term_months
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)

    payload = {
        "technician_id": people["technician"]["id"], "requested_limit_cents": 400000,
        "requested_kind": "LEASE", "employment_verified": True, "months_in_trade": 100,
        "prior_delinquency_count": 0, "decision_source": "FRANCHISEE",
    }
    validate_error(api_client.file_credit_application(people["shop"]["id"], payload,
                                                      store["franchisee"]["owner_headers"]),
                   ApiErrorId.ERR_LEASE_TERM_REQUIRED, 422)

    accepted = file_application(store["franchisee"], people["shop"], people["technician"],
                                requested_limit_cents=400_000, requested_kind="REVOLVING")
    assert accepted["requested_kind"] == "REVOLVING"
    assert accepted["application_status"] == "SUBMITTED"


def test_route_code_is_globally_unique(api):
    """PRD §2.9: "A `route_code` is globally unique across
    every route, so a create or update that reuses one is rejected with `ERR_ROUTE_CODE_DUPLICATE`."

    Design: Corner/validations/validation_duplicate_route_code_rejected
    """
    first = create_certified_franchisee(legal_name="First Franchisee LLC")
    second = create_certified_franchisee(legal_name="Second Franchisee LLC")
    create_route(first, route_code="R1")

    duplicate = api_client.create_route(
        second["id"],
        {"route_code": "R1", "route_tier": "B", "zip_codes": ["75002"], "visit_weekday": 2,
         "truck_label": "T-02", "inventory_invested_cents": 50000,
         "mix_plan": "TOOL_STORAGE", "territory_model": "FRANCHISEE_ASSUMED"},
        second["owner_headers"])
    validate_error(duplicate, ApiErrorId.ERR_ROUTE_CODE_DUPLICATE, 409)

    rows = validate_success(api_client.list_routes(second["owner_headers"],
                                                   {"franchisee_id": second["id"]}))
    assert rows == []


def test_shop_zip_must_belong_to_the_route_territory(api):
    """PRD §3.2: "The zip code must appear in the owning route's `zip_codes`; a shop
    whose zip code falls outside the territory is rejected with `ERR_SHOP_ZIP_NOT_IN_TERRITORY` and HTTP
    status 400."
    PRD §2.6: "Territory membership of a shop's zip code is twelfth, refused with `ERR_SHOP_ZIP_NOT_IN_TERRITORY` at
    HTTP status 400 when a shop is added to a route."

    Design: Corner/validations/validation_shop_zip_must_belong_to_route_territory
    """
    franchisee = create_certified_franchisee()
    narrow = create_route(franchisee, route_code="R1", zip_codes=["75001"])
    wide = create_route(franchisee, route_code="R2", zip_codes=["75001", "75002"],
                        visit_weekday=2, truck_label="T-02",
                        mix_plan="TOOL_STORAGE")

    refused = api_client.create_shop(
        narrow["id"], {"shop_name": "Out Of Territory Shop", "street_line": "5 Pine",
                       "zip_code": "75002"}, franchisee["owner_headers"])
    validate_error(refused, ApiErrorId.ERR_SHOP_ZIP_NOT_IN_TERRITORY, 400)

    rows = validate_success(api_client.list_shops(franchisee["owner_headers"],
                                                  {"route_id": narrow["id"]}))
    assert rows == []

    accepted = validate_success(api_client.create_shop(
        wide["id"], {"shop_name": "In Territory Shop", "street_line": "6 Pine",
                     "zip_code": "75002"}, franchisee["owner_headers"]), 201)
    assert accepted["zip_code"] == "75002"
    assert accepted["shop_status"] == "ACTIVE"
