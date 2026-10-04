"""Certification preconditions evaluated after the state-admission band.

A promotion request that violates both the state band and the certification-completeness band
reports the state failure, because the state check sits above the certification check in the
fixed validation order.
"""
from test_helpers import (
    validate_error,
    set_clock,
    create_pharmacy,
    add_endpoint,
    reload_participant,
    make_participant_admin_headers,
    api_client,
)


def test_certify_before_moving_into_certification_reports_the_state_error(api):
    """PRD §2.9: "State admission follows: the target resource must be in a state that admits
    the requested operation, and rejection here uses `ERR_INVALID_STATE`,
    `ERR_ROUTE_ATTEMPT_IN_PROGRESS`, `ERR_ALREADY_TERMINAL`, or `ERR_LAST_ACTIVE_ENDPOINT`,
    all at HTTP 409."
    PRD §3.2: "First, `certification_tests_passed` must cover at least `CONNECTIVITY` and
    `SCRIPT_NEW_RX`; a shortfall is refused with `ERR_CERT_TESTS_INCOMPLETE`."

    Design: Difficulty/priority_pair_validation_conflict/certification_priority_business_referential_over_state
    """
    set_clock()
    pharmacy = create_pharmacy()
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )

    before = reload_participant(pharmacy["id"])
    assert before["certification_status"] == "UNCERTIFIED"
    assert before["certification_tests_passed"] == []

    response = api_client.certify_participant(
        pharmacy["id"], before["version"], make_participant_admin_headers(pharmacy["id"])
    )
    error = validate_error(response, "ERR_INVALID_STATE", expected_status=409)
    assert error["error_id"] != "ERR_CERT_TESTS_INCOMPLETE"


def test_the_rejected_promotion_leaves_the_participant_untouched(api):
    """PRD §2.9: "Requests are validated in a fixed priority order, and the first failure ends
    the request with its own error."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Difficulty/priority_pair_validation_conflict/certification_priority_business_referential_over_state
    """
    set_clock()
    pharmacy = create_pharmacy()
    add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )

    before = reload_participant(pharmacy["id"])
    response = api_client.certify_participant(
        pharmacy["id"], before["version"], make_participant_admin_headers(pharmacy["id"])
    )
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["error_id"], str)
    assert body["data"]["message"].strip()

    after = reload_participant(pharmacy["id"])
    assert after["certification_status"] == "UNCERTIFIED"
    assert after["certification_tests_passed"] == []
    assert after["directory_listed"] is False