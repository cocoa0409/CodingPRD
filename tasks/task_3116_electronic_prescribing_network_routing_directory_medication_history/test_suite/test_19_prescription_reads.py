"""Corner coverage: the computed prescription flags, the filtering list read, and the child
read paths a prescription exposes.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_clinic,
    create_pharmacy,
    add_endpoint,
    certify_participant,
    create_patient,
    create_prescription,
    grant_consent,
    setup_signed_prescription,
    route_prescription,
    TEST_USERS,
    api_client,
)

OPERATOR = TEST_USERS["network_operator_headers"]


def _certified_pair():
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
    return clinic, pharmacy


def test_prescription_flags_are_computed_from_the_schedule_and_the_patients_consent(api):
    """PRD §3.3: "the computed flags are derived immediately: `is_controlled` is true exactly
    when `controlled_schedule` differs from `NON_CONTROLLED`, and `significance` is `CRITICAL`
    when the schedule is `SCHEDULE_II` or `SCHEDULE_III` or when `monitored_under_consent` is
    true, and `STANDARD` in every other case."

    Design: Corner/entities/prescription_significance_and_is_controlled_are_computed_never_supplied
    """
    clinic, pharmacy = _certified_pair()
    patient = create_patient()
    # A `BENEFIT_CHECK` consent is deliberately not a medication-history consent, so the
    # non-controlled order is not `monitored_under_consent` and reads `STANDARD` while the
    # SCHEDULE_II order reads `CRITICAL` on its schedule alone.
    grant_consent(patient["id"], scope="BENEFIT_CHECK", duration_days=365)

    controlled = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], drug_ndc="00093314905",
        controlled_schedule="SCHEDULE_II", refills_authorized=0,
    )
    plain = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], drug_ndc="00093314906",
        controlled_schedule="NON_CONTROLLED", quantity=30, refills_authorized=6,
    )

    assert controlled["is_controlled"] is True
    assert controlled["significance"] == "CRITICAL"
    assert plain["is_controlled"] is False
    assert plain["significance"] == "STANDARD"


def test_a_new_draft_starts_with_no_attempt_and_no_signature_authority(api):
    """PRD §3.3: "A draft starts in `DRAFT` clinical status and `NOT_ROUTED` routing status,
    with `refills_used` and `routing_attempt_count` at zero"

    Design: Corner/entities/prescription_significance_and_is_controlled_are_computed_never_supplied
    """
    clinic, pharmacy = _certified_pair()
    patient = create_patient()
    grant_consent(patient["id"], scope="MEDICATION_HISTORY", duration_days=365)

    draft = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_II",
        refills_authorized=0,
    )
    assert draft["clinical_status"] == "DRAFT"
    assert draft["routing_status"] == "NOT_ROUTED"
    assert draft["refills_used"] == 0
    assert draft["routing_attempt_count"] == 0
    assert draft["active_routing_attempt_id"] is None
    assert draft["signature_audit_id"] is None
    assert draft["monitored_under_consent"] is True


def test_prescription_list_filters_by_relationship_and_status(api):
    """PRD §4: "List prescriptions with status and relationship filters"

    Design: Corner/endpoints/prescriptions_filtered_list_finds_children_by_pharmacy_endpoint_and_significance
    """
    clinic, pharmacy = _certified_pair()
    patient = create_patient()
    controlled = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_II",
        refills_authorized=0,
    )
    draft = create_prescription(
        clinic["id"], pharmacy["id"], patient["id"], drug_ndc="00093314906",
        controlled_schedule="NON_CONTROLLED", quantity=30,
    )

    signed, session = setup_signed_prescription(
        clinic["id"], pharmacy["id"], patient["id"], controlled_schedule="SCHEDULE_II",
        refills_authorized=0,
    )
    routed = route_prescription(signed["id"], clinic["id"])

    by_pharmacy = validate_success(
        api_client.list_prescriptions(OPERATOR, {"receiving_pharmacy_id": pharmacy["id"]}), 200
    )
    assert len(by_pharmacy) == 3

    critical = validate_success(
        api_client.list_prescriptions(OPERATOR, {"significance": "CRITICAL"}), 200
    )
    assert {row["id"] for row in critical} == {controlled["id"], routed["id"]}

    by_endpoint = validate_success(
        api_client.list_prescriptions(OPERATOR, {"routed_endpoint_id": routed["routed_endpoint_id"]}), 200
    )
    assert {row["id"] for row in by_endpoint} == {routed["id"]}

    drafts = validate_success(
        api_client.list_prescriptions(OPERATOR, {"clinical_status": "DRAFT"}), 200
    )
    assert {row["id"] for row in drafts} == {controlled["id"], draft["id"]}

    signature = validate_success(
        api_client.get_signature_session(routed["id"], OPERATOR), 200
    )
    assert len(signature) == 1
    assert signature[0]["id"] == session["id"]

    chosen = validate_success(api_client.get_routed_endpoint(routed["id"], OPERATOR), 200)
    assert len(chosen) == 1
    assert chosen[0]["id"] == routed["routed_endpoint_id"]

    active = validate_success(api_client.get_active_attempt(routed["id"], OPERATOR), 200)
    assert len(active) == 1
    assert active[0]["outcome"] == "IN_PROGRESS"