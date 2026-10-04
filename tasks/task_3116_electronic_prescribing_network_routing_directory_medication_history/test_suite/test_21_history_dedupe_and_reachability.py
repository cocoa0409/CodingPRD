"""Corner coverage: the dedupe ranking's fill authority, the input set's exclusions, and the
derived delivery-reachability enumeration.
"""
from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    setup_certified_pharmacy,
    register_participant,
    create_patient,
    grant_consent,
    revoke_consents,
    add_history_record,
    open_history_batch,
    aggregate_batch,
    reload_history_record,
    reload_patient,
    reload_endpoint,
    make_participant_admin_headers,
    TEST_USERS,
    api_client,
)

OPERATOR = TEST_USERS["network_operator_headers"]


def test_a_pharmacy_fill_wins_its_dedupe_group_against_a_larger_payer_claim(api):
    """PRD §3.8: "Rows from a `PHARMACY_FILL` source rank ahead of rows from a `PAYER_CLAIM`
    source regardless of what else they carry."
    PRD §3.8: "When a partition mixes fills and claims, the pharmacy fill wins even if the
    payer claim carries a larger quantity, since source rank is the first key."

    Design: Corner/calculations/medication_history_dedupe_fill_authority_beats_larger_payer_claim
    """
    set_clock()
    pharmacy, _ = setup_certified_pharmacy(
        endpoint_specs=[{"service_set": "MED_HISTORY", "endpoint_role": "RECEIVER",
                         "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
                         "message_standard": "NCPDP_SCRIPT_2022011"}]
    )
    patient = create_patient()
    grant_consent(patient["id"], scope="MEDICATION_HISTORY", duration_days=365)

    fill = add_history_record(
        patient["id"], pharmacy["id"], source_type="PHARMACY_FILL",
        drug_ndc="00093314905", fill_date="2026-06-01T00:00:00Z", days_supply=30, quantity=30,
    )
    claim = add_history_record(
        patient["id"], pharmacy["id"], source_type="PAYER_CLAIM",
        drug_ndc="00093314905", fill_date="2026-06-01T00:00:00Z", days_supply=30, quantity=90,
    )
    assert fill["dedupe_key"] == claim["dedupe_key"]

    batch = open_history_batch(patient["id"], pharmacy["id"])
    settled = aggregate_batch(batch["id"])

    assert settled["record_count"] == 1
    assert settled["superseded_count"] == 1
    assert reload_history_record(fill["id"])["is_superseded"] is False
    assert reload_history_record(claim["id"])["is_superseded"] is True
    assert reload_history_record(fill["id"])["aggregation_batch_id"] == batch["id"]
    assert reload_history_record(claim["id"])["aggregation_batch_id"] == batch["id"]


def test_the_dedupe_input_set_excludes_retracted_and_uncertified_sources(api):
    """PRD §3.8: "`source_record_count` is computed over the patient's medication history
    records whose `retracted_at` is null and whose source participant is `CERTIFIED`."
    PRD §3.8: "A reporting organization that is not `CERTIFIED` has its submission refused with
    `ERR_HISTORY_SOURCE_UNCERTIFIED` at HTTP 422."

    Design: Corner/calculations/batch_cost_and_dedupe_input_set_excludes_retracted_and_uncertified_sources
    """
    set_clock()
    pharmacy, _ = setup_certified_pharmacy(
        endpoint_specs=[{"service_set": "MED_HISTORY", "endpoint_role": "RECEIVER",
                         "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
                         "message_standard": "NCPDP_SCRIPT_2022011"}]
    )
    uncertified = register_participant("Harborside Pharmacy", "PHARMACY", "5555555555")
    assert uncertified["certification_status"] == "UNCERTIFIED"

    patient = create_patient(discard_on_revoke=True)
    grant_consent(patient["id"], scope="MEDICATION_HISTORY", duration_days=365)

    add_history_record(
        patient["id"], pharmacy["id"], drug_ndc="00093314905",
        fill_date="2026-06-01T00:00:00Z", days_supply=30, quantity=60,
    )
    refused = api_client.create_history_record(
        patient["id"],
        {"source_type": "PHARMACY_FILL", "source_participant_id": uncertified["id"],
         "drug_ndc": "00093314906", "fill_date": "2026-06-02T00:00:00Z",
         "days_supply": 30, "quantity": 30},
        TEST_USERS["hub_operator_headers"],
    )
    validate_error(refused, "ERR_HISTORY_SOURCE_UNCERTIFIED", expected_status=422)

    # Revoking with discard_on_revoke retracts the patient's live records, so they leave the
    # aggregation input set entirely.
    revoke_consents(patient["id"])
    grant_consent(patient["id"], scope="MEDICATION_HISTORY", duration_days=365)
    add_history_record(
        patient["id"], pharmacy["id"], drug_ndc="00093314907",
        fill_date="2026-06-03T00:00:00Z", days_supply=30, quantity=60,
    )

    batch = open_history_batch(patient["id"], pharmacy["id"])
    settled = aggregate_batch(batch["id"])

    assert settled["source_record_count"] == 1
    assert settled["record_count"] == 1
    assert settled["superseded_count"] == 0
    assert settled["batch_cost_cents"] == 35
    assert reload_patient(patient["id"])["history_record_count"] == 1


def test_delivery_reachability_counts_pending_endpoints_in_its_denominator(api):
    """PRD §2.4: "The total is the number of that participant's endpoints of every status,
    including those still `PENDING_CERT` and those already `DISABLED`."
    PRD §2.4: "When at least one endpoint is reachable but the reachable share of the total is
    below one half, the participant reads `AT_RISK`."

    Design: Corner/calculations/network_delivery_reachability_counts_pending_endpoints_in_its_denominator
    """
    set_clock()
    pharmacy, endpoints = setup_certified_pharmacy()
    active_endpoint = endpoints[0]
    hist = api_client.create_endpoint(
        pharmacy["id"],
        {"service_set": "MED_HISTORY", "endpoint_role": "RECEIVER",
         "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
         "message_standard": "NCPDP_SCRIPT_2022011",
         "effective_from": "2026-01-01T00:00:00Z", "effective_to": "2027-01-01T00:00:00Z"},
        make_participant_admin_headers(pharmacy["id"]),
    )
    elig = api_client.create_endpoint(
        pharmacy["id"],
        {"service_set": "ELIGIBILITY_FORMULARY", "endpoint_role": "RECEIVER",
         "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
         "message_standard": "NCPDP_SCRIPT_2022011",
         "effective_from": "2026-01-01T00:00:00Z", "effective_to": "2027-01-01T00:00:00Z"},
        make_participant_admin_headers(pharmacy["id"]),
    )
    # Endpoints registered after certification do not earn ACTIVE status.
    assert validate_success(hist, 201)["status"] == "PENDING_CERT"
    assert validate_success(elig, 201)["status"] == "PENDING_CERT"
    assert reload_endpoint(active_endpoint["id"])["status"] == "ACTIVE"

    report = validate_success(
        api_client.get_delivery_reachability(pharmacy["id"], OPERATOR), 200
    )
    assert report["reachable_endpoint_count"] == 1
    assert report["total_endpoint_count"] == 3
    assert report["delivery_reachability"] == "AT_RISK"