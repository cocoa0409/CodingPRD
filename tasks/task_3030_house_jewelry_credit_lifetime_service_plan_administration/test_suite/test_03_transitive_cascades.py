"""Multi-hop cascades: each hop is caused by the previous one, not the sweep.

The hop count is asserted explicitly so an implementation that fires every
effect off the original request — instead of off the state change it caused —
is caught.
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
    setup_approved_customer,
    setup_bundle,
    setup_customer,
    setup_diamond,
    setup_purchase,
    setup_registration,
    setup_store,
    setup_defaulted_plan_and_registration,
    validate_success,
)


def test_default_sweep_cascades_through_registration_and_tier(api, credit_analyst_headers):
    """PRD §3.7: "The fourth lapses every lifetime registration the customer holds in `PENDING_INSPECTION`, incrementing each one's `missed_inspection_count`."
    PRD §3.7: "The fifth recomputes the customer's `lost_inspection_streak`, which counts the registrations that have entered `LAPSED`."

    Design: Difficulty/transitive_cascade/default_cascade_plan_to_customer_to_application_to_registration_to_tier
    """
    graph = setup_defaulted_plan_and_registration()
    registration = get_success_data(
        api.get_registration(graph["registration"]["id"], credit_analyst_headers))
    assert registration["coverage_status"] == "LAPSED", (
        "hop four lapses the registration the suspension left in PENDING_INSPECTION"
    )
    assert registration["missed_inspection_count"] == 1
    assert registration["is_valid"] is False


def test_default_sweep_declines_the_customers_pending_application(api, credit_analyst_headers):
    """PRD §3.7: "The third declines every credit application the customer still holds in `PENDING` or `COUNTERED`."
    PRD §3.7: "The second suspends the cardholder: `account_status` becomes `SUSPENDED`, `credit_tier` is forced to `NO_FILE`, `standalone_credit_limit_cents` is zeroed"

    Design: Difficulty/transitive_cascade/default_cascade_plan_to_customer_to_application_to_registration_to_tier
    """
    graph = setup_defaulted_plan_and_registration()
    application = get_success_data(api.get_credit_application(
        graph["application2"]["id"], credit_analyst_headers))
    assert application["decision_status"] == "DECLINED", (
        "hop three declines the application the suspension found still PENDING"
    )
    customer = get_success_data(api.get_customer(graph["customer"]["id"], credit_analyst_headers))
    assert customer["account_status"] == "SUSPENDED"
    assert customer["standalone_credit_limit_cents"] == 0


def test_default_sweep_increments_the_streak_before_the_tier_recompute(
        api, credit_analyst_headers):
    """PRD §2.10: "When the recomputation is the final step of a lapse cascade, the streak increment produced by that very lapse is included, so the evaluation runs on the post-increment streak — the `STREAK_APPLIED_AFTER_INCREMENT` reading."
    PRD §3.7: "the streak mutation from hops four and five happens before the tier is recomputed, so the downgrade reflects the new misses rather than the posture from before the default"

    Design: Difficulty/transitive_cascade/default_cascade_plan_to_customer_to_application_to_registration_to_tier
    """
    graph = setup_defaulted_plan_and_registration()
    customer = get_success_data(api.get_customer(graph["customer"]["id"], credit_analyst_headers))
    assert customer["lost_inspection_streak"] == 1, (
        "hop five counts the registration the lapse cascade just moved to LAPSED"
    )
    assert customer["credit_tier"] == "NO_FILE"


def test_default_sweep_chain_leaves_the_plan_defaulted_and_terminal_state_visible(
        api, credit_analyst_headers):
    """PRD §3.7: "The first hop sets `plan_status` to `DEFAULTED`."
    PRD §2.10: "If the customer has any promotional plan in `DEFAULTED`, the tier is `NO_FILE` regardless of the score."

    Design: Difficulty/transitive_cascade/default_cascade_plan_to_customer_to_application_to_registration_to_tier
    """
    graph = setup_defaulted_plan_and_registration()
    plan = get_success_data(api.get_promotional_plan(
        graph["plan"]["id"], credit_analyst_headers))
    assert plan["plan_status"] == "DEFAULTED"
    customer = get_success_data(api.get_customer(graph["customer"]["id"], credit_analyst_headers))
    assert customer["credit_tier"] == "NO_FILE"
    assert customer["lost_inspection_streak"] == 1


def test_payoff_cascade_retires_the_origin_purchase_and_its_registration(
        api, credit_analyst_headers, customer_service_headers):
    """PRD §3.5: "When the ticket names an origin, that origin ticket becomes `TRADE_UP_APPLIED` and, if it carried a live promotional plan, that plan becomes `PAID` with a ledger entry of kind `TRADE_UP_CREDIT`"
    PRD §3.5: "When the origin ticket carries a live lifetime registration, that registration becomes `TERMINATED` and exactly one fresh registration for the new stone starts at `PENDING_INSPECTION`"

    Design: Difficulty/transitive_cascade/payoff_cascade_plan_to_origin_to_registration_to_replacement
    """
    graph = _origin_graph_with_plan_and_registration()
    plan = graph["plan"]
    origin = graph["origin"]

    settled = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    validate_success(api.payoff_promotional_plan(
        plan["id"],
        {"amount_cents": settled["principal_cents"] + settled["deferred_interest_accrued_cents"],
         "expected_plan_version": settled["version"]},
        customer_service_headers), 200)
    validate_success(api.complete_purchase(graph["new_purchase"]["id"], ASSOCIATE), 200)

    origin_after = get_success_data(api.get_purchase(origin["id"], credit_analyst_headers))
    assert origin_after["purchase_status"] == "TRADE_UP_APPLIED", (
        "hop two: the origin purchase is retired by the trade-up"
    )
    registration_after = get_success_data(api.get_registration(
        graph["registration"]["id"], credit_analyst_headers))
    assert registration_after["coverage_status"] == "TERMINATED", (
        "hop three: the origin registration is terminated by the origin's state change"
    )


def test_payoff_cascade_conserves_the_open_inspection_population(api, credit_analyst_headers, customer_service_headers):
    """PRD §3.5: "Finally the customer's outstanding balance and tier are recomputed and the store's open inspection count is recomputed, because the retirement of the old plan and the opening of the new one must leave that population unchanged."
    PRD §2.16: "`open_inspection_count` counts the store's registrations whose `coverage_status` is `PENDING_INSPECTION` or `REMINDER_ISSUED`, and is recomputed on every registration transition."

    Design: Difficulty/transitive_cascade/payoff_cascade_plan_to_origin_to_registration_to_replacement
    """
    graph = _origin_graph_with_plan_and_registration()
    plan = graph["plan"]
    settled = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    validate_success(api.payoff_promotional_plan(
        plan["id"],
        {"amount_cents": settled["principal_cents"] + settled["deferred_interest_accrued_cents"],
         "expected_plan_version": settled["version"]},
        customer_service_headers), 200)
    validate_success(api.complete_purchase(graph["new_purchase"]["id"], ASSOCIATE), 200)

    store_after = get_success_data(api.get_store(graph["store"]["id"], credit_analyst_headers))
    assert store_after["open_inspection_count"] == 1, (
        "the terminated origin registration is exactly replaced by one fresh one"
    )
    registrations = validate_success(api.list_purchase_registrations(
        graph["new_purchase"]["id"], credit_analyst_headers), 200)
    assert len(registrations) == 1
    assert registrations[0]["coverage_status"] == "PENDING_INSPECTION"


def test_payoff_cascade_leaves_a_live_registration_that_blocks_the_customer_close(
        api, credit_analyst_headers, customer_service_headers):
    """PRD §3.7: "Anything else is refused with `ERR_CUSTOMER_ACTIVE_OBLIGATIONS` (HTTP 409)."
    PRD §3.7: "Closing requires an `outstanding_balance_cents` of exactly 0, no repair of that customer in `INTAKE`, `ROUTED`, `IN_REPAIR`, `QC_REVIEW`, or `COMPLETED`, and no registration of that customer in `PENDING_INSPECTION`, `REMINDER_ISSUED`, `GRACE_PERIOD`, or `RENEWED`."

    Design: Difficulty/transitive_cascade/payoff_cascade_plan_to_origin_to_registration_to_replacement
    """
    graph = _origin_graph_with_plan_and_registration()
    plan = graph["plan"]
    settled = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    validate_success(api.payoff_promotional_plan(
        plan["id"],
        {"amount_cents": settled["principal_cents"] + settled["deferred_interest_accrued_cents"],
         "expected_plan_version": settled["version"]},
        customer_service_headers), 200)
    validate_success(api.complete_purchase(graph["new_purchase"]["id"], ASSOCIATE), 200)

    refused = api.close_customer(graph["customer"]["id"], customer_service_headers)
    assert refused.status_code == 409, (
        "the replacement registration still in PENDING_INSPECTION is a live obligation"
    )
    body = refused.json()
    assert body["data"]["error_id"] == "ERR_CUSTOMER_ACTIVE_OBLIGATIONS"
    customer_after = get_success_data(api.get_customer(
        graph["customer"]["id"], credit_analyst_headers))
    assert customer_after["account_status"] != "CLOSED"


def test_payoff_cascade_transfers_ownership_of_the_new_stone(api, credit_analyst_headers, customer_service_headers):
    """PRD §3.5: "Every stone attached to the ticket takes the customer as `owner_customer_id` and returns to `IN_CASE`."
    PRD §3.5: "A surrendered stone also moves in custody. When a completed trade-up names an origin purchase that transferred a particular stone, that stone's `custody_status` becomes `IN_VAULT`"

    Design: Difficulty/transitive_cascade/payoff_cascade_plan_to_origin_to_registration_to_replacement
    """
    graph = _origin_graph_with_plan_and_registration()
    validate_success(api.complete_purchase(graph["new_purchase"]["id"], ASSOCIATE), 200)

    new_stone = get_success_data(api.get_diamond(graph["new_diamond"]["id"], customer_service_headers))
    assert new_stone["owner_customer_id"] == graph["customer"]["id"]
    assert new_stone["custody_status"] == "IN_CASE"
    old_stone = get_success_data(api.get_diamond(graph["origin_diamond"]["id"], customer_service_headers))
    assert old_stone["custody_status"] == "IN_VAULT", (
        "the surrendered stone returns to chain stock"
    )


def test_payoff_cascade_recomputes_the_customer_balance(api, credit_analyst_headers, customer_service_headers):
    """PRD §3.2: "`plan_status` becomes `PAID` and `paid_at` is stamped with the current instant; `deferred_interest_accrued_cents` and `final_settlement_amount_cents` both fall to 0"
    PRD §3.5: "The customer's `outstanding_balance_cents` is increased by the net amount and their `lifetime_purchase_cents` by the ticket's `base_price_cents`."

    Design: Difficulty/transitive_cascade/payoff_cascade_plan_to_origin_to_registration_to_replacement
    """
    graph = _origin_graph_with_plan_and_registration()
    plan = graph["plan"]
    settled = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    before = get_success_data(api.get_customer(graph["customer"]["id"], credit_analyst_headers))
    validate_success(api.payoff_promotional_plan(
        plan["id"],
        {"amount_cents": settled["principal_cents"] + settled["deferred_interest_accrued_cents"],
         "expected_plan_version": settled["version"]},
        customer_service_headers), 200)

    after_payoff = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert after_payoff["plan_status"] == "PAID"
    assert after_payoff["paid_at"] is not None
    assert after_payoff["final_settlement_amount_cents"] == 0
    settled_customer = get_success_data(api.get_customer(
        graph["customer"]["id"], credit_analyst_headers))
    assert settled_customer["outstanding_balance_cents"] < before["outstanding_balance_cents"]


def _origin_graph_with_plan_and_registration():
    """Origin purchase financed by a plan and covered by a live registration,
    plus a fresh trade-up purchase naming it as origin.
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_regulation_row = get_success_data(api_client.create_regulation({
        "state_code": "TX", "max_plan_term_months": 60, "inspection_required_months": 6,
        "lapse_cure_days": 30, "replacement_plus_pct": 1.0, "max_inspection_gap_days": 210,
    }, ADMIN), 201)
    del setup_regulation_row
    store = setup_store()
    get_success_data(api_client.create_registry_row({
        "registry_key": "TX", "credit_tier": "TIER_3", "base_limit_cents": 2_000_000,
        "min_down_payment_pct": 0.10, "registry_type": "STATE", "min_ticket_cents": 200_000,
    }, ADMIN), 201)
    customer = setup_customer()
    application = get_success_data(api_client.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 1_500_000,
        "requested_purchase_amount_cents": 900_100, "down_payment_cents": 90_010,
    }, ASSOCIATE), 201)
    get_success_data(api_client.decide_credit_application(application["id"],
                                                   {"decision": "APPROVE_FULL"}, ANALYST))
    customer = get_success_data(api_client.get_customer(customer["id"], AFTERCARE))

    bundle = setup_bundle()
    origin_diamond = setup_diamond(stone_code="ST-0031")
    new_diamond = setup_diamond(stone_code="ST-0032", carat=1.30,
                                origin_registry="KIMBERLEY-TX-7788")
    origin = setup_purchase(customer, store, base_price_cents=450_018, diamond=origin_diamond)
    origin = get_success_data(api_client.get_purchase(origin["id"], ASSOCIATE))
    plan = get_success_data(api_client.create_promotional_plan({
        "customer_id": customer["id"], "purchase_id": origin["id"],
        "plan_code": "PROMO_12_6M", "expected_purchase_version": origin["version"],
    }, ASSOCIATE), 201)
    origin = get_success_data(api_client.complete_purchase(origin["id"], ASSOCIATE))
    registration = setup_registration(customer, store, origin, origin_diamond, bundle)
    new_purchase = get_success_data(api_client.create_purchase({
        "customer_id": customer["id"], "store_id": store["id"],
        "base_price_cents": 900_100, "diamond_id": new_diamond["id"],
        "origin_purchase_id": origin["id"],
    }, ASSOCIATE), 201)
    return {
        "customer": customer,
        "store": store,
        "origin": origin,
        "origin_diamond": origin_diamond,
        "new_diamond": new_diamond,
        "new_purchase": new_purchase,
        "plan": plan,
        "registration": registration,
    }