"""State-machine claims: valid transitions, terminal lockdowns, side effects."""

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
    setup_active_registration,
    setup_bundle,
    setup_customer,
    setup_diamond,
    setup_purchase,
    setup_registration,
    setup_regulation,
    setup_store,
    setup_vendor_shop,
    validate_error,
    validate_success,
)


def test_credit_decision_moves_pending_application_to_approved(api, credit_analyst_headers):
    """PRD §3.1: "When it succeeds, the granted tier `decision_tier` equals the application's `policy_tier`; `approved_limit_cents` takes the selected row's `base_limit_cents`"
    PRD §3.1: "The customer's posture then moves in the same operation: `credit_tier` is set to the granted tier, `account_status` becomes `OPEN` if it had been `NO_FILE`"

    Design: Corner/state_machines/credit_decision_moves_pending_application_to_approved
    """
    store, customer = _tier1_environment(base_limit_cents=400_000,
                                        min_down_payment_pct=0.20)
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 400_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, ASSOCIATE), 201)

    decided = validate_success(api.decide_credit_application(
        application["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers), 200)
    assert decided["decision_status"] == "APPROVED"
    assert decided["decision_tier"] == "TIER_1"
    assert decided["approved_limit_cents"] == 400_000
    assert decided["min_down_payment_required_cents"] == 50_000
    assert decided["down_payment_shortfall_cents"] == 0
    assert decided["version"] == 2

    refreshed = get_success_data(api.get_customer(customer["id"], credit_analyst_headers))
    assert refreshed["account_status"] == "OPEN"
    assert refreshed["credit_tier"] == "TIER_1"
    assert refreshed["standalone_credit_limit_cents"] == 400_000


def test_decision_on_already_declined_application_is_invalid_state(api, credit_analyst_headers):
    """PRD §3.1: "A flat `DECLINE` needs only that the application be `PENDING`; the resulting `decision_status` of `DECLINED` is terminal, and the customer file is untouched"
    PRD §2.14: "Priority 4 is state: the target resource must be in a state from which the requested transition is declared, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/decision_on_already_declined_application_is_invalid_state
    """
    store, customer = _tier1_environment()
    application = get_success_data(api.create_credit_application({
        "customer_id": customer["id"], "store_id": store["id"],
        "requested_limit_cents": 250_000,
        "requested_purchase_amount_cents": 250_000, "down_payment_cents": 50_000,
    }, ASSOCIATE), 201)
    declined = get_success_data(api.decide_credit_application(
        application["id"], {"decision": "DECLINE"}, credit_analyst_headers))

    response = api.decide_credit_application(
        application["id"], {"decision": "APPROVE_FULL"}, credit_analyst_headers)
    validate_error(response, "ERR_INVALID_STATE", expected_status=409)

    unchanged = get_success_data(api.get_credit_application(
        application["id"], credit_analyst_headers))
    assert unchanged["decision_status"] == "DECLINED"
    assert unchanged["version"] == declined["version"], "no side effect fired"
    still_no_file = get_success_data(api.get_customer(customer["id"], credit_analyst_headers))
    assert still_no_file["account_status"] == "NO_FILE"


def test_new_repair_starts_at_intake_with_declared_custody_and_zero_delivery(
        api, store_manager_headers):
    """PRD §3.4: "The repair starts in `INTAKE`, and the store's `open_repair_liability_cents` is recomputed straight away."
    PRD §3.4: "Intake pins two things that are never recomputed: `accepted_at`, the intake instant from which every turnaround deadline is measured, and `loss_liability_cents`"

    Design: Corner/state_machines/new_repair_starts_at_intake_with_declared_custody_and_zero_delivery
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, diamond, bundle, purchase, registration = setup_active_registration()
    repair = validate_success(api.create_repair({
        "customer_id": customer["id"], "store_id": store["id"],
        "diamond_id": diamond["id"], "registration_id": registration["id"],
        "failure_class": "SETTING", "declared_parts_cents": 40_000,
        "declared_labor_cents": 15_000, "declared_loss_liability_cents": 5_000,
    }, store_manager_headers), 201)

    assert repair["repair_status"] == "INTAKE"
    assert repair["accepted_at"] == "2026-09-01T00:00:00.000Z"
    assert repair["vendor_shop_code"] is None
    assert repair["promised_delivery_at"] is None
    assert repair["pickup_deadline_at"] is None
    assert repair["version"] == 1
    stone = get_success_data(api.get_diamond(diamond["id"], store_manager_headers))
    assert stone["custody_status"] == "IN_CASE"


def test_verified_loss_is_terminal_and_refuses_further_transitions(api, store_manager_headers):
    """PRD §3.4: "`COMPLETED`, `UNREPAIRABLE`, `VERIFIED_LOSS`, and `ABANDONED` are the terminal repair states."
    PRD §3.4: "the repair becomes `VERIFIED_LOSS`, custody becomes `WITHDRAWN`, an appraisal is issued, the store's liability is recomputed, and — explicitly — the `loss_liability_cents` declared at intake is not recomputed here."

    Design: Corner/state_machines/verified_loss_is_terminal_and_refuses_further_transitions
    """
    from test_helpers import create_repair_in_qc_review
    customer, store, diamond, registration, repair = create_repair_in_qc_review(
        shop_code="MALCA", failure_class="STONE_LOSS")
    pinned = repair["loss_liability_cents"]
    declared = validate_success(
        api.declare_repair_loss(repair["id"], store_manager_headers), 200)
    assert declared["repair_status"] == "VERIFIED_LOSS"

    response = api.route_repair(repair["id"], store_manager_headers)
    validate_error(response, "ERR_INVALID_STATE", expected_status=409)

    unchanged = get_success_data(api.get_repair(repair["id"], store_manager_headers))
    assert unchanged["repair_status"] == "VERIFIED_LOSS"
    assert unchanged["loss_liability_cents"] == pinned, (
        "the intake liability is never recomputed"
    )
    stone = get_success_data(api.get_diamond(diamond["id"], store_manager_headers))
    assert stone["custody_status"] == "WITHDRAWN"
    appraisals = validate_success(api.list_repair_appraisals(
        repair["id"], store_manager_headers), 200)
    assert len(appraisals) == 1


def test_second_route_from_routed_state_is_invalid_state_and_keeps_first_vendor(
        api, store_manager_headers):
    """PRD §3.4: "On success the repair's `vendor_shop_code` is stamped with the routing result, `promised_delivery_at` is stamped as the intake instant plus that shop's `base_turnaround_days`, `repair_status` becomes `ROUTED`"
    PRD §2.14: "Priority 4 is state: the target resource must be in a state from which the requested transition is declared, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/second_route_from_routed_state_is_invalid_state_and_keeps_first_vendor
    """
    reset_clock(LOGICAL_CLOCK_START)
    customer, store, diamond, bundle, purchase, registration = setup_active_registration()
    setup_vendor_shop(shop_code="JEWELCRAFT")
    from test_helpers import setup_repair
    repair = setup_repair(customer, store, diamond, registration, failure_class="SETTING")
    first = validate_success(api.route_repair(repair["id"], store_manager_headers), 200)

    response = api.route_repair(repair["id"], store_manager_headers)
    validate_error(response, "ERR_INVALID_STATE", expected_status=409)

    unchanged = get_success_data(api.get_repair(repair["id"], store_manager_headers))
    assert unchanged["vendor_shop_code"] == "JEWELCRAFT"
    assert unchanged["promised_delivery_at"] == first["promised_delivery_at"]
    assert unchanged["repair_status"] == "ROUTED"


def test_purchase_completion_requires_open_account_precondition_error(
        api, sales_associate_headers):
    """PRD §3.5: "the customer's `account_status` must be `OPEN`"
    PRD §2.14: "Priority 9 is the account posture requirement that the account carrying the obligation be `OPEN`, giving `ERR_ACCOUNT_NOT_OPEN` (422)."

    Design: Corner/state_machines/purchase_completion_requires_open_account_precondition_error
    """
    reset_clock(LOGICAL_CLOCK_START)
    setup_regulation()
    store = setup_store()
    customer = setup_customer()
    purchase = setup_purchase(customer, store, base_price_cents=450_018)

    response = api.complete_purchase(purchase["id"], sales_associate_headers)
    validate_error(response, "ERR_ACCOUNT_NOT_OPEN", expected_status=422)

    unchanged = get_success_data(api.get_purchase(purchase["id"], sales_associate_headers))
    assert unchanged["purchase_status"] == "PENDING"
    refreshed = get_success_data(api.get_customer(customer["id"], sales_associate_headers))
    assert refreshed["outstanding_balance_cents"] == 0
    assert refreshed["lifetime_purchase_cents"] == 0


def test_verified_repair_emits_appraisal_purchase_and_liability_side_effects(
        api, store_manager_headers):
    """PRD §3.4: "A replacement appraisal is then issued out of the repair file at the value described in §2.9, its traceability URL taken from the stone's `origin_registry`."
    PRD §2.9: "parts of 2,800 and labor of 15,000 give a base of 17,800; an unrepairable natural stone appraises at 18,512"

    Design: Corner/state_machines/verified_repair_emits_appraisal_purchase_and_liability_side_effects
    """
    from test_helpers import create_repair_in_qc_review
    customer, store, diamond, registration, repair = create_repair_in_qc_review(
        shop_code="MALCA", failure_class="STONE_LOSS")
    assert repair["customer_parts_cents"] == 2_800
    assert repair["customer_labor_cents"] == 15_000

    completed = validate_success(api.verify_repair(repair["id"], store_manager_headers), 200)
    assert completed["repair_status"] == "COMPLETED"
    assert completed["pickup_deadline_at"] is not None
    assert completed["stored_appraisal_id"] is not None

    appraisals = validate_success(api.list_repair_appraisals(
        repair["id"], store_manager_headers), 200)
    assert len(appraisals) == 1
    assert appraisals[0]["appraised_value_cents"] == 17_800, (
        "a repaired stone takes the default multiplier over the 17,800 base"
    )
    assert appraisals[0]["id"] == completed["stored_appraisal_id"]
    stone = get_success_data(api.get_diamond(diamond["id"], store_manager_headers))
    assert stone["custody_status"] == "IN_CASE"


def test_the_completed_repair_leaves_the_open_liability_set(api, store_manager_headers):
    """PRD §2.16: "`open_repair_liability_cents` sums `loss_liability_cents` across the store's repairs currently in `INTAKE`, `ROUTED`, `IN_REPAIR`, or `QC_REVIEW`."
    PRD §2.16: "`store_absorbed_total_cents` sums `store_absorbed_cents` across the store's repairs currently in `INTAKE`, `ROUTED`, `IN_REPAIR`, `QC_REVIEW`, or `COMPLETED`."

    Design: Corner/state_machines/verified_repair_emits_appraisal_purchase_and_liability_side_effects
    """
    from test_helpers import create_repair_in_qc_review
    customer, store, diamond, registration, repair = create_repair_in_qc_review(
        shop_code="MALCA", failure_class="STONE_LOSS")
    liability = repair["loss_liability_cents"]
    validate_success(api.verify_repair(repair["id"], store_manager_headers), 200)

    store_after = validate_success(api.get_store(store["id"], store_manager_headers), 200)
    assert store_after["open_repair_liability_cents"] == 0, (
        "a COMPLETED repair leaves the open set"
    )
    assert store_after["store_absorbed_total_cents"] == liability, (
        "but its absorbed cost still counts"
    )


def test_the_completed_repair_terminates_its_covering_registration(api, store_manager_headers):
    """PRD §3.4: "The lifetime registration that covered the damaged diamond becomes `TERMINATED`."
    PRD §3.4: "The store's `open_inspection_count` decrements and its `open_repair_liability_cents` is recomputed."

    Design: Corner/state_machines/verified_repair_emits_appraisal_purchase_and_liability_side_effects
    """
    from test_helpers import create_repair_in_qc_review
    customer, store, diamond, registration, repair = create_repair_in_qc_review(
        shop_code="MALCA", failure_class="STONE_LOSS")
    validate_success(api.verify_repair(repair["id"], store_manager_headers), 200)

    registration_after = get_success_data(api.get_registration(
        registration["id"], store_manager_headers))
    assert registration_after["coverage_status"] == "TERMINATED"
    store_after = get_success_data(api.get_store(store["id"], store_manager_headers))
    assert store_after["open_inspection_count"] == 0


def test_the_completed_repair_opens_a_replacement_purchase_at_the_appraised_value(
        api, store_manager_headers):
    """PRD §3.4: "A purchase is opened against the appraised value — `base_price_cents` equal to the appraisal's `appraised_value_cents`, starting in `PENDING`, with its own `trade_up_credit_cents` set to the lesser of the repair's `loss_liability_cents` and the appraised value."
    PRD §3.4: "The repair records the issued appraisal in `stored_appraisal_id` and increments its `version`."

    Design: Corner/state_machines/verified_repair_emits_appraisal_purchase_and_liability_side_effects
    """
    from test_helpers import create_repair_in_qc_review
    customer, store, diamond, registration, repair = create_repair_in_qc_review(
        shop_code="MALCA", failure_class="STONE_LOSS")
    completed = validate_success(api.verify_repair(repair["id"], store_manager_headers), 200)
    appraisals = validate_success(api.list_repair_appraisals(
        repair["id"], store_manager_headers), 200)
    appraised = appraisals[0]["appraised_value_cents"]

    purchases = validate_success(api.list_customer_purchases(
        customer["id"], store_manager_headers), 200)
    derived = [p for p in purchases if p["base_price_cents"] == appraised]
    assert derived, "a purchase opens at the appraised value"
    assert derived[0]["purchase_status"] == "PENDING"
    assert derived[0]["trade_up_credit_cents"] == min(
        completed["loss_liability_cents"], appraised)


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