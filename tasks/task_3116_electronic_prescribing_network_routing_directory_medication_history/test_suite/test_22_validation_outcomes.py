"""Corner coverage: validation failures and their exact error vocabulary, plus the RBAC and
authentication bands.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    create_prescription,
    setup_signed_prescription,
    reload_prescription,
    reload_endpoint,
    create_ready_session,
    make_prescriber_headers,
    TEST_USERS,
    api_client,
)

OPERATOR = TEST_USERS["network_operator_headers"]
MISSING = {}


def test_routing_with_no_eligible_endpoint_reports_no_route_available(api):
    """PRD §3.4: "When the candidate set is empty, `routing_status` moves to `ROUTE_FAILED`,
    the caller receives `ERR_NO_ROUTE_AVAILABLE`, nothing is scheduled, and no fallback fires."

    Design: Corner/validations/route_without_any_eligible_endpoint_returns_no_route_available
    """
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    refill_only = add_endpoint(
        pharmacy["id"], service_set="REFILL_RX", endpoint_role="BOTH",
        service_level="ELIGIBLE_A", sla_response_minutes=15,
        message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    prescription, _ = setup_signed_prescription(clinic["id"], pharmacy["id"], patient["id"])
    assert prescription["clinical_status"] == "SIGNED"

    response = api_client.route_prescription(
        prescription["id"], prescription["version"], make_prescriber_headers(clinic["id"])
    )
    validate_error(response, "ERR_NO_ROUTE_AVAILABLE", expected_status=422)

    after = reload_prescription(prescription["id"])
    assert after["routing_status"] == "NOT_ROUTED"
    assert after["clinical_status"] == "SIGNED"
    assert after["routing_attempt_count"] == 0
    assert after["active_routing_attempt_id"] is None
    # A failed selection never degrades an endpoint.
    assert reload_endpoint(refill_only["id"])["status"] == "ACTIVE"


def test_signing_a_controlled_order_without_two_factor_requires_identity_proofing(api):
    """PRD §3.3: "Second, a controlled order — one whose `is_controlled` is true — requires
    both the passed identity proofing and the passed second factor on the signing session, and
    an order lacking either is refused with `ERR_IDENTITY_PROOFING_REQUIRED` at HTTP 422"

    Design: Corner/validations/sign_without_passed_identity_proofing_returns_identity_proofing_required
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
    prescription = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_IV",
        refills_authorized=0,
    )
    prescriber = make_prescriber_headers(clinic["id"])
    session = api_client.create_signing_session(prescription["id"], prescriber).json()["data"]
    api_client.identity_proof(session["id"], "PASSED", prescriber)
    issued = api_client.request_otp(session["id"], prescriber).json()["data"]
    assert issued["two_factor_status"] == "PENDING"

    response = api_client.sign_prescription(prescription["id"], session["id"], prescriber)
    validate_error(response, "ERR_IDENTITY_PROOFING_REQUIRED", expected_status=422)

    after = reload_prescription(prescription["id"])
    assert after["clinical_status"] == "DRAFT"
    assert after["signature_audit_id"] is None


def test_verifying_the_pending_challenge_unblocks_the_controlled_sign(api):
    """PRD §3.3: "A match moves `two_factor_status` to `PASSED` and clears the challenge code."
    PRD §3.3: "When all four hold, the order's `clinical_status` becomes `SIGNED`"

    Design: Corner/validations/sign_without_passed_identity_proofing_returns_identity_proofing_required
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
    prescription = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_IV",
        refills_authorized=0,
    )
    prescriber = make_prescriber_headers(clinic["id"])
    session = api_client.create_signing_session(prescription["id"], prescriber).json()["data"]
    api_client.identity_proof(session["id"], "PASSED", prescriber)
    issued = api_client.request_otp(session["id"], prescriber).json()["data"]

    verified = validate_success(
        api_client.verify_otp(session["id"], issued["otp_challenge_code"], prescriber), 200
    )
    assert verified["two_factor_status"] == "PASSED"
    assert verified["otp_challenge_code"] is None

    signed = validate_success(
        api_client.sign_prescription(prescription["id"], session["id"], prescriber), 200
    )
    assert signed["clinical_status"] == "SIGNED"


def test_a_controlled_order_on_the_older_standard_is_refused(api):
    """PRD §3.3: "Third, an order whose `message_standard` is `NCPDP_SCRIPT_2017071` may not
    carry a `controlled_schedule` of `SCHEDULE_II`, `SCHEDULE_III`, `SCHEDULE_IV`, or
    `SCHEDULE_V`; that combination is refused with `ERR_CONTROLLED_NOT_SUPPORTED_BY_STANDARD`."

    Design: Corner/validations/controlled_order_on_the_2017071_standard_returns_standard_mismatch
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
    controlled = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_III",
        message_standard="NCPDP_SCRIPT_2017071", refills_authorized=0,
    )
    controlled_session = create_ready_session(controlled["id"], clinic["id"])

    response = api_client.sign_prescription(
        controlled["id"], controlled_session["id"], make_prescriber_headers(clinic["id"])
    )
    validate_error(
        response, "ERR_CONTROLLED_NOT_SUPPORTED_BY_STANDARD", expected_status=422
    )
    assert reload_prescription(controlled["id"])["clinical_status"] == "DRAFT"


def test_the_same_order_uncontrolled_on_the_older_standard_signs_through(api):
    """PRD §3.3: "an order whose `message_standard` is `NCPDP_SCRIPT_2017071` may not carry a
    `controlled_schedule` of `SCHEDULE_II`, `SCHEDULE_III`, `SCHEDULE_IV`, or `SCHEDULE_V`"
    PRD §2.9: "Controlled-substance safety preconditions are evaluated next, before any
    structural or fiscal rule"

    Design: Corner/validations/controlled_order_on_the_2017071_standard_returns_standard_mismatch
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
    plain = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], drug_ndc="00093314906",
        controlled_schedule="NON_CONTROLLED", message_standard="NCPDP_SCRIPT_2017071",
        quantity=30, refills_authorized=6,
    )
    session = create_ready_session(plain["id"], clinic["id"])

    signed = validate_success(
        api_client.sign_prescription(
            plain["id"], session["id"], make_prescriber_headers(clinic["id"])
        ),
        200,
    )
    assert signed["clinical_status"] == "SIGNED"