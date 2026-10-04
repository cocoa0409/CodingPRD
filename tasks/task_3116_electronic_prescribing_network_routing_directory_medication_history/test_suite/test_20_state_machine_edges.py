"""Corner coverage: invalid transitions on the prescription and signing-session machines,
and the two-factor attempt ceiling.
"""
from test_helpers import (
    validate_error,
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    create_prescription,
    setup_delivered_prescription,
    create_ready_session,
    open_signing_session,
    reload_prescription,
    reload_signing_session,
    make_prescriber_headers,
    api_client,
    TEST_USERS,
)

OPERATOR = TEST_USERS["network_operator_headers"]


def test_signing_a_delivered_order_is_refused_and_leaves_the_signature_authority(api):
    """PRD §3.4: "Note that the routing machine's `NOT_ROUTED` to `ROUTING` transition
    requires `clinical_status` to be `SIGNED`, so a route call on a draft is refused with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sign_from_already_delivered_prescription_returns_invalid_state
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    delivered, first_attempt = setup_delivered_prescription(
        clinic["id"], pharmacy["id"], patient["id"]
    )
    assert delivered["clinical_status"] == "DELIVERED"
    signature_before = delivered["signature_audit_id"]
    assert signature_before is not None

    second_session = create_ready_session(delivered["id"], clinic["id"])
    response = api_client.sign_prescription(
        delivered["id"], second_session["id"], make_prescriber_headers(clinic["id"])
    )
    validate_error(response, "ERR_INVALID_STATE", expected_status=409)

    after = reload_prescription(delivered["id"])
    assert after["clinical_status"] == "DELIVERED"
    assert after["signature_audit_id"] == signature_before


def test_the_rejected_signing_session_is_left_unconsumed(api):
    """PRD §3.3: "The referenced session must belong to this prescription, must still be
    `OPEN`, must carry `identity_proofing_status` of `PASSED`, and must carry
    `two_factor_status` of `PASSED`"

    Design: Corner/state_machines/sign_from_already_delivered_prescription_returns_invalid_state
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    delivered, _ = setup_delivered_prescription(clinic["id"], pharmacy["id"], patient["id"])
    second_session = create_ready_session(delivered["id"], clinic["id"])
    api_client.sign_prescription(
        delivered["id"], second_session["id"], make_prescriber_headers(clinic["id"])
    )

    session_after = reload_signing_session(second_session["id"])
    assert session_after["session_status"] == "OPEN"
    assert session_after["identity_proofing_status"] == "PASSED"
    assert session_after["two_factor_status"] == "PASSED"


def test_the_third_failed_challenge_locks_the_session(api):
    """PRD §3.3: "A mismatch increments `otp_attempt_count` and is refused with `ERR_OTP_INVALID`
    at HTTP 422; when the increment carries `otp_attempt_count` to three, `two_factor_status`
    becomes `LOCKED` and the session is refused thereafter with `ERR_ACCOUNT_LOCKED`."

    Design: Corner/state_machines/signing_session_two_factor_locks_after_three_failed_challenges
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    prescription = create_prescription(clinic["id"], pharmacy["id"], patient["id"])
    session = open_signing_session(prescription["id"], clinic["id"])
    prescriber = make_prescriber_headers(clinic["id"])

    from test_helpers import get_success_data, api_client as client
    get_success_data(client.identity_proof(session["id"], "PASSED", prescriber))
    issued = get_success_data(client.request_otp(session["id"], prescriber))
    assert issued["two_factor_status"] == "PENDING"

    first = client.verify_otp(session["id"], "000000", prescriber)
    validate_error(first, "ERR_OTP_INVALID", expected_status=422)
    second = client.verify_otp(session["id"], "111111", prescriber)
    validate_error(second, "ERR_OTP_INVALID", expected_status=422)

    third = client.verify_otp(session["id"], "222222", prescriber)
    validate_error(third, "ERR_ACCOUNT_LOCKED", expected_status=423)

    locked = reload_signing_session(session["id"])
    assert locked["two_factor_status"] == "LOCKED"
    assert locked["otp_attempt_count"] == 3
    assert locked["session_status"] == "OPEN"


def test_a_locked_session_cannot_be_driven_back_into_verification(api):
    """PRD §3.3: "The session cannot start a third-factor verification attempt while
    `otp_attempt_count` is already at three, since that guard is evaluated before the
    comparison."
    PRD §3.3: "a session whose `two_factor_status` is already `LOCKED` is refused with
    `ERR_ACCOUNT_LOCKED` at HTTP 423."

    Design: Corner/state_machines/signing_session_two_factor_locks_after_three_failed_challenges
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    prescription = create_prescription(clinic["id"], pharmacy["id"], patient["id"])
    session = open_signing_session(prescription["id"], clinic["id"])
    prescriber = make_prescriber_headers(clinic["id"])

    from test_helpers import get_success_data, api_client as client
    get_success_data(client.identity_proof(session["id"], "PASSED", prescriber))
    issued = get_success_data(client.request_otp(session["id"], prescriber))
    real_code = issued["otp_challenge_code"]

    for wrong in ("000000", "111111", "222222"):
        client.verify_otp(session["id"], wrong, prescriber)

    # The challenge cannot be reissued on a locked session.
    validate_error(
        client.request_otp(session["id"], prescriber), "ERR_ACCOUNT_LOCKED", expected_status=423
    )
    # And the correct code, had it ever been issued, is now unusable.
    validate_error(
        client.verify_otp(session["id"], real_code, prescriber),
        "ERR_ACCOUNT_LOCKED",
        expected_status=423,
    )


def test_cancelling_an_unsigned_order_is_refused_by_the_state_machine(api):
    """PRD §3.5: "A `Prescriber` may cancel a prescription sitting at `ROUTED` or
    `BACKUP_SELECTION` routing status, moving `clinical_status` to `CANCELLED` and taking any
    attempt still `IN_PROGRESS` to `REJECTED` with `failure_code` `PRESCRIPTION_CANCELLED`."
    PRD §3.5: "A routing status other than those four is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_from_draft_prescription_returns_invalid_state
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    draft = create_prescription(clinic["id"], pharmacy["id"], patient["id"])
    assert draft["clinical_status"] == "DRAFT"
    assert draft["routing_status"] == "NOT_ROUTED"

    response = api_client.cancel_prescription(
        draft["id"], make_prescriber_headers(clinic["id"])
    )
    validate_error(response, "ERR_INVALID_STATE", expected_status=409)

    after = reload_prescription(draft["id"])
    assert after["clinical_status"] == "DRAFT"
    assert after["routing_status"] == "NOT_ROUTED"
    attempts = api_client.list_attempts(draft["id"], OPERATOR).json()["data"]
    assert attempts == []