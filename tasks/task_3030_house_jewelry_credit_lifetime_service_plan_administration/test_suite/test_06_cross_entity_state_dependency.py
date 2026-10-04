"""Cross-entity gates: one entity's transition depends on another's state.

Each pair is asserted from both directions — the request succeeds while the
dependency holds and is refused the moment it does not — so an implementation
that never reads the other entity is caught.
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
    validate_paginated,
    validate_success,
)


def test_purchase_completion_succeeds_while_the_customer_account_is_open(
        api, sales_associate_headers):
    """PRD §3.5: "Completing a purchase is the `SalesAssociate`'s act and it has five preconditions. The ticket must be in `PENDING` or `FINANCED`; the customer's `account_status` must be `OPEN`"
    PRD §3.5: "The ticket's `purchase_status` becomes `COMPLETED` and its `completed_at` is stamped."

    Design: Difficulty/cross_entity_state_dependency/purchase_completion_gated_by_customer_credit_posture
    """
    store, customer, purchase, other, other_purchase = _open_and_no_file_customers()
    completed = validate_success(
        api.complete_purchase(purchase["id"], sales_associate_headers), 200)
    assert completed["purchase_status"] == "COMPLETED"
    assert completed["completed_at"] is not None


def test_purchase_completion_is_refused_for_a_customer_with_no_credit_file(
        api, sales_associate_headers):
    """PRD §2.14: "Priority 9 is the account posture requirement that the account carrying the obligation be `OPEN`, giving `ERR_ACCOUNT_NOT_OPEN` (422)."
    PRD §3.7: "The account posture requirement is the next layer down: any obligation carried by an account that is not `OPEN` is refused with `ERR_ACCOUNT_NOT_OPEN` (HTTP 422)"

    Design: Difficulty/cross_entity_state_dependency/purchase_completion_gated_by_customer_credit_posture
    """
    store, customer, purchase, other, other_purchase = _open_and_no_file_customers()
    response = api.complete_purchase(other_purchase["id"], sales_associate_headers)
    assert response.status_code == 422
    body = response.json()
    assert body["data"]["error_id"] == "ERR_ACCOUNT_NOT_OPEN", (
        "the gate is the account posture, not a state or payload error"
    )
    unchanged = get_success_data(api.get_purchase(other_purchase["id"], sales_associate_headers))
    assert unchanged["purchase_status"] == "PENDING"


def test_the_successful_completion_updates_the_customers_own_totals(
        api, sales_associate_headers):
    """PRD §2.10: "`lifetime_purchase_cents` is the sum of `base_price_cents` over the customer's purchases that have reached `COMPLETED` or `TRADE_UP_APPLIED`."

    Design: Difficulty/cross_entity_state_dependency/purchase_completion_gated_by_customer_credit_posture
    """
    store, customer, purchase, other, other_purchase = _open_and_no_file_customers()
    validate_success(api.complete_purchase(purchase["id"], sales_associate_headers), 200)
    refreshed = get_success_data(api.get_customer(customer["id"], sales_associate_headers))
    assert refreshed["lifetime_purchase_cents"] == 500_000, (
        "the completed ticket's base price enters the customer's lifetime total"
    )


def test_the_refused_completion_leaves_the_no_file_customer_untouched(
        api, sales_associate_headers):
    """PRD §3.5: "the customer's `outstanding_balance_cents` plus that net amount must not exceed their `standalone_credit_limit_cents`"
    PRD §3.1: "A newly created customer carries `account_status` of `NO_FILE` and `credit_tier` of `NO_FILE`, an `outstanding_balance_cents` of 0, and no `standalone_credit_limit_cents` at all"

    Design: Difficulty/cross_entity_state_dependency/purchase_completion_gated_by_customer_credit_posture
    """
    store, customer, purchase, other, other_purchase = _open_and_no_file_customers()
    api.complete_purchase(other_purchase["id"], sales_associate_headers)
    refreshed = get_success_data(api.get_customer(other["id"], sales_associate_headers))
    assert refreshed["account_status"] == "NO_FILE"
    assert refreshed["outstanding_balance_cents"] == 0
    assert refreshed["lifetime_purchase_cents"] == 0


def test_active_registration_splits_the_repair_liability_with_the_diamond_component(
        api, store_manager_headers):
    """PRD §2.7: "The final step is the coverage gate. Whether the plan is valid is `is_valid_plan`, which is true only when the pinned registration's `coverage_status` is `ACTIVE`."
    PRD §2.7: "On the worked example above, `insurance_parts_cents` is 37,200, `customer_parts_cents` is 2,800, and `customer_labor_cents` is 15,000."

    Design: Difficulty/cross_entity_state_dependency/repair_liability_split_gated_by_registration_coverage_status
    """
    customer, store, diamond, bundle, purchase, registration = _active_registration_graph()
    repaired = validate_success(api.create_repair({
        "customer_id": customer["id"], "store_id": store["id"],
        "diamond_id": diamond["id"], "registration_id": registration["id"],
        "failure_class": "SETTING", "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000, "declared_loss_liability_cents": 5_000,
    }, store_manager_headers), 201)
    assert repaired["insurance_parts_cents"] == 37_200
    assert repaired["customer_parts_cents"] == 2_800
    assert repaired["loss_liability_cents"] == 35_000


def test_lapsed_registration_is_refused_at_intake_as_plan_terms_unsatisfied(
        api, store_manager_headers):
    """PRD §3.4: "A registration that has already `LAPSED` routes the repair to full-price billing and is likewise refused at intake with `ERR_PLAN_TERMS_UNSATISFIED` (HTTP 422)."
    PRD §2.14: "Priority 17 is the requirement that the plan be non-lapsed at intake, `ERR_PLAN_TERMS_UNSATISFIED` (422)."

    Design: Difficulty/cross_entity_state_dependency/repair_liability_split_gated_by_registration_coverage_status
    """
    from test_helpers import setup_pending_registration
    customer, store, diamond, bundle, purchase, registration = setup_pending_registration()
    reset_clock("2027-06-15T00:00:00Z")
    get_success_data(api.lapse_registrations_due(ANALYST))
    lapsed = get_success_data(api.get_registration(registration["id"], store_manager_headers))
    assert lapsed["coverage_status"] == "LAPSED"
    assert lapsed["is_valid"] is False

    response = api.create_repair({
        "customer_id": customer["id"], "store_id": store["id"],
        "diamond_id": diamond["id"],
        "registration_id": registration["id"],
        "failure_class": "SETTING", "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000, "declared_loss_liability_cents": 5_000,
    }, store_manager_headers)
    assert response.status_code == 422, (
        "a lapsed plan routes the repair to full-price billing rather than covering it"
    )
    assert response.json()["data"]["error_id"] == "ERR_PLAN_TERMS_UNSATISFIED"
    data, meta = _list_registration_repairs(api, registration["id"], store_manager_headers)
    assert data == [], "the refused intake wrote no repair row"


def test_intake_against_a_lapsed_registration_writes_no_repair_row(
        api, store_manager_headers):
    """PRD §3.3: "`is_valid` is true only while `coverage_status` is `ACTIVE`, and it is the gate that decides whether a new repair's liability is split with the diamond component or billed wholly to the customer."
    PRD §3.3: "Any registration still in `PENDING_INSPECTION` or `REMINDER_ISSUED` at an instant strictly after its `cure_expires_at` becomes `LAPSED` with `is_valid` false"

    Design: Difficulty/cross_entity_state_dependency/repair_liability_split_gated_by_registration_coverage_status
    """
    from test_helpers import setup_pending_registration
    customer, store, diamond, bundle, purchase, registration = setup_pending_registration()
    reset_clock("2027-06-15T00:00:00Z")
    get_success_data(api.lapse_registrations_due(ANALYST))
    lapsed = get_success_data(api.get_registration(registration["id"], store_manager_headers))
    assert lapsed["coverage_status"] == "LAPSED"
    assert lapsed["is_valid"] is False

    response = api.create_repair({
        "customer_id": customer["id"], "store_id": store["id"],
        "diamond_id": diamond["id"],
        "registration_id": registration["id"],
        "failure_class": "SETTING", "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000, "declared_loss_liability_cents": 5_000,
    }, store_manager_headers)
    assert response.status_code == 422
    assert response.json()["data"]["error_id"] == "ERR_PLAN_TERMS_UNSATISFIED"
    data, meta = _list_registration_repairs(api, registration["id"], store_manager_headers)
    assert data == []
    assert meta["total_count"] == 0


def _list_registration_repairs(api, registration_id, headers):
    return validate_paginated(
        api.list_repairs(headers, params={"registration_id": registration_id}))


def _active_registration_graph():
    from test_helpers import setup_active_registration
    return setup_active_registration()


def _open_and_no_file_customers():
    """One customer opened to OPEN by an approved application, and a second
    still at NO_FILE, each with a purchase she could otherwise complete.
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
    customer = setup_customer(email="nina.ortiz@example.com")
    other = setup_customer(full_name="Ivan Petrov", email="ivan.petrov@example.com")
    application = get_success_data(api_client.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 1_000_000,
        "requested_purchase_amount_cents": 500_000, "down_payment_cents": 50_000,
    }, ASSOCIATE), 201)
    get_success_data(api_client.decide_credit_application(application["id"],
                                                   {"decision": "APPROVE_FULL"}, ANALYST))
    customer = get_success_data(api_client.get_customer(customer["id"], AFTERCARE))

    diamond = setup_diamond(stone_code="ST-0061")
    purchase = setup_purchase(customer, store, base_price_cents=500_000, diamond=diamond)
    other_purchase = setup_purchase(other, store, base_price_cents=500_000)
    return store, customer, purchase, other, other_purchase