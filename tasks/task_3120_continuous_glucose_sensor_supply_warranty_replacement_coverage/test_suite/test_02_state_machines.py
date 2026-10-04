"""State machines: initial states, terminal-state lockdown, invalid
transitions, and transition preconditions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_approved_verification,
    create_patient,
    create_prescriber,
    create_prescription,
    create_product,
    make_prescriber_headers,
    run_verification,
    setup_claim_in_data_review,
    setup_delivered_unit,
    setup_failed_unit,
    setup_supply_pipeline,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["coverage_reviewer_headers"]
FULFILL = TEST_USERS["fulfillment_agent_headers"]


def test_prescription_initial_state_active(api):
    """PRD §3.3: "A prescription begins in `ACTIVE`."

    Design: Corner/state_machines/prescription_initial_state_active
    """
    patient = create_patient()
    prescriber = create_prescriber()
    product = create_product()
    rx = create_prescription(patient, prescriber, product)
    assert rx["status"] == "ACTIVE"


def test_prescription_terminal_state_lockdown(api):
    """PRD §3.3: "A prescriber may also cancel an active prescription directly;
    the cancellation is rejected with `ERR_PRESCRIPTION_NOT_ACTIVE` if the
    prescription is not `ACTIVE`"
    PRD §3.3: "The terminal states `EXHAUSTED`, `EXPIRED`, and `CANCELLED` are
    irreversible, and any state-driven refresh of a prescription touches
    `updated_at` and bumps its `version`."

    Design: Corner/state_machines/prescription_terminal_state_lockdown
    """
    patient = create_patient()
    prescriber = create_prescriber()
    product = create_product()
    rx = create_prescription(patient, prescriber, product)
    headers = make_prescriber_headers(prescriber["id"])
    first = api.cancel_prescription(rx["id"], headers)
    cancelled = validate_success(first, expected_status=200)
    assert cancelled["status"] == "CANCELLED"
    second = api.cancel_prescription(rx["id"], headers)
    validate_error(second, ApiErrorId.ERR_PRESCRIPTION_NOT_ACTIVE, expected_status=409)


def test_coverage_verification_decide_twice_rejected(api):
    """PRD §3.4: "If the verification is no longer `PENDING`, the decision
    attempt is rejected with `ERR_VERIFICATION_ALREADY_DECIDED`."

    Design: Corner/state_machines/coverage_verification_decide_twice_rejected
    """
    ctx = setup_supply_pipeline()
    resp = api.decide_coverage_verification(
        ctx["verification"]["id"],
        {"decision": "DENIED", "denial_reason": "MISSING_DOCUMENTATION"},
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_ALREADY_DECIDED, expected_status=409)


def test_sensor_order_terminal_delivered_no_further_transitions(api):
    """PRD §3.5: "cancelling from any other fulfillment state is rejected with
    `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/sensor_order_terminal_delivered_no_further_transitions
    """
    ctx = setup_delivered_unit()
    assert ctx["order"]["fulfillment_status"] == "DELIVERED"
    resp = api.cancel_sensor_order(ctx["order"]["id"], FULFILL)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE, expected_status=409)


def test_warranty_claim_begin_review_rejected_when_device_data_missing(api):
    """PRD §3.8: "A `WarrantyReviewer` takes the claim into review, which
    requires the claim to be in `SUBMITTED` (otherwise
    `ERR_CLAIM_NOT_SUBMITTED`) and requires `device_data_attached` to be true
    (otherwise `ERR_DEVICE_DATA_REQUIRED`)."

    Design: Corner/state_machines/warranty_claim_begin_review_rejected_when_device_data_missing
    """
    ctx = setup_failed_unit(failure_day_index=3, device_data_attached=False)
    resp = api.begin_review_warranty_claim(
        ctx["claim"]["id"], TEST_USERS["warranty_reviewer_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_DEVICE_DATA_REQUIRED, expected_status=422)
