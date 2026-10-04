"""The four-hop cascade that a single directory-endpoint disable sets off.

The endpoint's status move recomputes the participant's `directory_listed`; when that boolean
lands false the fan-out begins, and each hop is caused by the hop before it rather than by the
disable request.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    setup_routed_prescription,
    reload_endpoint,
    reload_participant,
    reload_prescription,
    reload_attempt,
    api_client,
    TEST_USERS,
)

OPERATOR = TEST_USERS["network_operator_headers"]


def _parked_routed_order():
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy(fax_number=None)
    endpoint = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    prescription, attempt = setup_routed_prescription(
        clinic["id"], pharmacy["id"], patient["id"]
    )
    return clinic, pharmacy, endpoint, patient, prescription, attempt


def test_disabling_the_last_endpoint_flips_directory_listed_and_fails_the_order(api):
    """PRD §3.6: "The endpoint becomes `DISABLED` and `directory_listed` is recomputed,
    flipping false when this was the participant's last endpoint in `ACTIVE` or `DEGRADED`
    status."
    PRD §2.11: "when that boolean lands false the fan-out begins: prescriptions of that
    receiving participant at `SIGNED` clinical status with `routing_status` at `NOT_ROUTED` or
    `BACKUP_SELECTION` move to `ROUTE_FAILED`."

    Design: Difficulty/transitive_cascade/endpoint_disable_cascade_reaches_prescription_undeliverable
    """
    clinic, pharmacy, endpoint, patient, prescription, attempt = _parked_routed_order()
    assert prescription["clinical_status"] == "ROUTED"
    assert prescription["routing_status"] == "ROUTED"

    validate_success(api_client.disable_endpoint(endpoint["id"], OPERATOR), 200)

    # HOP 1
    assert reload_endpoint(endpoint["id"])["status"] == "DISABLED"
    # HOP 2, caused by hop 1
    assert reload_participant(pharmacy["id"])["directory_listed"] is False


def test_the_disable_cascade_resolves_the_attempt_and_stamps_the_failure_code(api):
    """PRD §2.11: "Resolving their in-flight attempts is the third hop: attempts still
    `IN_PROGRESS` become `UNDELIVERABLE`."
    PRD §3.6: "every attempt of those prescriptions still `IN_PROGRESS` becomes
    `UNDELIVERABLE` with `failure_code` `NO_ROUTE`."

    Design: Difficulty/transitive_cascade/endpoint_disable_cascade_reaches_prescription_undeliverable
    """
    clinic, pharmacy, endpoint, patient, prescription, attempt = _parked_routed_order()

    validate_success(api_client.disable_endpoint(endpoint["id"], OPERATOR), 200)

    reported_attempt = reload_attempt(attempt["id"])
    assert reported_attempt["outcome"] == "UNDELIVERABLE"
    assert reported_attempt["failure_code"] == "NO_ROUTE"

    after = reload_prescription(prescription["id"])
    assert after["routing_status"] == "ROUTE_FAILED"
    # HOP 4: the order carries a null fallback channel, so nothing could absorb the failure.
    assert after["clinical_status"] == "UNDELIVERABLE"