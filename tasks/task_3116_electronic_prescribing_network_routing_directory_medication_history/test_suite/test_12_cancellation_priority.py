"""Cancellation: the error reported depends on which band rejects first.

The same operation on the same kind of order reports a different error as the order's routing
status moves, because the safety band and the state band sit at different priority levels.
"""
from test_helpers import (
    validate_error,
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    setup_signed_prescription,
    route_prescription,
    latest_attempt,
    report_undeliverable,
    reload_prescription,
    make_prescriber_headers,
    api_client,
)


def _two_critical_orders():
    """A SCHEDULE_II order parked at ROUTED on an ACTIVE endpoint, and a second SCHEDULE_II
    order whose in-flight attempt was reported undeliverable with no alternative endpoint for
    the same service set, leaving it at ROUTE_FAILED.

    The pharmacy also holds an inert MED_HISTORY endpoint so that degrading the NEW_RX one
    does not trip the coverage invariant.
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    ep_new_rx = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    add_endpoint(
        pharmacy["id"], service_set="MED_HISTORY", endpoint_role="RECEIVER",
        service_level="ELIGIBLE_A", sla_response_minutes=60,
        message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    rx_a, _ = setup_signed_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_II",
        refills_authorized=0,
    )
    rx_a = route_prescription(rx_a["id"], clinic["id"])

    rx_b, _ = setup_signed_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_II",
        refills_authorized=0,
    )
    rx_b = route_prescription(rx_b["id"], clinic["id"])
    report_undeliverable(latest_attempt(rx_b["id"])["id"], "CF_0000")
    rx_b = reload_prescription(rx_b["id"])

    return clinic, pharmacy, patient, rx_a, rx_b, ep_new_rx


def test_cancelling_a_critical_order_before_delivery_requires_a_delivery_outcome(api):
    """PRD §3.5: "One class of order resists cancellation: an order whose `significance` is
    `CRITICAL` — a `SCHEDULE_II` or `SCHEDULE_III` order, or an order for a patient monitored
    under `MEDICATION_HISTORY` consent — must reach a delivery outcome, meaning `DELIVERED` or
    the reach that `FALLBACK_SENT` represents, before it may settle as `CANCELLED`; a
    cancellation attempted before that is refused with `ERR_CRITICAL_ORDER_DELIVERY_REQUIRED`
    at HTTP 422."

    Design: Difficulty/priority_pair_validation_conflict/cancellation_priority_business_safety_over_constraint
    """
    clinic, pharmacy, patient, rx_a, rx_b, ep_new_rx = _two_critical_orders()

    assert rx_a["significance"] == "CRITICAL"
    assert rx_a["routing_status"] == "ROUTED"
    assert rx_a["clinical_status"] == "ROUTED"

    response = api_client.cancel_prescription(
        rx_a["id"], make_prescriber_headers(clinic["id"])
    )
    validate_error(response, "ERR_CRITICAL_ORDER_DELIVERY_REQUIRED", expected_status=422)


def test_cancelling_an_order_whose_routing_failed_reports_the_state_error(api):
    """PRD §3.5: "A routing status other than those four is refused with `ERR_INVALID_STATE`."
    PRD §2.9: "State admission follows: the target resource must be in a state that admits the
    requested operation, and rejection here uses `ERR_INVALID_STATE`,
    `ERR_ROUTE_ATTEMPT_IN_PROGRESS`, `ERR_ALREADY_TERMINAL`, or `ERR_LAST_ACTIVE_ENDPOINT`,
    all at HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/cancellation_priority_business_safety_over_constraint
    """
    clinic, pharmacy, patient, rx_a, rx_b, ep_new_rx = _two_critical_orders()

    # Same significance as rx_a, but a routing status the state band already rejects — so the
    # two orders report different errors for the identical operation.
    assert rx_b["significance"] == "CRITICAL"
    assert rx_b["routing_status"] == "ROUTE_FAILED"

    response = api_client.cancel_prescription(
        rx_b["id"], make_prescriber_headers(clinic["id"])
    )
    error = validate_error(response, "ERR_INVALID_STATE", expected_status=409)
    assert error["error_id"] != "ERR_CRITICAL_ORDER_DELIVERY_REQUIRED"

    assert reload_prescription(rx_a["id"])["clinical_status"] == "ROUTED"
    assert reload_prescription(rx_b["id"])["clinical_status"] == "SIGNED"