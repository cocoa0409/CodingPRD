"""Corner coverage: the remaining error-raising paths — a fallback with nothing to fall back
on, a fax channel that was never provisioned, a zero-length consent window, an un-reversible
fee entry, and the two authentication bands.
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
    setup_routed_prescription,
    report_undeliverable,
    reload_prescription,
    post_fee_entry,
    create_fallback_attempt,
    reload_fee_entry,
    reverse_fee_entry,
    reload_participant,
    make_prescriber_headers,
    TEST_USERS,
    api_client,
)

OPERATOR = TEST_USERS["network_operator_headers"]
HUB = TEST_USERS["hub_operator_headers"]


def _certified_pair(clinic_overrides=None, pharmacy_endpoint_specs=None):
    set_clock()
    clinic = create_clinic(**(clinic_overrides or {}))
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])
    pharmacy = create_pharmacy()
    specs = pharmacy_endpoint_specs or [{}]
    endpoints = [add_endpoint(pharmacy["id"], **spec) for spec in specs]
    pharmacy = certify_participant(pharmacy["id"])
    return clinic, pharmacy, endpoints


def test_falling_back_from_an_order_with_no_failed_attempt_is_refused(api):
    """PRD §3.5: "requires at least one attempt of this prescription to already carry an
    outcome of `UNDELIVERABLE` or `REJECTED`, or the request is refused with
    `ERR_NO_FAILED_ATTEMPT_TO_FALL_BACK`."

    Design: Corner/endpoints/deliverable_fallback_flow_requires_a_failed_attempt_first
    """
    clinic, pharmacy, _ = _certified_pair()
    patient = create_patient()
    prescription, attempt = setup_routed_prescription(
        clinic["id"], pharmacy["id"], patient["id"]
    )
    assert prescription["routing_status"] == "ROUTED"
    prescriber = make_prescriber_headers(clinic["id"])

    early = api_client.route_fallback(prescription["id"], prescriber)
    validate_error(early, "ERR_NO_FAILED_ATTEMPT_TO_FALL_BACK", expected_status=422)
    assert reload_prescription(prescription["id"])["routing_status"] == "ROUTED"

    # After the failed attempt is reported, the same call moves the order to the fallback.
    report_undeliverable(attempt["id"], "CF_0000")
    failed = reload_prescription(prescription["id"])
    assert failed["routing_status"] == "ROUTE_FAILED"
    assert failed["routing_attempt_count"] == 1

    moved = validate_success(api_client.route_fallback(prescription["id"], prescriber), 200)
    assert moved["routing_status"] == "FALLBACK_PENDING"


def test_the_fallback_attempt_is_only_created_by_its_own_endpoint(api):
    """PRD §3.5: "The fallback attempt itself may be opened directly: creating a fallback
    attempt requires a `channel`, and it starts `IN_PROGRESS` with `target_endpoint_id` null
    and `attempt_no` set to one more than the prescription's current `routing_attempt_count`"

    Design: Corner/endpoints/deliverable_fallback_flow_requires_a_failed_attempt_first
    """
    clinic, pharmacy, _ = _certified_pair()
    patient = create_patient()
    prescription, attempt = setup_routed_prescription(
        clinic["id"], pharmacy["id"], patient["id"]
    )
    report_undeliverable(attempt["id"], "CF_0000")
    prescriber = make_prescriber_headers(clinic["id"])
    validate_success(api_client.route_fallback(prescription["id"], prescriber), 200)

    attempts = validate_success(api_client.list_attempts(prescription["id"], OPERATOR), 200)
    assert len(attempts) == 1, (
        "the fallback attempt is only created by the fallback-attempts endpoint"
    )

    fax = create_fallback_attempt(prescription["id"], clinic["id"], "FAX")
    assert fax["channel"] == "FAX"
    assert fax["outcome"] == "IN_PROGRESS"
    assert fax["target_endpoint_id"] is None
    assert fax["attempt_no"] == 2

    after = reload_prescription(prescription["id"])
    assert after["routing_attempt_count"] == 2


def test_a_fax_fallback_without_a_number_is_refused(api):
    """PRD §3.5: "requires `fallback_channel` to be `FAX` or `PRINT` with a present
    `fax_number` when the channel is fax — otherwise `ERR_FALLBACK_CHANNEL_UNAVAILABLE`"

    Design: Corner/errors/fallback_on_a_fax_channel_without_a_fax_number_is_refused
    """
    clinic, pharmacy, _ = _certified_pair(clinic_overrides={"fax_number": None})
    assert clinic["fallback_channel"] == "FAX"
    assert clinic["fax_number"] is None

    patient = create_patient()
    prescription, attempt = setup_routed_prescription(
        clinic["id"], pharmacy["id"], patient["id"]
    )
    report_undeliverable(attempt["id"], "CF_0000")
    assert reload_prescription(prescription["id"])["routing_status"] == "ROUTE_FAILED"

    response = api_client.route_fallback(
        prescription["id"], make_prescriber_headers(clinic["id"])
    )
    validate_error(response, "ERR_FALLBACK_CHANNEL_UNAVAILABLE", expected_status=422)
    assert reload_prescription(prescription["id"])["routing_status"] == "ROUTE_FAILED"


def test_a_zero_length_consent_window_is_written_as_expired(api):
    """PRD §3.8: "The new consent's `status` is written `ACTIVE` when `expires_at` is later
    than the current logical clock and `EXPIRED` otherwise; a zero-length duration therefore
    produces an empty interval whose status is `EXPIRED`, the condition behind
    `ERR_CONSENT_EXPIRED`."

    Design: Corner/errors/zero_duration_consent_grant_expires_immediately
    """
    set_clock()
    patient = create_patient()

    consent = validate_success(
        api_client.grant_consent(
            patient["id"], {"scope": "MEDICATION_HISTORY", "duration_days": 0},
            TEST_USERS["patient_service_headers"],
        ),
        201,
    )
    assert consent["status"] == "EXPIRED"
    assert consent["expires_at"] == consent["granted_at"]

    after = validate_success(api_client.get_patient(patient["id"],
                                                     TEST_USERS["patient_service_headers"]), 200)
    assert after["consent_status"] == "EXPIRED"
    assert after["consent_version"] == 1

    readable = validate_success(
        api_client.get_consent(consent["id"], TEST_USERS["patient_service_headers"]), 200
    )
    assert readable["status"] == "EXPIRED"


def test_reversing_an_entry_twice_or_its_compensation_is_refused(api):
    """PRD §3.7: "the target entry's `status` must be `POSTED`, it must not be an unsettled
    `PARTIAL` accrual, it must not itself be a compensating row — its `reversal_of_entry_id`
    must be null — and it must not already have been reversed. Any violation is refused with
    `ERR_ENTRY_NOT_REVERSIBLE` at HTTP 422."

    Design: Corner/errors/reverse_of_an_already_reversed_entry_returns_entry_not_reversible
    """
    set_clock()
    clinic = create_clinic()
    entry = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=500
    )
    assert entry["fee_cents"] == 3600

    compensation = reverse_fee_entry(entry["id"], clinic["id"])
    validate_error(
        reverse_fee_entry(entry["id"], clinic["id"], expect_success=False),
        "ERR_ENTRY_NOT_REVERSIBLE",
        expected_status=422,
    )
    validate_error(
        reverse_fee_entry(compensation["id"], clinic["id"], expect_success=False),
        "ERR_ENTRY_NOT_REVERSIBLE",
        expected_status=422,
    )

    reversal_rows = validate_success(
        api_client.get_fee_reversal(entry["id"], OPERATOR), 200
    )
    assert len(reversal_rows) == 1
    assert reversal_rows[0]["id"] == compensation["id"]
    assert reload_fee_entry(entry["id"])["period_net_total_cents"] == 0


def test_the_authentication_band_runs_before_anything_else(api):
    """PRD §2.1: "A request that omits `X-User-Role`, or supplies a value that is not one of
    these six, is refused with `ERR_UNAUTHENTICATED` and an HTTP 401."

    Design: Corner/cross_cutting_layers/missing_role_header_returns_unauthenticated
    """
    set_clock()
    pharmacy = create_pharmacy()

    response = api_client.get_participant(pharmacy["id"], {})
    validate_error(response, "ERR_UNAUTHENTICATED", expected_status=401)

    body = response.json()
    assert body["response_type"] == "error"
    assert "data" in body and "error_id" in body["data"]
    assert "name" not in body["data"]