"""Corner queue B — RBAC: role exclusivity and entity-backed ownership."""
from test_helpers import (
    CREDIT_OFFICER,
    MANAGER,
    PLATFORM_ADMIN,
    TEST_USERS,
    ApiErrorId,
    activate_route,
    advance_route,
    api_client,
    create_certified_franchisee,
    create_delivered_order,
    create_order,
    create_product,
    create_route,
    create_shop,
    create_technician,
    file_claim,
    get_account,
    get_franchisee,
    get_order,
    get_route,
    get_shop,
    get_technician,
    list_positions,
    order_line,
    set_clock,
    setup_account,
    setup_product_with_stock,
    setup_shop_and_technician,
    setup_storefront,
    validate_error,
    validate_success,
)


def test_route_sales_rep_cannot_suspend_a_route(api):
    """PRD §2.1: "`FranchiseManager`
    alone adjudicates route suspension, reinstatement and retirement"
    PRD §2.1: "a role absent from an endpoint's authorised list is refused with `ERR_UNAUTHORIZED`."

    Design: Corner/RBAC/rbac_route_sales_rep_cannot_suspend_a_route
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    activate_route(franchisee, route)

    denied = api_client.advance_route_status(route["id"], {"action": "SUSPEND"},
                                             franchisee["rep_headers"])
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert get_route(route["id"])["route_status"] == "IN_SERVICE"


def test_franchise_manager_may_suspend_and_reinstate(api):
    """PRD §2.1: "`FranchiseManager`
    alone adjudicates route suspension, reinstatement and retirement"
    PRD §3.1: "Both moves recompute the franchisee's `active_route_count`. Retirement may be requested from `DRAFT`"
    PRD §3.1: "Suspension is a `FranchiseManager` act that moves `IN_SERVICE` to `SUSPENDED` and cascades downward."
    PRD §3.1: "Reinstatement moves `SUSPENDED` back to `IN_SERVICE`"

    Design: Corner/RBAC/rbac_franchise_manager_permitted_to_reinstate_a_suspended_route
    """
    set_clock("2026-09-07T00:00:00Z")
    franchisee = create_certified_franchisee()
    route = create_route(franchisee, route_code="R1")
    activate_route(franchisee, route)

    suspended = validate_success(advance_route(franchisee, route, "SUSPEND"))
    assert suspended["route_status"] == "SUSPENDED"
    assert get_franchisee(franchisee["id"])["active_route_count"] == 0

    reinstated = validate_success(advance_route(franchisee, route, "REINSTATE"))
    assert reinstated["route_status"] == "IN_SERVICE"
    assert get_franchisee(franchisee["id"])["active_route_count"] == 1


def test_platform_admin_cannot_create_a_route(api):
    """PRD §2.1: "`PlatformAdmin` alone may set the logical clock and create
    or update products. `FranchiseOwner` alone may enrol, certify or recertify a franchisee, create a
    route, update route attributes, create a shop, onboard or update a technician"
    PRD §2.1: "This role owns the logical clock and the product catalogue and
    performs no business mutation of routes, accounts or orders."

    Design: Corner/RBAC/rbac_platform_admin_cannot_create_a_route
    """
    franchisee = create_certified_franchisee()
    denied = api_client.create_route(
        franchisee["id"],
        {"route_code": "R1", "route_tier": "A", "zip_codes": ["75001"], "visit_weekday": 1,
         "truck_label": "T-01", "inventory_invested_cents": 100000,
         "mix_plan": "DIAGNOSTIC_WEIGHTED", "territory_model": "FRANCHISEE_ASSUMED"},
        PLATFORM_ADMIN)
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED, 403)

    rows = validate_success(api_client.list_routes(PLATFORM_ADMIN,
                                                   {"franchisee_id": franchisee["id"]}))
    assert rows == []

    permitted = validate_success(api_client.create_product(
        {"sku": "P1", "product_name": "Torque Wrench", "category": "POWER_TOOLS",
         "unit_cost_cents": 12000, "retail_price_cents": 15000,
         "default_warranty_months": 12, "is_new_launch": False}, PLATFORM_ADMIN), 201)
    assert permitted["launch_status"] == "LIVE"


def test_warranty_admin_may_decide_but_not_file(api):
    """PRD §2.1: "`WarrantyAdmin` alone approves, rejects or reopens a warranty claim."
    PRD §2.1: "`RouteSalesRep` alone creates and edits sales orders, advances them through confirmation, delivery,
    settlement and cancellation, books a payment, collects a payment and files a warranty claim."

    Design: Corner/RBAC/rbac_warranty_admin_cannot_file_a_claim
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_delivered_order(store["franchisee"], store["route"],
                                   people["technician"], account, [order_line(product, 1)])
    claim = validate_success(file_claim(store["franchisee"], order, "idem-rbac-1",
                                        apply_to_account_id=account["id"]), 201)

    denied = file_claim_as(store, order, account, "idem-rbac-2")
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED, 403)

    from test_helpers import list_warranty_claims
    assert len(list_warranty_claims(store["franchisee"], {"order_id": order["id"]})) == 1

    submitted = validate_success(api_client.advance_warranty_claim(
        order["id"], claim["id"], {"action": "SUBMIT"},
        store["franchisee"]["rep_headers"]))
    assert submitted["claim_status"] == "SUBMITTED"

    approved = validate_success(api_client.advance_warranty_claim(
        order["id"], claim["id"], {"action": "APPROVE"},
        TEST_USERS["warranty_admin_headers"]))
    assert approved["claim_status"] == "APPROVED"


