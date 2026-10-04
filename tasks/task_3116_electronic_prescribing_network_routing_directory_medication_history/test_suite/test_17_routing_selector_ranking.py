"""The routing selector's strictly ordered ranking over the candidate set.

Each ranking key decides before the next is consulted, so an earlier key can override a
better value on a later one — a shorter contracted SLA does not win against a worse service
level, and a matched message standard wins against a better service level.
"""
from test_helpers import (
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    setup_signed_prescription,
    route_prescription,
    reload_endpoint,
    TEST_USERS,
    api_client,
    validate_success,
)

OPERATOR = TEST_USERS["network_operator_headers"]


def _three_candidate_endpoints():
    """Three in-window NEW_RX endpoints on Riverbend Pharmacy, all ACTIVE with empty attempt
    history: ELIGIBLE_A/15min on the 2022011 standard, ELIGIBLE_A/10min on the 2017071
    standard, and ELIGIBLE_B/5min on the 2022011 standard. The order is a non-controlled
    NEW_RX on the 2022011 standard."""
    set_clock()
    clinic = create_clinic()
    add_endpoint(
        clinic["id"], service_set="NEW_RX", endpoint_role="SENDER", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    clinic = certify_participant(clinic["id"])

    pharmacy = create_pharmacy()
    winner = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=15, message_standard="NCPDP_SCRIPT_2022011",
    )
    std_mismatch = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_A",
        sla_response_minutes=10, message_standard="NCPDP_SCRIPT_2017071",
    )
    service_b = add_endpoint(
        pharmacy["id"], service_set="NEW_RX", endpoint_role="BOTH", service_level="ELIGIBLE_B",
        sla_response_minutes=5, message_standard="NCPDP_SCRIPT_2022011",
    )
    pharmacy = certify_participant(pharmacy["id"])

    patient = create_patient()
    prescription, _ = setup_signed_prescription(clinic["id"], pharmacy["id"], patient["id"])
    return clinic, pharmacy, patient, prescription, winner, std_mismatch, service_b


def test_message_standard_match_outranks_service_level(api):
    """PRD §3.4: "Among candidates of equal status, one whose `message_standard` equals the
    prescription's ranks ahead of one whose standard differs."
    PRD §3.4: "Among those, the `service_level` ordinal decides, with `ELIGIBLE_A` before
    `ELIGIBLE_B` before `ELIGIBLE_C`."

    Design: Difficulty/combinatorial_formula/routing_endpoint_selection_clamped_marginal_schedule
    """
    clinic, pharmacy, patient, prescription, winner, std_mismatch, service_b = (
        _three_candidate_endpoints()
    )

    routed = route_prescription(prescription["id"], clinic["id"])
    assert routed["routed_endpoint_id"] == winner["id"]
    assert routed["routed_endpoint_id"] != std_mismatch["id"], (
        "the ELIGIBLE_A endpoint at a 10-minute SLA is not selected: the standard-match key "
        "outranks the service-level key"
    )
    assert routed["routed_endpoint_id"] != service_b["id"]


def test_service_level_outranks_the_contracted_response_time(api):
    """PRD §3.4: "Then the shortest `sla_response_minutes` wins."
    PRD §3.4: "Among those, the `service_level` ordinal decides, with `ELIGIBLE_A` before
    `ELIGIBLE_B` before `ELIGIBLE_C`."

    Design: Difficulty/combinatorial_formula/routing_endpoint_selection_clamped_marginal_schedule
    """
    clinic, pharmacy, patient, prescription, winner, std_mismatch, service_b = (
        _three_candidate_endpoints()
    )

    routed = route_prescription(prescription["id"], clinic["id"])
    assert routed["routed_endpoint_id"] != service_b["id"], (
        "the ELIGIBLE_B endpoint at a 5-minute SLA is not selected: the service-level key "
        "outranks the SLA key"
    )
    assert reload_endpoint(service_b["id"])["sla_response_minutes"] == 5
    assert reload_endpoint(winner["id"])["sla_response_minutes"] == 15

    assert routed["routing_status"] == "ROUTED"
    assert routed["clinical_status"] == "ROUTED"
    assert routed["routing_attempt_count"] == 1

    listed = validate_success(
        api_client.list_participant_endpoints(pharmacy["id"], OPERATOR), 200
    )
    assert len(listed) == 3
    assert {row["status"] for row in listed} == {"ACTIVE"}