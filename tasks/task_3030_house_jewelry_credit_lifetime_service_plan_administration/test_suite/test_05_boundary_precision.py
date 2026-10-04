"""Boundary precision: exact-threshold crossings and empty-set edges.

Each test evaluates the rule at the boundary instant or the boundary cent, so
an off-by-one implementation is caught rather than a merely wrong formula.
"""

from test_helpers import (
    ADMIN,
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
    open_customer,
    setup_store,
    validate_paginated,
    validate_success,
)


def test_down_payment_floor_is_inclusive_at_exactly_the_required_minimum(
        api, credit_analyst_headers):
    """PRD §2.4: "Worked reference: a Texas row with `min_ticket_cents` of 200,000, `base_limit_cents` of 300,000, and `min_down_payment_pct` of 0.10, against a requested limit of 300,000 and a purchase amount of 300,000 with 30,000 tendered, yields `approved_limit_cents` of 300,000, a required minimum of 30,000, and a shortfall of 0"
    PRD §2.4: "`down_payment_shortfall_cents` is `min_down_payment_required_cents` minus `down_payment_cents`, floored at 0"

    Design: Difficulty/boundary_precision_check/down_payment_shortfall_flips_at_exactly_the_ceil_boundary
    """
    store, customer, app_a, app_b, app_c = _three_boundary_applications()
    decided = validate_success(api.decide_credit_application(
        app_a["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers), 200)

    assert decided["min_down_payment_required_cents"] == 30_000
    assert decided["down_payment_shortfall_cents"] == 0, (
        "the boundary itself is satisfied, not missed"
    )
    assert decided["decision_status"] == "APPROVED"
    assert decided["approved_limit_cents"] == 300_000, (
        "the granted ceiling is the lesser of the row base and the requested amount"
    )


def test_down_payment_shortfall_opens_up_one_cent_past_the_boundary(
        api, credit_analyst_headers):
    """PRD §2.4: "the same inputs with a purchase amount of 300,001 yield a required minimum of 30,001 and a shortfall of 1; and with a purchase amount of 300,050 they yield 30,050 required against 30,000 tendered, a shortfall of 5."
    PRD §2.4: "`min_down_payment_required_cents` is `min_down_payment_pct` multiplied by `requested_purchase_amount_cents`, rounded up to a whole cent."

    Design: Difficulty/boundary_precision_check/down_payment_shortfall_flips_at_exactly_the_ceil_boundary
    """
    store, customer, app_a, app_b, app_c = _three_boundary_applications()
    one_cent_past = validate_success(api.decide_credit_application(
        app_b["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers), 200)
    wider = validate_success(api.decide_credit_application(
        app_c["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers), 200)

    assert one_cent_past["min_down_payment_required_cents"] == 30_001
    assert one_cent_past["down_payment_shortfall_cents"] == 1
    assert wider["min_down_payment_required_cents"] == 30_005, (
        "PRD §2.4 states the formula normatively: min_down_payment_pct "
        "multiplied by requested_purchase_amount_cents, rounded up to a whole "
        "cent. 0.10 x 300,050 is exactly 30,005"
    )
    assert wider["down_payment_shortfall_cents"] == 5, (
        "the tender of 30,000 falls 5 cents short of the 30,005 minimum"
    )


def test_shortfall_is_reported_rather_than_raised_by_the_decision(
        api, credit_analyst_headers):
    """PRD §2.4: "A declared down payment below the formula-derived minimum for the decisioned tier is refused with `ERR_DOWN_PAYMENT_REQUIRED` (HTTP 422)."
    PRD §2.4: "`down_payment_shortfall_cents` is `min_down_payment_required_cents` minus `down_payment_cents`, floored at 0 — that is, the amount by which the tendered down payment falls short, or 0 when it does not."

    Design: Difficulty/boundary_precision_check/down_payment_shortfall_flips_at_exactly_the_ceil_boundary
    """
    store, customer, app_a, app_b, app_c = _three_boundary_applications()
    decided = validate_success(api.decide_credit_application(
        app_c["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers), 200)
    assert decided["decision_status"] == "APPROVED", (
        "the decision still lands; the shortfall is a reported figure"
    )
    assert decided["down_payment_shortfall_cents"] == 5
    assert decided["min_down_payment_required_cents"] - 30_000 == 5


def test_terminating_the_only_registration_does_not_push_the_count_negative(
        api, store_manager_headers):
    """PRD §2.16: "`open_inspection_count` counts the store's registrations whose `coverage_status` is `PENDING_INSPECTION` or `REMINDER_ISSUED`, and is recomputed on every registration transition."
    PRD §3.3: "The result is `TERMINATED`, with `is_valid` false, every scheduled visit of the registration marked `NO_SHOW`, and the store's `open_inspection_count` decremented."

    Design: Difficulty/boundary_precision_check/zero_open_inspection_count_writes_no_negative_floor
    """
    customer, store, diamond, bundle, purchase, registration = _single_registration_store()
    before = get_success_data(api.get_store(store["id"], store_manager_headers))
    assert before["open_inspection_count"] == 1

    terminated = validate_success(api.terminate_registration(
        registration["id"], store_manager_headers), 200)
    assert terminated["coverage_status"] == "TERMINATED"

    after = get_success_data(api.get_store(store["id"], store_manager_headers))
    assert after["open_inspection_count"] == 0, "the count lands on 0 exactly, never -1"
    assert after["open_inspection_count"] >= 0


def test_a_store_that_accepted_no_repair_reports_zero_open_liability(
        api, store_manager_headers):
    """PRD §2.16: "When a child event changes a quantity a parent carries, the parent is reconciled without a separate client request"
    PRD §2.16: "`open_repair_liability_cents` sums `loss_liability_cents` across the store's repairs currently in `INTAKE`, `ROUTED`, `IN_REPAIR`, or `QC_REVIEW`."

    Design: Difficulty/boundary_precision_check/zero_open_inspection_count_writes_no_negative_floor
    """
    customer, store, diamond, bundle, purchase, registration = _single_registration_store()
    store_after = get_success_data(api.get_store(store["id"], store_manager_headers))
    assert store_after["open_repair_liability_cents"] == 0, (
        "a store with no repairs sums an empty set, not a stale or null value"
    )
    assert store_after["store_absorbed_total_cents"] == 0


def test_empty_repair_collection_paginates_as_an_empty_array(api, store_manager_headers):
    """PRD §2.2: "The `data` field contains the resource object or an array of resource objects."
    PRD §2.3: "`offset` skips that many items from the front of the result and defaults to 0."

    Design: Difficulty/boundary_precision_check/zero_open_inspection_count_writes_no_negative_floor
    """
    customer, store, diamond, bundle, purchase, registration = _single_registration_store()
    data, meta = validate_paginated(
        api.list_repairs(store_manager_headers, params={"store_id": store["id"]}))
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def _three_boundary_applications():
    """Store ACTIVE in TX with a TIER_3 row at 10% and three applications
    straddling the ceil boundary of the down-payment formula.
    """
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    get_success_data(api_client.create_regulation({
        "state_code": "TX", "max_plan_term_months": 60, "inspection_required_months": 6,
        "lapse_cure_days": 30, "replacement_plus_pct": 1.0, "max_inspection_gap_days": 210,
    }, ADMIN), 201)
    get_success_data(api_client.create_registry_row({
        "registry_key": "TX", "credit_tier": "TIER_1", "base_limit_cents": 300_000,
        "min_down_payment_pct": 0.10, "registry_type": "STATE", "min_ticket_cents": 200_000,
    }, ADMIN), 201)
    customer = setup_customer()

    def _application(amount):
        return get_success_data(api_client.create_credit_application({
            "customer_id": customer["id"], "store_id": store["id"],
            "requested_limit_cents": 300_000,
            "requested_purchase_amount_cents": amount,
            "down_payment_cents": 30_000,
        }, ASSOCIATE), 201)

    return store, customer, _application(300_000), _application(300_001), _application(300_050)


def _single_registration_store():
    """A store carrying exactly one registration in PENDING_INSPECTION and no repairs."""
    reset_clock(LOGICAL_CLOCK_START)
    store = setup_store()
    get_success_data(api_client.create_regulation({
        "state_code": "TX", "max_plan_term_months": 60, "inspection_required_months": 6,
        "lapse_cure_days": 30, "replacement_plus_pct": 1.0, "max_inspection_gap_days": 210,
    }, ADMIN), 201)
    customer = setup_customer()
    customer, _ = open_customer(customer, store)
    bundle = setup_bundle()
    diamond = setup_diamond(stone_code="ST-0051")
    purchase = setup_purchase(customer, store, base_price_cents=320_000, diamond=diamond)
    purchase = get_success_data(api_client.complete_purchase(purchase["id"], ASSOCIATE))
    registration = setup_registration(customer, store, purchase, diamond, bundle)
    return customer, store, diamond, bundle, purchase, registration