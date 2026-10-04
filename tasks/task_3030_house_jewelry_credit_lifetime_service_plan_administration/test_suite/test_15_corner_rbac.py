"""RBAC claims: exclusive operations, shared operations, identity binding."""

from test_helpers import (
    ADMIN,
    ANALYST,
    ASSOCIATE,
    LOGICAL_CLOCK_START,
    MANAGER,
    api_client,
    get_success_data,
    make_customer_headers,
    reset_clock,
    setup_active_registration,
    setup_customer,
    setup_regulation,
    setup_registry_row,
    setup_repair,
    setup_store,
    setup_vendor_shop,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_store_manager_cannot_record_a_credit_decision(api, store_manager_headers):
    """PRD §2.1: "Each operation belongs to a set of permitted roles; a role that attempts an operation outside its permitted set — including a role attempting another role's exclusive capability — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "Decisioning is the `CreditAnalyst`'s exclusive ground."

    Design: Corner/rbac/store_manager_cannot_record_a_credit_decision
    """
    store, customer = _credit_environment()
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 250_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, ASSOCIATE), 201)

    response = api.decide_credit_application(
        application["id"], {"decision": "APPROVE_FULL"}, store_manager_headers)
    validate_error(response, "ERR_UNAUTHORIZED", expected_status=403)

    unchanged = get_success_data(api.get_credit_application(application["id"], ANALYST))
    assert unchanged["decision_status"] == "PENDING"
    customer_after = get_success_data(api.get_customer(customer["id"], ANALYST))
    assert customer_after["account_status"] == "NO_FILE"


def test_store_manager_exclusive_intake_succeeds_and_sales_associate_shared_create_succeeds(
        api, store_manager_headers, sales_associate_headers):
    """PRD §4: "| POST | `/repairs` | Intake a repair, pinning the loss liability at that instant | StoreManager, SalesAssociate |"
    PRD §4: "| POST | `/repairs/{id}/route` | Route a repair to its bench shop and freeze the turnaround commitment | StoreManager |"

    Design: Corner/rbac/store_manager_exclusive_intake_succeeds_and_sales_associate_shared_create_succeeds
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, diamond, bundle, purchase, registration = setup_active_registration()
    setup_vendor_shop(shop_code="JEWELCRAFT")

    intake = validate_success(api.create_repair({
        "customer_id": customer["id"], "store_id": store["id"],
        "diamond_id": diamond["id"], "registration_id": registration["id"],
        "failure_class": "SETTING", "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000, "declared_loss_liability_cents": 5_000,
    }, sales_associate_headers), 201)
    assert intake["repair_status"] == "INTAKE", (
        "the associate is within the shared intake permission"
    )

    routing = api.route_repair(intake["id"], sales_associate_headers)
    validate_error(routing, "ERR_UNAUTHORIZED", expected_status=403)

    unchanged = get_success_data(api.get_repair(intake["id"], store_manager_headers))
    assert unchanged["vendor_shop_code"] is None
    assert unchanged["repair_status"] == "INTAKE", "routing is StoreManager-exclusive"


def test_chain_admin_exclusive_configuration_is_refused_to_other_roles(
        api, chain_admin_headers, credit_analyst_headers):
    """PRD §2.1: "a `CustomerService` operator closing a customer file does so by naming the customer in the request, not by possessing a matching identifier."
    PRD §4: "| POST | `/credit-limit-registry-state` | Register a risk-registry pricing row for one (registry_key, credit_tier) | ChainAdmin |"

    Design: Corner/rbac/chain_admin_exclusive_configuration_is_refused_to_other_roles
    """
    reset_clock(LOGICAL_CLOCK_START)
    payload = {
        "registry_key": "NV", "credit_tier": "TIER_2", "base_limit_cents": 600_000,
        "min_down_payment_pct": 0.15, "registry_type": "STATE", "min_ticket_cents": 200_000,
    }
    refused = api.create_registry_row(payload, credit_analyst_headers)
    validate_error(refused, "ERR_UNAUTHORIZED", expected_status=403)

    validate_success(api.create_registry_row(payload, chain_admin_headers), 201)
    rows, meta = validate_paginated(api.list_registry_rows(
        chain_admin_headers, params={"registry_key": "NV"}))
    assert meta["total_count"] == 1, "the refused attempt left no row behind"
    assert rows[0]["credit_tier"] == "TIER_2"
    assert rows[0]["base_limit_cents"] == 600_000


def test_missing_role_header_is_unauthenticated_not_unauthorized(api, bad_role_headers):
    """PRD §2.1: "A request that omits either header, or whose `X-User-Role` does not name one of those six, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.14: "Priority 1 is authentication: `X-User-Role` and `X-User-ID` must be present and `X-User-Role` must name a declared role, else `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/rbac/missing_role_header_is_unauthenticated_not_unauthorized
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store(activate=False)

    response = api.activate_store(store["id"], bad_role_headers)
    validate_error(response, "ERR_UNAUTHENTICATED", expected_status=401)
    assert response.json()["data"]["error_id"] != "ERR_UNAUTHORIZED", (
        "authentication at priority 1 outranks authorization at priority 2"
    )
    unchanged = get_success_data(api.get_store(store["id"], ADMIN))
    assert unchanged["store_status"] == "OPEN"
    assert unchanged["version"] == 1


def test_customer_role_may_read_own_statements_only(api, customer_service_headers):
    """PRD §2.1: "A `Customer` acting on a credit application, a custom commission, or a statement that names a different customer is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §4: "| GET | `/billing-statements/{id}` | Get a billing statement | ChainAdmin, CreditAnalyst, CustomerService, Customer |"

    Design: Corner/rbac/customer_role_may_read_own_statements_only
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_store()
    customer = setup_customer(email="nina.ortiz@example.com")
    other = setup_customer(full_name="Ivan Petrov", email="ivan.petrov@example.com")
    statement = validate_success(api.create_billing_statement({
        "customer_id": customer["id"],
        "statement_period": "2026-09",
        "lines": [{"amount_cents": 250_000, "billable_pct": 1.0,
                   "line_status": "BILLABLE"}],
    }, customer_service_headers), 201)

    refused = api.get_billing_statement(statement["id"], make_customer_headers(other["id"]))
    validate_error(refused, "ERR_NOT_RESOURCE_OWNER", expected_status=403)

    owner_read = validate_success(api.get_billing_statement(
        statement["id"], make_customer_headers(customer["id"])), 200)
    assert owner_read["statement_status"] == "OPEN"
    assert owner_read["statement_balance_cents"] == 255_000


def _credit_environment():
    store = setup_store()
    setup_regulation()
    setup_registry_row(registry_key="TX", credit_tier="TIER_1", base_limit_cents=400_000,
                       min_down_payment_pct=0.20, min_ticket_cents=200_000)
    customer = setup_customer()
    return store, customer