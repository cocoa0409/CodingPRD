"""Validation-surface claims: violations, satisfied checks, filtering."""

from test_helpers import (
    ADMIN,
    AFTERCARE,
    ANALYST,
    ASSOCIATE,
    LOGICAL_CLOCK_START,
    MANAGER,
    make_customer_headers,
    api_client,
    get_success_data,
    reset_clock,
    setup_customer,
    setup_plan_environment,
    setup_regulation,
    setup_registry_row,
    setup_store,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_duplicate_customer_email_returns_duplicate_email(api, sales_associate_headers):
    """PRD §3.1: "Email is a unique contact key: a second customer file carrying an email already held by another customer is refused with `ERR_DUPLICATE_EMAIL` (HTTP 409)."
    PRD §2.14: "Priority 27 is code uniqueness across stones, bundles, and shops, `ERR_DUPLICATE_STONE_CODE` (409)."

    Design: Corner/validations/duplicate_customer_email_returns_duplicate_email
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_customer(full_name="Ivan Petrov", email="ivan.petrov@example.com", state_code="NV")

    duplicate = api.create_customer({
        "full_name": "Ivan P Duplicate",
        "email": "ivan.petrov@example.com",
        "state_code": "NV",
    }, sales_associate_headers)
    validate_error(duplicate, "ERR_DUPLICATE_EMAIL", expected_status=409)

    fresh = validate_success(api.create_customer({
        "full_name": "Ivan P Fresh",
        "email": "ivan.fresh@example.com",
        "state_code": "NV",
    }, sales_associate_headers), 201)
    assert fresh["email"] == "ivan.fresh@example.com"

    rows, meta = validate_paginated(api.list_customers(sales_associate_headers))
    assert meta["total_count"] == 2, "the duplicate was not persisted"


def test_belonging_check_passes_for_the_owning_customer(api, credit_analyst_headers):
    """PRD §3.1: "Accepting requires the application to be `COUNTERED` and the instant to be at or before `expires_at`; it moves `decision_status` to `APPROVED` and then applies the customer-side effects of a full approval"
    PRD §2.1: "ownership checks on any resource that references a `Customer` compare the resource's customer foreign-key field (the resource's `customer_id`) to `X-User-ID`."

    Design: Corner/validations/belonging_check_passes_for_the_owning_customer
    """
    store, customer = _countered_environment()
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 400_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, ASSOCIATE), 201)
    get_success_data(api.decide_credit_application(
        application["id"], {"decision": "APPROVE_COUNTERED"}, credit_analyst_headers))

    accepted = validate_success(api.accept_credit_application(
        application["id"], make_customer_headers(customer["id"])), 200)
    assert accepted["decision_status"] == "APPROVED"
    assert accepted["decision_tier"] == "TIER_1"
    assert accepted["approved_limit_cents"] == 400_000

    refreshed = get_success_data(api.get_customer(customer["id"], credit_analyst_headers))
    assert refreshed["account_status"] == "OPEN"
    assert refreshed["standalone_credit_limit_cents"] == 400_000


def test_countered_offer_acceptance_is_refused_for_a_non_owner(api, credit_analyst_headers):
    """PRD §2.1: "A `Customer` acting on a credit application, a custom commission, or a statement that names a different customer is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §2.14: "Priority 12 is resource ownership, `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/validations/countered_offer_acceptance_is_refused_for_a_non_owner
    """
    store, customer = _countered_environment()
    other = setup_customer(full_name="Ivan Petrov", email="ivan.petrov@example.com")
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 250_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, ASSOCIATE), 201)
    countered = get_success_data(api.decide_credit_application(
        application["id"], {"decision": "APPROVE_COUNTERED"}, credit_analyst_headers))

    response = api.accept_credit_application(
        application["id"], make_customer_headers(other["id"]))
    validate_error(response, "ERR_NOT_RESOURCE_OWNER", expected_status=403)

    unchanged = get_success_data(api.get_credit_application(
        application["id"], credit_analyst_headers))
    assert unchanged["decision_status"] == "COUNTERED"
    assert unchanged["version"] == countered["version"]
    other_after = get_success_data(api.get_customer(other["id"], credit_analyst_headers))
    assert other_after["account_status"] == "NO_FILE"


def test_counteroffer_changes_nothing_on_the_customer_until_accepted(
        api, credit_analyst_headers):
    """PRD §3.1: "It sets `decision_tier` to `TIER_1` and `approved_limit_cents` to that row's `base_limit_cents`, recomputes `min_down_payment_required_cents` at the `TIER_1` percentage, and recomputes the shortfall against it — but it changes nothing on the customer file."
    PRD §3.1: "The counteroffer binds only the application row until the customer accepts."

    Design: Corner/validations/belonging_check_passes_for_the_owning_customer
    """
    store, customer = _countered_environment()
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 250_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, ASSOCIATE), 201)
    countered = validate_success(api.decide_credit_application(
        application["id"], {"decision": "APPROVE_COUNTERED"}, credit_analyst_headers), 200)
    assert countered["decision_status"] == "COUNTERED"

    unchanged = get_success_data(api.get_customer(customer["id"], credit_analyst_headers))
    assert unchanged["account_status"] == "NO_FILE"
    assert unchanged["standalone_credit_limit_cents"] == 0


def test_a_second_live_plan_on_the_same_purchase_is_refused(api, sales_associate_headers):
    """PRD §3.2: "Only one live plan may reference a ticket: a second non-terminal plan naming the same `purchase_id` is refused with `ERR_PLAN_ALREADY_EXISTS` (HTTP 409)."
    PRD §2.14: "Priority 18 is the one-live-plan-per-purchase rule, `ERR_PLAN_ALREADY_EXISTS` (409)."

    Design: Corner/validations/unpaid_plan_shortfall_on_default_sweep_is_flagged_by_plan_status
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code="PROMO_12_6M", base_price_cents=450_000)
    current = get_success_data(api.get_purchase(purchase["id"], sales_associate_headers))

    second = api.create_promotional_plan({
        "customer_id": customer["id"], "purchase_id": purchase["id"],
        "plan_code": "PROMO_18_6M", "expected_purchase_version": current["version"],
    }, sales_associate_headers)
    validate_error(second, "ERR_PLAN_ALREADY_EXISTS", expected_status=409)

    rows, meta = validate_paginated(api.list_promotional_plans(
        sales_associate_headers, params={"purchase_id": purchase["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["plan_status"] == "ACCRUING"
    assert rows[0]["plan_code"] == "PROMO_12_6M"


def test_the_first_plan_still_reads_as_accruing_after_the_refusal(api, sales_associate_headers):
    """PRD §3.2: "The financed ticket's `purchase_status` moves from `PENDING` to `FINANCED` — the transition requires the ticket's `customer_id` to equal the plan's"
    PRD §2.5: "The financed principal is `principal_cents`: the financed purchase's `net_amount_cents`"

    Design: Corner/validations/unpaid_plan_shortfall_on_default_sweep_is_flagged_by_plan_status
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code="PROMO_12_6M", base_price_cents=450_000)
    current = get_success_data(api.get_purchase(purchase["id"], sales_associate_headers))
    validate_error(api.create_promotional_plan({
        "customer_id": customer["id"], "purchase_id": purchase["id"],
        "plan_code": "PROMO_18_6M", "expected_purchase_version": current["version"],
    }, sales_associate_headers), "ERR_PLAN_ALREADY_EXISTS", expected_status=409)

    ticket = get_success_data(api.get_purchase(purchase["id"], sales_associate_headers))
    assert ticket["purchase_status"] == "FINANCED"
    plan_after = get_success_data(api.get_promotional_plan(plan["id"], sales_associate_headers))
    assert plan_after["plan_status"] == "ACCRUING"
    assert plan_after["principal_cents"] == 450_000


def test_customers_list_filter_is_applied_before_pagination(api, customer_service_headers,
                                                            credit_analyst_headers):
    """PRD §2.3: "Unless a rule elsewhere in this document says otherwise, list endpoints return resources sorted by creation timestamp (`created_at`) in ascending order."
    PRD §3.1: "Intake runs the chain's counter credit pricing — `credit_limit_registry_pricing` — immediately and stamps the resulting `policy_tier` on the row, sets `decision_status` to `PENDING`"

    Design: Corner/validations/customers_list_filter_is_applied_before_pagination
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    setup_regulation()
    setup_registry_row(registry_key="TX", credit_tier="TIER_1", base_limit_cents=2_000_000,
                       min_down_payment_pct=0.10)
    customer = setup_customer(email="nina.ortiz@example.com")
    setup_customer(full_name="Ivan Petrov", email="ivan.petrov@example.com")
    setup_customer(full_name="Greta Lind", email="greta.lind@example.com")

    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 450_000,
        "requested_purchase_amount_cents": 450_000, "down_payment_cents": 45_000,
    }, ASSOCIATE), 201)
    get_success_data(api.decide_credit_application(
        application["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers))

    rows, meta = validate_paginated(api.list_customers(
        customer_service_headers, params={"account_status": "OPEN"}))
    assert len(rows) == 1, "the filter narrows the set before total_count is computed"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == customer["id"]


def test_the_unfiltered_customer_list_still_reports_every_row(api, customer_service_headers,
                                                              credit_analyst_headers):
    """PRD §2.3: "`limit` caps how many items are returned; when omitted it defaults to 10, and it may be set no lower than 1 and no higher than 100."
    PRD §2.3: "`offset` skips that many items from the front of the result and defaults to 0."

    Design: Corner/validations/customers_list_filter_is_applied_before_pagination
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    setup_regulation()
    setup_registry_row(registry_key="TX", credit_tier="TIER_1", base_limit_cents=2_000_000,
                       min_down_payment_pct=0.10)
    customer = setup_customer(email="nina.ortiz@example.com")
    setup_customer(full_name="Ivan Petrov", email="ivan.petrov@example.com")
    setup_customer(full_name="Greta Lind", email="greta.lind@example.com")
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 450_000,
        "requested_purchase_amount_cents": 450_000, "down_payment_cents": 45_000,
    }, ASSOCIATE), 201)
    get_success_data(api.decide_credit_application(
        application["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers))

    rows, meta = validate_paginated(api.list_customers(customer_service_headers))
    assert meta["total_count"] == 3, "the unfiltered set counts every customer"
    assert len(rows) == 3
    assert meta["has_more"] is False


def test_closing_the_counteroffer_declines_it_and_leaves_the_file_untouched(
        api, credit_analyst_headers):
    """PRD §3.1: "Declining the counteroffer moves `decision_status` to `DECLINED` and leaves every customer field exactly as it was, `account_status` included, and does not consult the validity window at all."
    PRD §2.14: "Priority 12 is resource ownership, `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/validations/belonging_check_passes_for_the_owning_customer
    """
    store, customer = _countered_environment()
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 250_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, ASSOCIATE), 201)
    get_success_data(api.decide_credit_application(
        application["id"], {"decision": "APPROVE_COUNTERED"}, credit_analyst_headers))

    declined = validate_success(api.decline_credit_application(
        application["id"], make_customer_headers(customer["id"])), 200)
    assert declined["decision_status"] == "DECLINED"
    unchanged = get_success_data(api.get_customer(customer["id"], credit_analyst_headers))
    assert unchanged["account_status"] == "NO_FILE"
    assert unchanged["standalone_credit_limit_cents"] == 0


def test_a_customer_cannot_accept_another_customers_counteroffer(api, credit_analyst_headers):
    """PRD §2.1: "This check is enforced on accepting a countered offer, declining a countered offer, requesting a CAD revision, approving a CAD document, and cancelling an own commission."
    PRD §2.1: "The `Customer` role is the exception, and it is backed by an entity."

    Design: Corner/validations/countered_offer_acceptance_is_refused_for_a_non_owner
    """
    store, customer = _countered_environment()
    other = setup_customer(full_name="Ivan Petrov", email="ivan.petrov@example.com")
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 250_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, ASSOCIATE), 201)
    get_success_data(api.decide_credit_application(
        application["id"], {"decision": "APPROVE_COUNTERED"}, credit_analyst_headers))

    refused = api.decline_credit_application(
        application["id"], make_customer_headers(other["id"]))
    validate_error(refused, "ERR_NOT_RESOURCE_OWNER", expected_status=403)
    unchanged = get_success_data(api.get_credit_application(
        application["id"], credit_analyst_headers))
    assert unchanged["decision_status"] == "COUNTERED"


def _countered_environment():
    """Store ACTIVE with a TIER_1 row at 20% and a customer on file."""
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    setup_regulation()
    setup_registry_row(registry_key="TX", credit_tier="TIER_1", base_limit_cents=400_000,
                       min_down_payment_pct=0.20, min_ticket_cents=200_000)
    customer = setup_customer()
    return store, customer