def file_claim_as(store, order, account, idempotency_key):
    return api_client.file_warranty_claim(
        order["id"],
        {"line_index": 0, "claim_kind": "CLAIM", "idempotency_key": idempotency_key,
         "apply_to_account_id": account["id"]},
        TEST_USERS["warranty_admin_headers"])


def test_technician_may_read_its_own_account_but_mutate_nothing(api):
    """PRD §2.1: "the role is entirely read-only — a `Technician` may read its own accounts, its own payment history and its
    own orders but mutates nothing."
    PRD §2.1: "ownership checks on a credit account compare the account's `technician_id` to `X-User-ID`"

    Design: Corner/RBAC/rbac_technician_cannot_mutate_own_account
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)

    own = validate_success(api_client.get_credit_account(
        account["id"], people["technician"]["headers"]))
    assert own["account_status"] == "ACTIVE"

    denied = api_client.advance_account_status(account["id"], {"action": "SUSPEND"},
                                               people["technician"]["headers"])
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED, 403)
    assert get_account(account["id"])["account_status"] == "ACTIVE"


def test_credit_officer_cannot_write_a_truck_stock_position(api):
    """PRD §2.1: "`FranchiseOwner` alone may ... create a replenishment
    order or an inventory position"
    PRD §2.1: "`CreditOfficer` alone reviews and decides franchisor-sourced applications, mints credit accounts and
    reverses a collected payment."

    Design: Corner/RBAC/rbac_credit_officer_cannot_suspend_own_route_stock_position
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    product = create_product(sku="P1", category="POWER_TOOLS", unit_cost_cents=12_000,
                             retail_price_cents=15_000)

    denied = api_client.write_inventory_position(
        store["route"]["id"], {"product_id": product["id"], "on_hand_qty": 5},
        CREDIT_OFFICER)
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED, 403)

    assert list_positions(store["franchisee"], store["route"]["id"], product["id"]) == []

    accepted = validate_success(api_client.write_inventory_position(
        store["route"]["id"], {"product_id": product["id"], "on_hand_qty": 5},
        store["franchisee"]["owner_headers"]), 201)
    assert accepted["on_hand_qty"] == 5


def test_franchise_manager_can_read_every_resource_type(api):
    """PRD §2.1: "Read
    access is broader: most role lists in Section 4 include the read endpoints a role legitimately needs"
    PRD §4: "GET | `/retail/credit-accounts` | List credit accounts. | PlatformAdmin, FranchiseOwner, FranchiseManager, CreditOfficer, Technician |"

    Design: Corner/RBAC/rbac_franchise_manager_can_read_every_resource_type
    """
    set_clock("2026-09-07T00:00:00Z")
    store = setup_storefront()
    people = setup_shop_and_technician(store)
    product = setup_product_with_stock(store, on_hand=10)
    account = setup_account(store["franchisee"], people["shop"], people["technician"],
                            requested_limit_cents=50_000)
    order = create_order(store["franchisee"], store["route"], people["technician"], account,
                         [order_line(product, 1)])

    assert get_route(store["route"]["id"], MANAGER)["route_status"] == "IN_SERVICE"
    assert get_account(account["id"])["account_status"] == "ACTIVE"
    assert get_order(order["id"], MANAGER)["order_status"] == "DRAFT"
    assert validate_success(api_client.list_launch_allocations(
        MANAGER, {"route_id": store["route"]["id"]})) == []
