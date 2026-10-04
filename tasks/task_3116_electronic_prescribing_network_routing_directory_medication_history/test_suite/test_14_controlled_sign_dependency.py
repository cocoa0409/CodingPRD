"""Cross-entity gates: a prescribed order's signing depends on the receiving pharmacy's
directory state, and a history batch's advance depends on the patient's consent scope.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    start_certification_window,
    certify_participant,
    create_patient,
    create_prescription,
    create_ready_session,
    reload_prescription,
    reload_endpoint,
    make_prescriber_headers,
    api_client,
)


def test_a_controlled_order_cannot_be_signed_while_the_pharmacy_endpoint_is_pending(api):
    """PRD §3.3: "Fourth, a controlled order requires that the receiving pharmacy hold a
    directory endpoint for `service_set` `NEW_RX` in `ACTIVE` status; absent that, the sign is
    refused with `ERR_PHARMACY_NOT_CERTIFIED_FOR_CONTROLLED`."

    Design: Difficulty/cross_entity_state_dependency/controlled_sign_requires_pharmacy_endpoint_active
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    # The pharmacy holds exactly one NEW_RX endpoint and sits in IN_CERTIFICATION, so that
    # endpoint is still PENDING_CERT.
    pharmacy = create_pharmacy()
    endpoint = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    start_certification_window(pharmacy["id"])
    assert reload_endpoint(endpoint["id"])["status"] == "PENDING_CERT"

    patient = create_patient()
    prescription = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_II",
        refills_authorized=0,
    )
    session = create_ready_session(prescription["id"], clinic["id"])

    response = api_client.sign_prescription(
        prescription["id"], session["id"], make_prescriber_headers(clinic["id"])
    )
    validate_error(response, "ERR_PHARMACY_NOT_CERTIFIED_FOR_CONTROLLED", expected_status=422)

    after = reload_prescription(prescription["id"])
    assert after["clinical_status"] == "DRAFT"
    assert after["signature_audit_id"] is None


def test_the_same_sign_succeeds_once_the_endpoint_becomes_active(api):
    """PRD §2.9: "Controlled-substance safety preconditions are evaluated next, before any
    structural or fiscal rule, so an order that is both controlled and missing its two-factor
    evidence surfaces the safety error rather than a downstream one."
    PRD §3.2: "The participant's `certification_status` becomes `CERTIFIED`, and — in the same
    transaction — every one of its endpoints still sitting in `PENDING_CERT` becomes `ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/controlled_sign_requires_pharmacy_endpoint_active
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    endpoint = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    start_certification_window(pharmacy["id"])

    patient = create_patient()
    prescription = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_II",
        refills_authorized=0,
    )
    session = create_ready_session(prescription["id"], clinic["id"])

    # Promote the pharmacy; the endpoint move to ACTIVE is the only thing that changed.
    certify_participant(pharmacy["id"])
    assert reload_endpoint(endpoint["id"])["status"] == "ACTIVE"

    signed = validate_success(
        api_client.sign_prescription(
            prescription["id"], session["id"], make_prescriber_headers(clinic["id"])
        ),
        200,
    )
    assert signed["clinical_status"] == "SIGNED"
    assert signed["signature_audit_id"] == session["id"]