"""Difficulty queue A: validation-priority pair and cross-entity state
dependencies (order requires APPROVED verification; binding requires IN_HAND
unit owned by the patient)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_order,
    create_approved_verification,
    create_lot,
    create_order,
    create_patient,
    create_payer,
    create_prescriber,
    create_prescription,
    create_product,
    create_units,
    decide_verification,
    file_and_close_aer,
    make_patient_headers,
    pick_order,
    run_verification,
    setup_lot_with_substantiated_complaints,
    setup_supply_pipeline,
    validate_error,
)

FULFILL = TEST_USERS["fulfillment_agent_headers"]


def test_state_priority_wins_on_pick_of_cancelled_order_on_hold_lot(api):
    """PRD §2.7: "All authentication, authorization, existence, state, and
    business validations run in the priority order defined throughout this
    document — authentication first, then role permission, then path and body
    existence, then transition-state validity, then business and fiscal rules."
    PRD §3.5: "A `FulfillmentAgent` picks the order, which requires the order
    to be in `PENDING_PICK` (otherwise `ERR_ORDER_NOT_PICKABLE`)"

    Order is CANCELLED (transition-state violation) on a HOLD lot (business
    rule); the state error must be reported.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_pick_of_cancelled_order_on_hold_lot
    """
    ctx = setup_lot_with_substantiated_complaints(7)
    prescriber = create_prescriber()
    payer = create_payer()
    patient = ctx["patient"]
    rx = create_prescription(patient, prescriber, ctx["product"], quantity_per_fill=1)
    cv = create_approved_verification(rx, payer)
    order = create_order(patient, rx, cv, ctx["lot"])
    cancelled = api.cancel_sensor_order(order["id"], FULFILL)
    assert cancelled.status_code == 200
    resp = api.pick_sensor_order(order["id"], FULFILL)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PICKABLE, expected_status=409)


def test_cancelled_order_on_hold_lot_remains_cancelled_after_failed_pick(api):
    """PRD §3.5: "A `PENDING_PICK` order may instead be cancelled by a
    `FulfillmentAgent` (or via cascade when the parent prescription is
    cancelled); cancelling from any other fulfillment state is rejected with
    `ERR_ORDER_NOT_CANCELLABLE`."
    PRD §2.7: "All authentication, authorization, existence, state, and
    business validations run in the priority order defined throughout this
    document — authentication first, then role permission, then path and body
    existence, then transition-state validity, then business and fiscal rules."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_pick_of_cancelled_order_on_hold_lot
    """
    ctx = setup_lot_with_substantiated_complaints(7)
    prescriber = create_prescriber()
    payer = create_payer()
    patient = ctx["patient"]
    rx = create_prescription(patient, prescriber, ctx["product"], quantity_per_fill=1)
    cv = create_approved_verification(rx, payer)
    order = create_order(patient, rx, cv, ctx["lot"])
    assert api.cancel_sensor_order(order["id"], FULFILL).status_code == 200
    resp = api.pick_sensor_order(order["id"], FULFILL)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PICKABLE, expected_status=409)
    after = api.get_sensor_order(order["id"], TEST_USERS["platform_admin_headers"]).json()["data"]
    assert after["fulfillment_status"] == "CANCELLED"


def test_order_against_pending_verification_rejected(api):
    """PRD §3.5: "The referenced coverage verification must belong to the same
    prescription and must currently be decided `APPROVED`; otherwise the create
    is rejected with `ERR_COVERAGE_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_order_create
    """
    ctx = setup_supply_pipeline()
    # a fresh verification left PENDING on the same prescription
    cv_pending = run_verification(ctx["prescription"], ctx["payer"])
    resp = api.create_sensor_order(
        ctx["patient"]["id"],
        {
            "prescription_id": ctx["prescription"]["id"],
            "coverage_verification_id": cv_pending["id"],
            "lot_id": ctx["lot"]["id"],
            "quantity": 1,
        },
        FULFILL,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_NOT_APPROVED, expected_status=409)


def test_order_against_verification_of_other_prescription_rejected(api):
    """PRD §3.5: "The referenced coverage verification must belong to the same
    prescription and must currently be decided `APPROVED`; otherwise the create
    is rejected with `ERR_COVERAGE_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_order_create
    """
    ctx = setup_supply_pipeline()
    patient2 = create_patient()
    prescriber2 = create_prescriber()
    rx2 = create_prescription(patient2, prescriber2, ctx["product"], quantity_per_fill=1)
    cv2 = create_approved_verification(rx2, ctx["payer"])
    # cv2 is APPROVED but belongs to rx2, not to ctx's prescription
    resp = api.create_sensor_order(
        ctx["patient"]["id"],
        {
            "prescription_id": ctx["prescription"]["id"],
            "coverage_verification_id": cv2["id"],
            "lot_id": ctx["lot"]["id"],
            "quantity": 1,
        },
        FULFILL,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_NOT_APPROVED, expected_status=409)


def test_order_against_denied_verification_rejected(api):
    """PRD §3.5: "The referenced coverage verification must belong to the same
    prescription and must currently be decided `APPROVED`; otherwise the create
    is rejected with `ERR_COVERAGE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/sensor_order_requires_coverage_verification_approved
    """
    ctx = setup_supply_pipeline()
    cv_denied = run_verification(ctx["prescription"], ctx["payer"])
    decide_verification(cv_denied, "DENIED", denial_reason="MISSING_DOCUMENTATION")
    resp = api.create_sensor_order(
        ctx["patient"]["id"],
        {
            "prescription_id": ctx["prescription"]["id"],
            "coverage_verification_id": cv_denied["id"],
            "lot_id": ctx["lot"]["id"],
            "quantity": 1,
        },
        FULFILL,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_NOT_APPROVED, expected_status=409)


def test_order_against_pending_verification_rejected_for_dependency(api):
    """PRD §3.5: "The referenced coverage verification must belong to the same
    prescription and must currently be decided `APPROVED`; otherwise the create
    is rejected with `ERR_COVERAGE_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/sensor_order_requires_coverage_verification_approved
    """
    ctx = setup_supply_pipeline()
    cv_pending = run_verification(ctx["prescription"], ctx["payer"])
    resp = api.create_sensor_order(
        ctx["patient"]["id"],
        {
            "prescription_id": ctx["prescription"]["id"],
            "coverage_verification_id": cv_pending["id"],
            "lot_id": ctx["lot"]["id"],
            "quantity": 1,
        },
        FULFILL,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_NOT_APPROVED, expected_status=409)


def test_binding_against_allocated_unit_rejected(api):
    """PRD §3.7: "The unit must currently be `IN_HAND` and allocated to the
    activating patient; a unit in any other status, or one allocated to a
    different patient, is rejected with `ERR_UNIT_NOT_ACTIVATABLE`."

    Design: Difficulty/cross_entity_state_dependency/device_binding_requires_unit_in_hand
    """
    ctx = setup_supply_pipeline()
    order = create_order(ctx["patient"], ctx["prescription"], ctx["verification"], ctx["lot"])
    adjudicate_order(order)
    pick_order(order)
    # unit is now ALLOCATED to the patient but not yet IN_HAND
    unit = ctx["units"][0]
    resp = api.create_device_binding(
        ctx["patient"]["id"],
        {"sensor_unit_id": unit["id"], "channel": "READER"},
        make_patient_headers(ctx["patient"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_ACTIVATABLE, expected_status=409)


def test_binding_against_in_hand_unit_of_another_patient_rejected(api):
    """PRD §3.7: "The unit must currently be `IN_HAND` and allocated to the
    activating patient; a unit in any other status, or one allocated to a
    different patient, is rejected with `ERR_UNIT_NOT_ACTIVATABLE`."

    Design: Difficulty/cross_entity_state_dependency/device_binding_requires_unit_in_hand
    """
    from test_helpers import setup_delivered_unit

    ctx = setup_delivered_unit()
    intruder = create_patient()
    unit = ctx["units"][0]  # IN_HAND, allocated to ctx patient
    resp = api.create_device_binding(
        intruder["id"],
        {"sensor_unit_id": unit["id"], "channel": "READER"},
        make_patient_headers(intruder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_ACTIVATABLE, expected_status=409)
