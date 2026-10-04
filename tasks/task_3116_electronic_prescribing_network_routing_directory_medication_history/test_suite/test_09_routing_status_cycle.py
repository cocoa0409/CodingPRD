"""The cyclic routing-status machine: re-entering a state the order already occupied.

ROUTED and FALLBACK_SENT are not one-way stops. An order can travel ROUTED, then
BACKUP_SELECTION, then FALLBACK_PENDING and FALLBACK_SENT, and a fresh failing attempt lets
the same five transitions run again.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    setup_signed_prescription,
    route_prescription,
    current_attempts,
    latest_attempt,
    report_acknowledged,
    report_rejected,
    report_undeliverable,
    reload_attempt,
    reload_prescription,
    create_fallback_attempt,
    report_fallback,
    make_prescriber_headers,
    api_client,
)


def _drive_the_cycle():
    """Drive one order through ACK on the first endpoint, post-delivery rejection, ACK on the
    second endpoint, then an undeliverable report on that same attempt, then the fallback
    channel and a reported acknowledgment of the fax attempt.

    Returns the prescription and the observed routing-status sequence.
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    ep_a = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_B",
        sla_response_minutes=30, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    prescription, _ = setup_signed_prescription(clinic["id"], pharmacy["id"], patient["id"])

    observed = []

    # First attempt: acknowledged.
    prescription = route_prescription(prescription["id"], clinic["id"])
    observed.append(prescription["routing_status"])
    assert prescription["routed_endpoint_id"] == ep_a["id"]
    first = latest_attempt(prescription["id"])
    report_acknowledged(first["id"])
    prescription = reload_prescription(prescription["id"])
    observed.append(prescription["routing_status"])
    assert prescription["clinical_status"] == "DELIVERED"

    # Second attempt on the same order: a post-delivery rejection.
    prescription = route_prescription(prescription["id"], clinic["id"])
    observed.append(prescription["routing_status"])
    second = latest_attempt(prescription["id"])
    report_rejected(second["id"], "POST_DELIVERY", "ERR_RX_REJECTED")
    prescription = reload_prescription(prescription["id"])
    assert prescription["clinical_status"] == "REJECTED"

    # Third attempt: it lands on the other endpoint because the first is now excluded, and
    # it is acknowledged.
    prescription = route_prescription(prescription["id"], clinic["id"])
    observed.append(prescription["routing_status"])
    third = latest_attempt(prescription["id"])
    assert third["target_endpoint_id"] != ep_a["id"]
    report_acknowledged(third["id"])
    prescription = reload_prescription(prescription["id"])
    observed.append(prescription["routing_status"])
    assert prescription["clinical_status"] == "DELIVERED"

    # The same third attempt then reports undeliverable.
    report_undeliverable(third["id"], "CF_0000")
    prescription = reload_prescription(prescription["id"])
    observed.append(prescription["routing_status"])

    # Fallback: the order is sent over its declared fax channel.
    fallback_response = validate_success(
        api_client.route_fallback(
            prescription["id"], make_prescriber_headers(clinic["id"])
        ),
        200,
    )
    assert fallback_response["routing_status"] == "FALLBACK_PENDING"
    observed.append(fallback_response["routing_status"])

    fax_attempt = create_fallback_attempt(prescription["id"], clinic["id"], "FAX")
    report_fallback(fax_attempt["id"], "ACKNOWLEDGED")

    return prescription, observed, third, fax_attempt


def test_routing_status_cycle_reenters_a_state_the_order_already_occupied(api):
    """PRD §3.5: "The ordinary path into `FALLBACK_PENDING` is from `BACKUP_SELECTION`, where
    no remaining endpoint in `ACTIVE` or `DEGRADED` exists, and that route is refused with
    `ERR_NO_ROUTE_AVAILABLE` when one does."
    PRD §3.5: "an acknowledged network attempt moves a prescription sitting in `FALLBACK_SENT`
    back to `ROUTED` with `clinical_status` at `DELIVERED` — which closes the cyclic routing
    machine."

    Design: Difficulty/non_linear_state_machine/routing_status_cycle_reenters_fallback_sent
    """
    prescription, observed, third_attempt, fax_attempt = _drive_the_cycle()

    assert observed.count("ROUTED") >= 2, (
        "the order occupied ROUTED more than once, so the machine is cyclic rather than linear"
    )
    assert "FALLBACK_PENDING" in observed

    final = reload_prescription(prescription["id"])
    assert final["routing_status"] == "FALLBACK_SENT"
    assert final["clinical_status"] == "DELIVERED"
    assert final["active_routing_attempt_id"] is None

    reported_fax = reload_attempt(fax_attempt["id"])
    assert reported_fax["outcome"] == "ACKNOWLEDGED"
    assert reported_fax["target_endpoint_id"] is None


def test_attempt_history_records_every_terminal_outcome_in_order(api):
    """PRD §3.5: "The ordinary path into `FALLBACK_PENDING` is from `BACKUP_SELECTION`, where
    no remaining endpoint in `ACTIVE` or `DEGRADED` exists, and that route is refused with
    `ERR_NO_ROUTE_AVAILABLE` when one does."
    PRD §3.4: "A successful route creates a `RoutingAttempt` with `channel` `NETWORK` in
    `IN_PROGRESS` — its `attempt_no` is a monotone attempt number within the prescription
    starting at 1"

    Design: Difficulty/non_linear_state_machine/routing_status_cycle_reenters_fallback_sent
    """
    prescription, _, third_attempt, fax_attempt = _drive_the_cycle()

    attempts = sorted(current_attempts(prescription["id"]), key=lambda a: a["attempt_no"])
    assert [a["attempt_no"] for a in attempts] == [1, 2, 3, 4]
    assert [a["outcome"] for a in attempts] == [
        "ACKNOWLEDGED", "REJECTED", "UNDELIVERABLE", "ACKNOWLEDGED",
    ]
    assert [a["channel"] for a in attempts] == ["NETWORK", "NETWORK", "NETWORK", "FAX"]

    final = reload_prescription(prescription["id"])
    assert final["routing_attempt_count"] == 4
    assert reload_attempt(third_attempt["id"])["failure_code"] == "CF_0000"
    assert reload_attempt(fax_attempt["id"])["reported_at"] is not None