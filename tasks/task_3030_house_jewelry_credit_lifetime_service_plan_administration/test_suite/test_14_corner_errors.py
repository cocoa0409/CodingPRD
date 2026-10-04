"""Error-surface claims: each catalogue identifier's trigger condition."""

from test_helpers import (
    ADMIN,
    AFTERCARE,
    ANALYST,
    ASSOCIATE,
    LOGICAL_CLOCK_START,
    MANAGER,
    api_client,
    create_repair_in_qc_review,
    open_customer,
    get_success_data,
    reset_clock,
    setup_active_registration,
    setup_approved_customer,
    setup_bundle,
    setup_customer,
    setup_diamond,
    setup_pending_registration,
    setup_plan_with_accrual,
    setup_purchase,
    setup_registration,
    setup_repair,
    setup_regulation,
    setup_store,
    setup_store_near_capacity,
    setup_vendor_shop,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_credit_limit_exceeded_is_raised_on_decision_over_the_tier_ceiling(
        api, credit_analyst_headers):
    """PRD §2.4: "A requested amount above the standalone limit implied by the customer's `credit_tier` is refused with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422)."
    PRD §2.4: "`approved_limit_cents` is the smaller of `base_limit_cents` and `requested_limit_cents`."

    Design: Corner/errors/credit_limit_exceeded_is_raised_on_decision_over_the_tier_ceiling
    """
    store, customer = _tier1_environment(base_limit_cents=400_000)

    def _application(amount):
        return get_success_data(api.create_credit_application({
            "customer_id": customer["id"], "store_id": store["id"],
            "requested_limit_cents": amount,
            "requested_purchase_amount_cents": 300_000, "down_payment_cents": 60_000,
        }, ASSOCIATE), 201)

    over = _application(400_001)
    at = _application(400_000)
    response = api.decide_credit_application(
        over["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers)
    validate_error(response, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=422)
    unchanged = get_success_data(api.get_credit_application(over["id"], credit_analyst_headers))
    assert unchanged["decision_status"] == "PENDING"

    approved = validate_success(api.decide_credit_application(
        at["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers), 200)
    assert approved["approved_limit_cents"] == 400_000, "the ceiling is inclusive"
    assert approved["decision_status"] == "APPROVED"


def test_regulation_terms_violation_is_raised_when_state_terms_are_unregistered(
        api, store_manager_headers):
    """PRD §3.3: "Registration conversion has a compliance gate in front of it. If no regulation row exists for the store's `state_code`, the registration cannot be originated and the attempt is refused with `ERR_REGULATION_TERMS_VIOLATION` (HTTP 422)"
    PRD §3.3: "The store's `open_inspection_count` is recomputed at once, because a registration in `PENDING_INSPECTION` counts against it."

    Design: Corner/errors/regulation_terms_violation_is_raised_when_state_terms_are_unregistered
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_regulation()
    store_zz = setup_store(state_code="ZZ", store_code="0142")
    store_tx = setup_store(state_code="TX", store_code="0210")
    customer = setup_customer()
    customer, _ = open_customer(customer, store_tx)
    bundle = get_success_data(api.create_bundle({
        "bundle_code": "BUNDLE_180", "display_name": "Lifetime Diamond 180",
        "lifetime_plan_fee_cents": 19_900, "stone_limit_labor_cents": 25_000,
        "stone_limit_parts_cents": 60_000, "inspection_interval_days": 180,
        "inspection_cure_days": 30,
    }, ADMIN), 201)
    get_success_data(api.create_diamond({
        "stone_code": "ST-0001", "stone_kind": "NATURAL", "carat": 0.90,
    }, ASSOCIATE), 201)
    diamonds = validate_success(api.list_diamonds(ASSOCIATE), 200)
    diamond = diamonds[0]
    get_success_data(api.create_regulation({
        "state_code": "TX", "max_plan_term_months": 60, "inspection_required_months": 6,
        "lapse_cure_days": 30, "replacement_plus_pct": 1.0, "max_inspection_gap_days": 210,
    }, ADMIN), 201)
    purchase = setup_purchase(customer, store_tx, base_price_cents=400_000, diamond=diamond)
    purchase = get_success_data(api.complete_purchase(purchase["id"], ASSOCIATE))

    response = api.create_registration({
        "customer_id": customer["id"], "purchase_id": purchase["id"],
        "diamond_id": diamond["id"], "store_id": store_zz["id"],
        "bundle_id": bundle["id"], "plan_term_months": 24,
    }, store_manager_headers)
    validate_error(response, "ERR_REGULATION_TERMS_VIOLATION", expected_status=422)

    rows, meta = validate_paginated(api.list_registrations(
        store_manager_headers, params={"store_id": store_zz["id"]}))
    assert meta["total_count"] == 0
    store_after = get_success_data(api.get_store(store_zz["id"], store_manager_headers))
    assert store_after["open_inspection_count"] == 0


def test_plan_term_exceeding_the_state_maximum_is_rejected(api, store_manager_headers):
    """PRD §2.6: "Where the row exists but the plan's `plan_term_months` exceeds `max_plan_term_months`, the request is refused with the same `ERR_REGULATION_TERMS_VIOLATION` code at HTTP 422"
    PRD §2.6: "A registration also takes `plan_term_months`, the contracted term, which must not exceed the maximum the governing state permits."

    Design: Corner/errors/plan_term_exceeding_the_state_maximum_is_rejected
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_regulation()
    store = setup_store()
    customer = setup_customer()
    customer, _ = open_customer(customer, store)
    bundle = setup_bundle()
    diamond = setup_diamond(stone_code="ST-0001")
    purchase = setup_purchase(customer, store, base_price_cents=400_000, diamond=diamond)
    purchase = get_success_data(api.complete_purchase(purchase["id"], ASSOCIATE))

    admitted = validate_success(api.create_registration({
        "customer_id": customer["id"], "purchase_id": purchase["id"],
        "diamond_id": diamond["id"], "store_id": store["id"],
        "bundle_id": bundle["id"], "plan_term_months": 60,
    }, store_manager_headers), 201)
    assert admitted["plan_term_months"] == 60, "60 is admitted"

    overrun = api.create_registration({
        "customer_id": customer["id"], "purchase_id": purchase["id"],
        "diamond_id": diamond["id"], "store_id": store["id"],
        "bundle_id": bundle["id"], "plan_term_months": 61,
    }, store_manager_headers)
    assert overrun.status_code == 422
    assert overrun.json()["data"]["error_id"] in (
        "ERR_PLAN_TERM_EXCEEDS_REGULATION", "ERR_REGULATION_TERMS_VIOLATION",
    ), "both identifiers describe refusals of a term the state does not allow"

    rows, meta = validate_paginated(api.list_registrations(
        store_manager_headers, params={"purchase_id": purchase["id"]}))
    assert meta["total_count"] == 1


def test_insufficient_payoff_below_the_settlement_amount_is_rejected(
        api, customer_service_headers):
    """PRD §2.5: "over 120 days, 39,930 cents"
    PRD §3.2: "A payoff below the settlement amount is refused with `ERR_INSUFFICIENT_PAYOFF` (HTTP 422)"

    Design: Corner/errors/insufficient_payoff_below_the_settlement_amount_is_rejected
    """
    customer, store, purchase, plan = setup_plan_with_accrual(
        elapsed_days=120, principal_cents=450_000)
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    assert settled["final_settlement_amount_cents"] == 489_930

    response = api.payoff_promotional_plan(
        plan["id"],
        {"amount_cents": 489_929, "expected_plan_version": settled["version"]},
        customer_service_headers)
    validate_error(response, "ERR_INSUFFICIENT_PAYOFF", expected_status=422)

    unchanged = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))
    assert unchanged["plan_status"] == "ACCRUING"
    assert unchanged["total_paid_cents"] == 0
    entries = validate_success(api.list_plan_ledger_entries(
        plan["id"], customer_service_headers), 200)
    assert entries == []


def test_the_exact_settlement_amount_is_accepted(api, customer_service_headers):
    """PRD §3.2: "requires the submitted `amount_cents` to be at least the plan's `principal_cents` plus its `deferred_interest_accrued_cents`"
    PRD §3.2: "The amount is added to `total_paid_cents`; `plan_status` becomes `PAID` and `paid_at` is stamped with the current instant"

    Design: Corner/errors/insufficient_payoff_below_the_settlement_amount_is_rejected
    """
    customer, store, purchase, plan = setup_plan_with_accrual(
        elapsed_days=120, principal_cents=450_000)
    settled = get_success_data(api.get_promotional_plan(plan["id"], customer_service_headers))

    paid = validate_success(api.payoff_promotional_plan(
        plan["id"],
        {"amount_cents": settled["final_settlement_amount_cents"],
         "expected_plan_version": settled["version"]},
        customer_service_headers), 200)
    assert paid["plan_status"] == "PAID"
    assert paid["total_paid_cents"] == 489_930


def test_trade_up_floor_not_met_is_rejected_one_cent_under_two_times_origin(
        api, sales_associate_headers):
    """PRD §2.8: "A 900,035 cent ticket against the same origin misses the 900,036 floor by one cent: completion is refused with `ERR_TRADE_UP_FLOOR_NOT_MET` even though the credit would still compute to 383,370."
    PRD §2.8: "`trade_up_floor_cents` is twice the origin purchase's `base_price_cents`."

    Design: Corner/errors/trade_up_floor_not_met_is_rejected_one_cent_under_two_times_origin
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, _ = setup_approved_customer(
        requested_limit_cents=1_500_000,
        requested_purchase_amount_cents=900_035, down_payment_cents=90_004)
    origin_diamond = setup_diamond(stone_code="ST-0001")
    origin = setup_purchase(customer, store, base_price_cents=450_018, diamond=origin_diamond)
    origin = get_success_data(api.complete_purchase(origin["id"], ASSOCIATE))
    short = get_success_data(api.create_purchase({
        "customer_id": customer["id"], "store_id": store["id"],
        "base_price_cents": 900_035, "origin_purchase_id": origin["id"],
    }, ASSOCIATE), 201)

    response = api.complete_purchase(short["id"], sales_associate_headers)
    validate_error(response, "ERR_TRADE_UP_FLOOR_NOT_MET", expected_status=422)

    unchanged = get_success_data(api.get_purchase(short["id"], sales_associate_headers))
    assert unchanged["trade_up_floor_cents"] == 900_036
    assert unchanged["purchase_status"] == "PENDING"
    origin_after = get_success_data(api.get_purchase(origin["id"], sales_associate_headers))
    assert origin_after["purchase_status"] == "COMPLETED", (
        "the refused completion did not consume the origin"
    )


def test_store_credit_capacity_exceeded_is_raised_when_the_liability_will_not_fit(
        api, store_manager_headers):
    """PRD §3.4: "A store whose available credit capacity cannot cover the obligation being booked refuses the intake with `ERR_STORE_CREDIT_CAPACITY_EXCEEDED` (HTTP 422)"
    PRD §2.7: "the reserve is `declared_parts_cents` multiplied by `WARRANTY_RESERVE_PCT` (0.07), rounded half up"

    Design: Corner/errors/store_credit_capacity_exceeded_is_raised_when_the_liability_will_not_fit
    """
    customer, store, diamond, registration, first = setup_store_near_capacity(
        credit_capacity_cents=20_000, first_parts_cents=15_000,
        first_labor_cents=0, first_failure_class="OTHER")

    assert first["store_absorbed_cents"] == 1_050, (
        "reserve of 1,050 with no labor above the limit"
    )
    store_after = get_success_data(api.get_store(store["id"], store_manager_headers))
    assert store_after["available_credit_capacity_cents"] == 20_000 - 1_050

    response = api.create_repair({
        "customer_id": customer["id"], "store_id": store["id"],
        "diamond_id": diamond["id"], "registration_id": registration["id"],
        "failure_class": "SETTING", "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000, "declared_loss_liability_cents": 5_000,
    }, store_manager_headers)
    validate_error(response, "ERR_STORE_CREDIT_CAPACITY_EXCEEDED", expected_status=422)

    rows, meta = validate_paginated(api.list_repairs(
        store_manager_headers, params={"store_id": store["id"]}))
    assert meta["total_count"] == 1, "the refusal happened before any Repair row was written"


def test_vendor_missing_is_raised_when_the_routing_table_target_is_absent(
        api, store_manager_headers):
    """PRD §3.4: "a missing or retired shop is refused with `ERR_VENDOR_MISSING` (HTTP 422)"
    PRD §3.4: "Routing requires the repair to be in `INTAKE` and the shop named by the routing rule to exist with a `vendor_status` of `ACTIVE`"

    Design: Corner/errors/vendor_missing_is_raised_when_the_routing_table_target_is_absent
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, diamond, bundle, purchase, registration = setup_active_registration()
    repair = setup_repair(customer, store, diamond, registration, failure_class="SETTING")

    response = api.route_repair(repair["id"], store_manager_headers)
    validate_error(response, "ERR_VENDOR_MISSING", expected_status=422)

    unchanged = get_success_data(api.get_repair(repair["id"], store_manager_headers))
    assert unchanged["repair_status"] == "INTAKE"
    assert unchanged["vendor_shop_code"] is None
    stone = get_success_data(api.get_diamond(diamond["id"], store_manager_headers))
    assert stone["custody_status"] == "IN_CASE"


def test_claim_already_used_blocks_a_second_insurance_replacement_advice(
        api, customer_service_headers):
    """PRD §2.9: "a registration whose count is already 1 cannot support a second advice and is refused with `ERR_CLAIM_ALREADY_USED` (HTTP 409)."
    PRD §2.9: "The circulation moves `appraisal_status` to `CIRCULATED`, takes the mandatory `insurance_schedule_ref`, and increments the registration's `replacement_claims_used`."

    Design: Corner/errors/claim_already_used_blocks_a_second_insurance_replacement_advice
    """
    customer, store, diamond, registration, repair = create_repair_in_qc_review(
        shop_code="MALCA", failure_class="STONE_LOSS")
    validate_success(api.declare_repair_loss(repair["id"], MANAGER), 200)
    appraisals = validate_success(api.list_repair_appraisals(repair["id"], MANAGER), 200)
    appraisal_id = appraisals[0]["id"]

    first = validate_success(api.advise_insurer(
        appraisal_id, {"insurance_schedule_ref": "SCH-2026-0001"}, customer_service_headers), 200)
    assert first["appraisal_status"] == "CIRCULATED"
    registration_after = get_success_data(api.get_registration(
        registration["id"], customer_service_headers))
    assert registration_after["replacement_claims_used"] == 1

    second = api.advise_insurer(
        appraisal_id, {"insurance_schedule_ref": "SCH-2026-0002"}, customer_service_headers)
    validate_error(second, "ERR_CLAIM_ALREADY_USED", expected_status=409)
    still_one = get_success_data(api.get_registration(
        registration["id"], customer_service_headers))
    assert still_one["replacement_claims_used"] == 1
    unchanged = get_success_data(api.get_appraisal(appraisal_id, customer_service_headers))
    assert unchanged["insurance_schedule_ref"] == "SCH-2026-0001"


def _tier1_environment(base_limit_cents: int = 400_000,
                       min_down_payment_pct: float = 0.20):
    store = setup_store()
    get_success_data(api_client.create_regulation({
        "state_code": "TX", "max_plan_term_months": 60, "inspection_required_months": 6,
        "lapse_cure_days": 30, "replacement_plus_pct": 1.0, "max_inspection_gap_days": 210,
    }, ADMIN), 201)
    get_success_data(api_client.create_registry_row({
        "registry_key": "TX", "credit_tier": "TIER_1", "base_limit_cents": base_limit_cents,
        "min_down_payment_pct": min_down_payment_pct, "registry_type": "STATE",
        "min_ticket_cents": 200_000,
    }, ADMIN), 201)
    customer = setup_customer()
    return store, customer