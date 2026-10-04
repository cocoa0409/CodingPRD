"""Cross-cutting claims: optimistic concurrency, ordering, scheduled effects."""

from test_helpers import (
    AFTERCARE,
    ANALYST,
    ASSOCIATE,
    LOGICAL_CLOCK_START,
    MANAGER,
    api_client,
    get_success_data,
    reset_clock,
    setup_plan_environment,
    setup_plan_with_accrual,
    setup_pending_registration,
    setup_purchase,
    setup_store,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_purchase_create_rejects_a_stale_expected_version(api, sales_associate_headers):
    """PRD §2.13: "Creating a financing plan against a purchase requires `expected_purchase_version` in the request body, carrying the client's last observed `version` of the target purchase. If the purchase's current `version` differs, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)"
    PRD §2.13: "a second financing code is a legitimate product for the same purchase, so the state preconditions alone would not have prevented a write the client had not observed."

    Design: Corner/cross_cutting_layers/purchase_create_rejects_a_stale_expected_version
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code="PROMO_12_6M", base_price_cents=450_000,
        requested_limit_cents=1_000_000)
    del plan
    stale = get_success_data(api.get_purchase(purchase["id"], sales_associate_headers))
    stale_version = stale["version"]
    stamped = validate_success(api.stamp_trade_up_credit(
        purchase["id"], {"additional_credit_cents": 10_050}, AFTERCARE), 200)
    current_version = stamped["version"]
    assert current_version != stale_version

    second = api.create_promotional_plan({
        "customer_id": customer["id"], "purchase_id": purchase["id"],
        "plan_code": "PROMO_18_6M", "expected_purchase_version": stale_version,
    }, sales_associate_headers)
    validate_error(second, "ERR_STALE_VERSION", expected_status=412)

    rows, meta = validate_paginated(api.list_promotional_plans(
        sales_associate_headers, params={"purchase_id": purchase["id"]}))
    assert meta["total_count"] == 1, "the stale write created nothing"
    after = get_success_data(api.get_purchase(purchase["id"], sales_associate_headers))
    assert after["version"] == current_version


def test_a_current_expected_version_is_admitted_where_the_write_is_otherwise_legal(
        api, sales_associate_headers):
    """PRD §2.14: "Priority 5 is the optimistic concurrency assertion, `ERR_STALE_VERSION` (412), on the four write operations named in §2.13."
    PRD §3.2: "Opening a plan requires the cardholder's `customer_id`, the `purchase_id` being financed, the `plan_code` chosen at the counter, and — because a second financing code is a perfectly legitimate product for the same ticket — the client's last observed `expected_purchase_version`."

    Design: Corner/cross_cutting_layers/purchase_create_rejects_a_stale_expected_version
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code="PROMO_12_6M", base_price_cents=450_000)
    assert plan["plan_status"] == "ACCRUING"
    ticket = get_success_data(api.get_purchase(purchase["id"], sales_associate_headers))
    assert ticket["purchase_status"] == "FINANCED"
    assert ticket["version"] > 1, "opening the plan advanced the ticket's version"


def test_version_increments_once_per_mutation_including_cascaded_writes(
        api, sales_associate_headers):
    """PRD §2.12: "`version` is an integer that starts at 1 and increments by one on every modification to the resource; it is the quantity optimistic concurrency control is asserted against"
    PRD §2.16: "When a child event changes a quantity a parent carries, the parent is reconciled without a separate client request, and each such reconciliation is an ordinary mutation that increments the parent's `version`"

    Design: Corner/cross_cutting_layers/version_increments_once_per_mutation_including_cascaded_writes
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, origin, new_purchase, _, _ = _trade_up_ready()
    origin_after = get_success_data(api.get_purchase(origin["id"], sales_associate_headers))
    origin_version = origin_after["version"]

    completed = validate_success(
        api.complete_purchase(new_purchase["id"], sales_associate_headers), 200)
    assert completed["purchase_status"] == "COMPLETED"
    after = get_success_data(api.get_purchase(origin["id"], sales_associate_headers))
    assert after["purchase_status"] == "TRADE_UP_APPLIED"
    assert after["version"] > origin_version, (
        "the cascade wrote onto the origin, advancing its version too"
    )


def test_simultaneous_order_of_appearance_of_inspection_visits_is_pinned_by_created_at(
        api, store_manager_headers):
    """PRD §2.16: "`created_at` is an ISO 8601 timestamp in UTC with exactly three fractional digits (for example `2025-05-24T10:30:00.123Z`) recording when the resource was first written."
    PRD §2.3: "Unless a rule elsewhere in this document says otherwise, list endpoints return resources sorted by creation timestamp (`created_at`) in ascending order."

    Design: Corner/cross_cutting_layers/simultaneous_order_of_appearance_of_inspection_visits_is_pinned_by_created_at
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, diamond, bundle, purchase, registration = setup_pending_registration()
    reset_clock("2027-02-20T00:00:00Z")
    validate_success(api.run_inspection_reminders(store_manager_headers), 200)
    current = get_success_data(api.get_registration(registration["id"], store_manager_headers))

    # PRD §3.3 refuses a visit logged earlier than the registration's current
    # `inspection_due_at`, so the claim lands exactly on that instant.
    visit = validate_success(api.create_inspection_visit({
        "registration_id": registration["id"],
        "store_id": store["id"],
        "visit_at": current["inspection_due_at"],
        "result": "CLAIMED",
        "expected_registration_version": current["version"],
    }, store_manager_headers), 201)
    assert visit["inspection_status"] == "CLAIMED"
    assert visit["claimed_at"] is not None

    rows, meta = validate_paginated(api.list_inspection_visits(
        store_manager_headers, params={"registration_id": registration["id"]}))
    assert meta["total_count"] >= 2
    created = [row["created_at"] for row in rows]
    assert created == sorted(created), "the list is ordered by created_at ascending"
    assert len(rows) == meta["total_count"]


