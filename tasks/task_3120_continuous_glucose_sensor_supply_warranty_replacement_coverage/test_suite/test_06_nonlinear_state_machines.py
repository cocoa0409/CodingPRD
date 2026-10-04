"""Difficulty queue A: non-linear state machines — SensorOrder's parallel
fulfillment x billing dimensions, and WarrantyClaim's review cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_order,
    deliver_order,
    make_patient_headers,
    pick_order,
    setup_failed_unit,
    setup_order_pipeline,
    ship_order,
    validate_error,
    validate_success,
)

FULFILL = TEST_USERS["fulfillment_agent_headers"]
WARRANTY = TEST_USERS["warranty_reviewer_headers"]


def test_order_ship_before_adjudication_rejected(api):
    """PRD §3.5: "a `FulfillmentAgent` ships the order, which requires
    `fulfillment_status` of `PICKED` (otherwise `ERR_ORDER_NOT_SHIPPABLE`) and
    `billing_status` of `ADJUDICATED` (otherwise `ERR_ORDER_NOT_ADJUDICATED`)"

    Design: Difficulty/non_linear_state_machine/sensor_order_parallel_fulfillment_x_billing
    """
    ctx = setup_order_pipeline()
    order = ctx["order"]
    assert order["fulfillment_status"] == "PENDING_PICK"
    resp = api.ship_sensor_order(order["id"], FULFILL)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SHIPPABLE, expected_status=409)


def test_order_adjudicate_while_pending_pick_then_fulfill_to_delivered(api):
    """PRD §3.6: "Adjudication moves `billing_status` from `UNBILLED` to
    `ADJUDICATED`."
    PRD §3.6: "The order's `billing_status` must be `UNBILLED` (otherwise
    `ERR_ORDER_ALREADY_ADJUDICATED`), and its `fulfillment_status` must be
    `PENDING_PICK` or `PICKED` — adjudicating an order that has already
    shipped, been delivered, or been cancelled is rejected with
    `ERR_ORDER_NOT_ADJUDICATABLE_STATE`."
    PRD §3.5: "Delivery moves `fulfillment_status` from `SHIPPED` to
    `DELIVERED` (requiring `SHIPPED`, else `ERR_ORDER_NOT_DELIVERABLE`) and
    transitions each unit `SHIPPED → IN_HAND`."

    Design: Difficulty/non_linear_state_machine/sensor_order_parallel_fulfillment_x_billing
    """
    ctx = setup_order_pipeline()
    order = ctx["order"]
    adjudicated = adjudicate_order(order)
    assert adjudicated["billing_status"] == "ADJUDICATED"
    assert adjudicated["fulfillment_status"] == "PENDING_PICK"
    picked = pick_order(order)
    assert picked["fulfillment_status"] == "PICKED"
    assert picked["billing_status"] == "ADJUDICATED"
    shipped = ship_order(order)
    assert shipped["fulfillment_status"] == "SHIPPED"
    delivered = deliver_order(order)
    assert delivered["fulfillment_status"] == "DELIVERED"


def test_warranty_claim_review_cycle_returns_to_data_review(api):
    """PRD §3.8: "From there, the reviewer may request more information, moving
    the claim to `MORE_INFO_REQUESTED`; the patient then resubmits data (the
    resubmission sets `device_data_attached` and requires the acting patient's
    `X-User-ID` to equal the claim's `patient_id`), returning the claim to
    `DATA_REVIEW`."

    Design: Difficulty/non_linear_state_machine/warranty_claim_data_review_cycle
    """
    ctx = setup_failed_unit(failure_day_index=3, device_data_attached=True)
    claim = ctx["claim"]
    patient = ctx["patient"]
    claim = validate_success(api.begin_review_warranty_claim(claim["id"], WARRANTY))
    assert claim["status"] == "DATA_REVIEW"
    claim = validate_success(api.request_more_info_warranty_claim(claim["id"], WARRANTY))
    assert claim["status"] == "MORE_INFO_REQUESTED"
    claim = validate_success(
        api.resubmit_data_warranty_claim(
            claim["id"], {"device_data_attached": True}, make_patient_headers(patient["id"])
        )
    )
    assert claim["status"] == "DATA_REVIEW"


def test_warranty_claim_two_cycles_then_approved(api):
    """PRD §3.8: "Approving requires the claim to be in `DATA_REVIEW`
    (otherwise `ERR_CLAIM_NOT_IN_REVIEW`), requires `device_data_attached`
    still to be true (otherwise `ERR_DEVICE_DATA_REQUIRED`), requires the
    supplied `review_notes` to be at least ten characters long"
    PRD §3.8: "The states `APPROVED`, `DENIED`, and `CLOSED` are all terminal."

    Design: Difficulty/non_linear_state_machine/warranty_claim_data_review_cycle
    """
    ctx = setup_failed_unit(failure_day_index=3, device_data_attached=True)
    claim = ctx["claim"]
    patient = ctx["patient"]
    validate_success(api.begin_review_warranty_claim(claim["id"], WARRANTY))
    for _ in range(2):
        validate_success(api.request_more_info_warranty_claim(claim["id"], WARRANTY))
        validate_success(
            api.resubmit_data_warranty_claim(
                claim["id"], {"device_data_attached": True}, make_patient_headers(patient["id"])
            )
        )
    approved = validate_success(
        api.decide_warranty_claim(
            claim["id"],
            {"decision": "APPROVED", "review_notes": "approved after two review cycles"},
            WARRANTY,
        )
    )
    assert approved["status"] == "APPROVED"
