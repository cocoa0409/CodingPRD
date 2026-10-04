"""Validation-priority pairs where two rules fail on one request.

Each test pins the lower-numbered priority's error identifier and states which
competing identifier was *not* returned, so an implementation that evaluates
the ladder in the wrong order is caught.
"""

from test_helpers import (
    ADMIN,
    AFTERCARE,
    ANALYST,
    ASSOCIATE,
    LOGICAL_CLOCK_START,
    MANAGER,
    api_client,
    get_success_data,
    reset_clock,
    setup_bundle,
    setup_customer,
    setup_diamond,
    setup_purchase,
    setup_registration,
    setup_store,
    validate_error,
    validate_success,
)


def test_regulation_terms_outrank_the_credit_ceiling_on_decision(api, credit_analyst_headers):
    """PRD §2.14: "Priority 6 is the regulation prerequisite — the governing regulation row for the store's state must exist before state and business rules run — `ERR_REGULATION_TERMS_VIOLATION` (422)."
    PRD §2.6: "Origination carries a hard prerequisite. The governing regulation row for the store's state must exist before any state or business rule is evaluated on a purchase completion, a registration, or a credit decision; if it does not, the request is refused with `ERR_REGULATION_TERMS_VIOLATION` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/regulation_terms_outrank_credit_limit_on_decision
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store(state_code="ZZ")
    customer = setup_customer(state_code="ZZ")
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"],
        "store_id": store["id"],
        "requested_limit_cents": 2_000_000,
        "requested_purchase_amount_cents": 1_900_000,
        "down_payment_cents": 190_000,
    }, ASSOCIATE), 201)
    version_before = application["version"]

    response = api.decide_credit_application(
        application["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers)
    validate_error(response, "ERR_REGULATION_TERMS_VIOLATION", expected_status=422)
    body = response.json()
    assert body["data"]["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED", (
        "the fiscal ceiling at priority 20 is not the reported identifier"
    )
    assert body["data"]["error_id"] != "ERR_REGISTRY_ROW_MISSING", (
        "registry resolvability at priority 19 is not the reported identifier either"
    )

    unchanged = get_success_data(api.get_credit_application(
        application["id"], credit_analyst_headers))
    assert unchanged["decision_status"] == "PENDING"
    assert unchanged["version"] == version_before


def test_regulation_prerequisite_outranks_the_state_and_business_rules(api, credit_analyst_headers):
    """PRD §2.14: "in particular the compliance prerequisite at priority 6 is evaluated before any state or business rule, and the frozen-credit hazard at priority 8 outranks every data-validity and fiscal check later in the ladder."
    PRD §2.14: "Priority 3 is existence: the path resource must exist, and on a flat entity the foreign-key fields named in the input are resolved left to right in the order the endpoint's input list declares them; a failure is `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Difficulty/priority_pair_validation_conflict/regulation_terms_outrank_credit_limit_on_decision
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store(state_code="ZZ")
    customer = setup_customer(state_code="ZZ")
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"],
        "store_id": store["id"],
        "requested_limit_cents": 2_000_000,
        "requested_purchase_amount_cents": 1_900_000,
        "down_payment_cents": 190_000,
    }, ASSOCIATE), 201)

    response = api.decide_credit_application(
        application["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers)
    assert response.status_code == 422, (
        "the missing regulation row is a compliance refusal, not a state or existence error"
    )
    assert response.json()["data"]["error_id"] == "ERR_REGULATION_TERMS_VIOLATION"
    unchanged = get_success_data(api.get_credit_application(
        application["id"], credit_analyst_headers))
    assert unchanged["decision_status"] == "PENDING"


def test_frozen_credit_hazard_outranks_terminated_plan_terms_on_complete(
        api, sales_associate_headers):
    """PRD §3.7: "Completing a purchase, opening a promotional plan, opening a custom commission, and releasing a commission to production are all refused with `ERR_CREDIT_FROZEN` (HTTP 422)"
    PRD §3.7: "and this hazard check is deliberately placed above every data-validity and fiscal check that would otherwise fire on the same request, so a frozen account surfaces as frozen rather than as a limit problem."

    Design: Difficulty/priority_pair_validation_conflict/credit_frozen_hazard_outranks_terminated_plan_terms_on_complete
    """
    graph = _frozen_customer_with_terminated_registration()
    response = api.complete_purchase(graph["purchase"]["id"], sales_associate_headers)
    validate_error(response, "ERR_CREDIT_FROZEN", expected_status=422)
    assert response.json()["data"]["error_id"] != "ERR_PLAN_TERMS_UNSATISFIED", (
        "the referential plan-terms gate at priority 16 is not the identifier reported"
    )


def test_frozen_credit_hazard_leaves_the_purchase_unfinished(api, sales_associate_headers):
    """PRD §2.14: "Priority 8 is the frozen-credit hazard: credit is frozen while any promotional plan of the customer is `DEFAULTED`, giving `ERR_CREDIT_FROZEN` (422), and this outranks every data-validity and fiscal check on the same request."
    PRD §3.7: "While any plan of a customer sits in `DEFAULTED`, credit is frozen across the chain for that customer."

    Design: Difficulty/priority_pair_validation_conflict/credit_frozen_hazard_outranks_terminated_plan_terms_on_complete
    """
    graph = _frozen_customer_with_terminated_registration()
    before = get_success_data(api.get_purchase(graph["purchase"]["id"], sales_associate_headers))
    response = api.complete_purchase(graph["purchase"]["id"], sales_associate_headers)
    assert response.status_code == 422
    after = get_success_data(api.get_purchase(graph["purchase"]["id"], sales_associate_headers))
    assert after["purchase_status"] == before["purchase_status"], (
        "the refusal leaves the purchase exactly as it was"
    )


def test_frozen_credit_refusal_does_not_touch_unrelated_child_collections(
        api, sales_associate_headers, store_manager_headers):
    """PRD §3.4: "A registration already `TERMINATED` or `VOID` cannot be named, and neither can one whose terms no longer cover the stone under repair — both are `ERR_PLAN_TERMS_UNSATISFIED` (HTTP 422)."
    PRD §3.7: "The third declines every credit application the customer still holds in `PENDING` or `COUNTERED`."

    Design: Difficulty/priority_pair_validation_conflict/credit_frozen_hazard_outranks_terminated_plan_terms_on_complete
    """
    graph = _frozen_customer_with_terminated_registration()
    api.complete_purchase(graph["purchase"]["id"], sales_associate_headers)
    repairs = validate_success(api.list_registration_repairs(
        graph["registration"]["id"], store_manager_headers), 200)
    assert repairs == [], "the refused completion created no repairs"


def _frozen_customer_with_terminated_registration():
    """Customer with a DEFAULTED plan (credit frozen) whose pinned registration
    is already TERMINATED, sitting on the purchase they are trying to complete.
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    get_success_data(api_client.create_regulation({
        "state_code": "TX", "max_plan_term_months": 60, "inspection_required_months": 6,
        "lapse_cure_days": 30, "replacement_plus_pct": 1.0, "max_inspection_gap_days": 210,
    }, ADMIN), 201)
    get_success_data(api_client.create_registry_row({
        "registry_key": "TX", "credit_tier": "TIER_3", "base_limit_cents": 2_000_000,
        "min_down_payment_pct": 0.10, "registry_type": "STATE", "min_ticket_cents": 200_000,
    }, ADMIN), 201)
    customer = setup_customer()
    application = get_success_data(api_client.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 1_000_000,
        "requested_purchase_amount_cents": 450_018, "down_payment_cents": 45_002,
    }, ASSOCIATE), 201)
    get_success_data(api_client.decide_credit_application(application["id"],
                                                   {"decision": "APPROVE_FULL"}, ANALYST))
    customer = get_success_data(api_client.get_customer(customer["id"], AFTERCARE))

    bundle = setup_bundle()
    diamond = setup_diamond(stone_code="ST-0041")
    purchase = setup_purchase(customer, store, base_price_cents=450_018, diamond=diamond)
    purchase = get_success_data(api_client.get_purchase(purchase["id"], ASSOCIATE))
    plan = get_success_data(api_client.create_promotional_plan({
        "customer_id": customer["id"], "purchase_id": purchase["id"],
        "plan_code": "PROMO_12_6M", "expected_purchase_version": purchase["version"],
    }, ASSOCIATE), 201)
    registration = setup_registration(customer, store, purchase, diamond, bundle)
    get_success_data(api_client.terminate_registration(registration["id"], MANAGER))
    registration = get_success_data(api_client.get_registration(registration["id"], MANAGER))

    reset_clock("2027-12-15T00:00:00Z")
    get_success_data(api_client.default_plans_due(ANALYST))
    plan = get_success_data(api_client.get_promotional_plan(plan["id"], ANALYST))
    assert plan["plan_status"] == "DEFAULTED"
    assert registration["coverage_status"] == "TERMINATED"
    return {"customer": customer, "store": store, "purchase": purchase,
            "plan": plan, "registration": registration, "diamond": diamond}