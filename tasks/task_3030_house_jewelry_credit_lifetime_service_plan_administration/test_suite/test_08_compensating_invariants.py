"""Conserved quantities: round trips must leave the totals where they started.

Each test replays a forward event and its compensating reverse, then compares
the conserved quantity before and after — a drift of even one cent fails.
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
    validate_success,
)


def test_payoff_records_a_decreasing_ledger_entry_at_the_settlement_amount(
        api, customer_service_headers):
    """PRD §3.2: "The payment appends a ledger entry whose `entry_kind` is `LUMPSUM_PAYOFF`, whose `direction` is `DECREASE`, whose `amount_cents` is the submitted amount, whose `adjustment_cents` is the negative of that amount, and whose `reference_bucket` is `PROMOTIONAL`"
    PRD §2.5: "`total_paid_cents` accumulates every payment applied to the plan, whether an installment or a lump-sum payoff."

    Design: Difficulty/compensating_invariant/payoff_and_reinstatement_leave_plan_balance_undrifted
    """
    customer, store, purchase, plan = _plan_with_accrual()
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    amount = settled["principal_cents"] + settled["deferred_interest_accrued_cents"]

    paid = validate_success(api.payoff_promotional_plan(
        plan["id"], {"amount_cents": amount, "expected_plan_version": settled["version"]},
        customer_service_headers), 200)
    assert paid["plan_status"] == "PAID"

    entries = validate_success(api.list_plan_ledger_entries(
        plan["id"], customer_service_headers), 200)
    assert len(entries) == 1
    assert entries[0]["entry_kind"] == "LUMPSUM_PAYOFF"
    assert entries[0]["direction"] == "DECREASE"
    assert entries[0]["amount_cents"] == amount
    assert entries[0]["reference_bucket"] == "PROMOTIONAL"


def test_the_payoff_ledger_replays_the_settlement_amount_exactly(
        api, customer_service_headers):
    """PRD §2.5: "`total_paid_cents` accumulates every payment applied to the plan, whether an installment or a lump-sum payoff."
    PRD §3.2: "The amount is added to `total_paid_cents`; `plan_status` becomes `PAID` and `paid_at` is stamped with the current instant"

    Design: Difficulty/compensating_invariant/payoff_and_reinstatement_leave_plan_balance_undrifted
    """
    customer, store, purchase, plan = _plan_with_accrual()
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    amount = settled["principal_cents"] + settled["deferred_interest_accrued_cents"]

    paid = validate_success(api.payoff_promotional_plan(
        plan["id"], {"amount_cents": amount, "expected_plan_version": settled["version"]},
        customer_service_headers), 200)
    entries = validate_success(api.list_plan_ledger_entries(
        plan["id"], customer_service_headers), 200)
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == amount, (
        "the ledger entry replays the settlement amount the plan carried"
    )
    assert entries[0]["adjustment_cents"] == -amount
    assert paid["total_paid_cents"] == amount
    assert paid["plan_status"] == "PAID"


def test_payoff_clears_the_settlement_and_refunds_the_merchant_fee(
        api, customer_service_headers, credit_analyst_headers):
    """PRD §3.2: "A payoff on an `ACCRUING` plan requires the current instant to be at or before `simplicity_expires_at`"
    PRD §3.2: "`plan_status` becomes `PAID` and `paid_at` is stamped with the current instant; `deferred_interest_accrued_cents` and `final_settlement_amount_cents` both fall to 0"

    Design: Difficulty/compensating_invariant/payoff_and_reinstatement_leave_plan_balance_undrifted
    """
    customer, store, purchase, plan = _plan_with_accrual()
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    amount = settled["principal_cents"] + settled["deferred_interest_accrued_cents"]
    paid = validate_success(api.payoff_promotional_plan(
        plan["id"], {"amount_cents": amount, "expected_plan_version": settled["version"]},
        customer_service_headers), 200)

    assert paid["final_settlement_amount_cents"] == 0
    assert paid["deferred_interest_accrued_cents"] == 0
    assert paid["merchant_deferral_fee_cents"] == 0, (
        "the merchant's deferral fee is refunded on payoff-by-date"
    )
    assert paid["version"] > settled["version"], "the plan's version increments by one"


def test_the_customer_balance_is_reduced_by_the_settlement_amount(
        api, customer_service_headers):
    """PRD §2.10: "`outstanding_balance_cents` is the sum of `adjustment_cents` over the customer's payoff-ledger entries, plus, for every promotional plan that is not yet `PAID`, the `installment_amount_cents` of its current open quarter."
    PRD §3.2: "The plan's `version` increments by one and the cardholder's `outstanding_balance_cents`, utilization band, and recomputed tier all follow."

    Design: Difficulty/compensating_invariant/payoff_and_reinstatement_leave_plan_balance_undrifted
    """
    customer, store, purchase, plan = _plan_with_accrual()
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    before = get_success_data(api.get_customer(customer["id"], customer_service_headers))
    amount = settled["principal_cents"] + settled["deferred_interest_accrued_cents"]

    validate_success(api.payoff_promotional_plan(
        plan["id"], {"amount_cents": amount, "expected_plan_version": settled["version"]},
        customer_service_headers), 200)
    after = get_success_data(api.get_customer(customer["id"], customer_service_headers))
    assert after["outstanding_balance_cents"] <= before["outstanding_balance_cents"], (
        "a settled plan stops contributing its open-quarter installment to the balance"
    )
    plan_after = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    assert plan_after["plan_status"] == "PAID"


def test_the_trade_up_swap_conserves_the_open_inspection_population(
        api, sales_associate_headers, store_manager_headers):
    """PRD §3.5: "When the origin ticket carries a live lifetime registration, that registration becomes `TERMINATED` and exactly one fresh registration for the new stone starts at `PENDING_INSPECTION`"
    PRD §3.5: "Finally the customer's outstanding balance and tier are recomputed and the store's open inspection count is recomputed, because the retirement of the old plan and the opening of the new one must leave that population unchanged."

    Design: Difficulty/compensating_invariant/replacement_registration_swap_conserves_the_open_inspection_population
    """
    graph = _trade_up_with_registration()
    before = get_success_data(api.get_store(graph["store"]["id"], sales_associate_headers))
    assert before["open_inspection_count"] == 1

    validate_success(api.complete_purchase(graph["new_purchase"]["id"], sales_associate_headers), 200)

    origin_registration = get_success_data(api.get_registration(
        graph["registration"]["id"], sales_associate_headers))
    assert origin_registration["coverage_status"] == "TERMINATED"
    replacements = validate_success(api.list_purchase_registrations(
        graph["new_purchase"]["id"], store_manager_headers), 200)
    assert len(replacements) == 1
    assert replacements[0]["coverage_status"] == "PENDING_INSPECTION"

    after = get_success_data(api.get_store(graph["store"]["id"], sales_associate_headers))
    assert after["open_inspection_count"] == 1, (
        "the swap terminates one registration and opens exactly one, so the count is unchanged"
    )


def test_the_conserved_registration_population_equals_one_before_and_after(
        api, sales_associate_headers):
    """PRD §2.16: "`open_inspection_count` counts the store's registrations whose `coverage_status` is `PENDING_INSPECTION` or `REMINDER_ISSUED`, and is recomputed on every registration transition."
    PRD §3.4: "The lifetime registration that covered the damaged diamond becomes `TERMINATED`."

    Design: Difficulty/compensating_invariant/replacement_registration_swap_conserves_the_open_inspection_population
    """
    graph = _trade_up_with_registration()
    validate_success(api.complete_purchase(graph["new_purchase"]["id"], sales_associate_headers), 200)

    registrations = validate_success(api.list_registrations(
        sales_associate_headers, params={"store_id": graph["store"]["id"]}), 200)
    open_states = {"PENDING_INSPECTION", "REMINDER_ISSUED"}
    conserved = [r for r in registrations if r["coverage_status"] in open_states]
    assert len(conserved) == 1, (
        "the conserved quantity C equals 1 both before and after the swap"
    )
    assert len(registrations) == 2, "one TERMINATED and one PENDING_INSPECTION row"


def test_the_swap_drains_the_population_to_zero_with_no_negative_residue(
        api, sales_associate_headers, customer_service_headers):
    """PRD §3.7: "every registration of that customer in `ACTIVE` becomes `TERMINATED`, every one of their applications still in `PENDING` becomes `DECLINED`, and the open inspection count is recomputed for each store affected."
    PRD §3.3: "The result is `TERMINATED`, with `is_valid` false, every scheduled visit of the registration marked `NO_SHOW`, and the store's `open_inspection_count` decremented."

    Design: Difficulty/compensating_invariant/replacement_registration_swap_conserves_the_open_inspection_population
    """
    graph = _trade_up_with_registration()
    validate_success(api.complete_purchase(graph["new_purchase"]["id"], sales_associate_headers), 200)
    replacement = validate_success(api.list_purchase_registrations(
        graph["new_purchase"]["id"], customer_service_headers), 200)[0]
    validate_success(api.terminate_registration(
        replacement["id"], customer_service_headers), 200)

    store_after = get_success_data(api.get_store(graph["store"]["id"], customer_service_headers))
    assert store_after["open_inspection_count"] == 0, (
        "the population drains to exactly 0 with no negative residue"
    )


def _plan_with_accrual():
    """A PROMO_12_6M plan on a 450,000 ticket whose deferral has accrued."""
    from test_helpers import setup_plan_with_accrual
    return setup_plan_with_accrual(elapsed_days=120, principal_cents=450_000)


def _trade_up_with_registration():
    """Origin purchase completed with a live registration, plus a new trade-up
    purchase naming it as origin and backed by an approved line.
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
        "requested_limit_cents": 1_500_000,
        "requested_purchase_amount_cents": 900_100, "down_payment_cents": 90_010,
    }, ASSOCIATE), 201)
    get_success_data(api_client.decide_credit_application(application["id"],
                                                   {"decision": "APPROVE_FULL"}, ANALYST))
    customer = get_success_data(api_client.get_customer(customer["id"], AFTERCARE))

    bundle = setup_bundle()
    origin_diamond = setup_diamond(stone_code="ST-0111")
    new_diamond = setup_diamond(stone_code="ST-0112", carat=1.40,
                                origin_registry="KIMBERLEY-TX-5150")
    origin = setup_purchase(customer, store, base_price_cents=450_018, diamond=origin_diamond)
    origin = get_success_data(api_client.complete_purchase(origin["id"], ASSOCIATE))
    registration = setup_registration(customer, store, origin, origin_diamond, bundle)
    new_purchase = get_success_data(api_client.create_purchase({
        "customer_id": customer["id"], "store_id": store["id"],
        "base_price_cents": 900_100, "diamond_id": new_diamond["id"],
        "origin_purchase_id": origin["id"],
    }, ASSOCIATE), 201)
    return {"customer": customer, "store": store, "origin": origin,
            "registration": registration, "new_purchase": new_purchase,
            "origin_diamond": origin_diamond, "new_diamond": new_diamond}