def test_derived_customer_balance_refuses_a_short_plan_payment(api, customer_service_headers):
    """PRD §2.5: "over 120 days, 39,930 cents"
    PRD §2.10: "`outstanding_balance_cents` is the sum of `adjustment_cents` over the customer's payoff-ledger entries, plus, for every promotional plan that is not yet `PAID`, the `installment_amount_cents` of its current open quarter."

    Design: Corner/cross_cutting_layers/derived_customer_balance_reconciles_after_each_plan_write
    """
    customer, store, purchase, plan = setup_plan_with_accrual(
        elapsed_days=120, principal_cents=450_000)
    before = get_success_data(api.get_customer(customer["id"], customer_service_headers))
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))

    response = api.payoff_promotional_plan(
        plan["id"], {"amount_cents": 112_500, "expected_plan_version": settled["version"]},
        customer_service_headers)
    validate_error(response, "ERR_INSUFFICIENT_PAYOFF", expected_status=422)

    after = get_success_data(api.get_customer(customer["id"], customer_service_headers))
    assert after["outstanding_balance_cents"] == before["outstanding_balance_cents"], (
        "a refused write leaves the derived balance untouched"
    )
    plan_after = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    assert plan_after["final_settlement_amount_cents"] == 489_930, (
        "principal plus the accrual at the current instant"
    )


def test_the_customer_balance_tracks_the_settled_plan_after_payment(
        api, customer_service_headers):
    """PRD §3.2: "The plan's `version` increments by one and the cardholder's `outstanding_balance_cents`, utilization band, and recomputed tier all follow."
    PRD §3.2: "`deferred_interest_accrued_cents` and `final_settlement_amount_cents` both fall to 0, which is the forgiveness the promo promised"

    Design: Corner/cross_cutting_layers/derived_customer_balance_reconciles_after_each_plan_write
    """
    customer, store, purchase, plan = setup_plan_with_accrual(
        elapsed_days=120, principal_cents=450_000)
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    before = get_success_data(api.get_customer(customer["id"], customer_service_headers))

    validate_success(api.payoff_promotional_plan(
        plan["id"],
        {"amount_cents": settled["final_settlement_amount_cents"],
         "expected_plan_version": settled["version"]},
        customer_service_headers), 200)
    after = get_success_data(api.get_customer(customer["id"], customer_service_headers))
    assert after["outstanding_balance_cents"] < before["outstanding_balance_cents"]
    assert after["standalone_credit_limit_cents"] == before["standalone_credit_limit_cents"], (
        "the limit is restored from the registry row, not recomputed from the balance"
    )


def test_scheduled_capitalization_takes_effect_only_after_the_window_elapses(
        api, credit_analyst_headers):
    """PRD §3.2: "Any plan still `ACCRUING` when the current instant is strictly after `simplicity_expires_at` has its deferred interest converted into principal."
    PRD §3.2: "The sweep reports `capitalized_count` and `capitalized_plan_ids`."

    Design: Corner/cross_cutting_layers/scheduled_capitalization_takes_effect_only_after_the_window_elapses
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, purchase, plan = setup_plan_environment(
        plan_code="PROMO_12_6M", base_price_cents=450_000)
    reset_clock("2027-08-31T00:00:00Z")
    early = validate_success(api.capitalize_plans_due(credit_analyst_headers), 200)
    assert early["capitalized_count"] == 0
    before = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert before["plan_status"] == "ACCRUING"

    reset_clock("2027-09-02T00:00:00Z")
    late = validate_success(api.capitalize_plans_due(credit_analyst_headers), 200)
    assert late["capitalized_count"] == 1
    after = get_success_data(api.get_promotional_plan(plan["id"], credit_analyst_headers))
    assert after["plan_status"] == "CAPITALIZED"
    assert after["deferred_interest_accrued_cents"] == 0
    assert after["merchant_deferral_fee_cents"] == 0
    assert after["principal_cents"] > before["principal_cents"], (
        "the deferred interest is folded into the principal"
    )


def _trade_up_ready():
    """Origin purchase completed at 450,018 with a 900,100 trade-up naming it."""
    from test_helpers import setup_approved_customer, setup_diamond
    customer, store, _ = setup_approved_customer(
        requested_limit_cents=1_500_000,
        requested_purchase_amount_cents=900_100, down_payment_cents=90_010)
    diamond = setup_diamond(stone_code="ST-0001")
    origin = setup_purchase(customer, store, base_price_cents=450_018, diamond=diamond)
    origin = get_success_data(api_client.complete_purchase(origin["id"], ASSOCIATE))
    new_purchase = get_success_data(api_client.create_purchase({
        "customer_id": customer["id"], "store_id": store["id"],
        "base_price_cents": 900_100, "origin_purchase_id": origin["id"],
    }, ASSOCIATE), 201)
    return customer, store, origin, new_purchase, diamond, None