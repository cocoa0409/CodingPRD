"""The consent gate on medication history aggregation.

Advancing a batch out of PENDING requires an ACTIVE consent whose scope covers medication
history, so a benefit-check-only consent blocks the advance outright.
"""
from test_helpers import (
    validate_error,
    set_clock,
    setup_certified_pharmacy,
    create_patient,
    grant_consent,
    add_history_record,
    open_history_batch,
    reload_batch,
    reload_history_record,
    reload_patient,
    revoke_consents,
    TEST_USERS,
    api_client,
)

HUB = TEST_USERS["hub_operator_headers"]


def _pharmacy_and_patient_with_consent(scope, duration_days=365):
    set_clock()
    pharmacy, _ = setup_certified_pharmacy(
        endpoint_specs=[{"service_set": "MED_HISTORY", "endpoint_role": "RECEIVER",
                         "service_level": "ELIGIBLE_A", "sla_response_minutes": 60,
                         "message_standard": "NCPDP_SCRIPT_2022011"}]
    )
    patient = create_patient()
    consent = grant_consent(patient["id"], scope=scope, duration_days=duration_days)
    record = add_history_record(
        patient["id"], pharmacy["id"], drug_ndc="00093314905",
        fill_date="2026-06-01T00:00:00Z", days_supply=30, quantity=60,
    )
    batch = open_history_batch(patient["id"], pharmacy["id"])
    return pharmacy, patient, consent, record, batch


def test_a_benefit_check_only_consent_blocks_the_batch_from_leaving_pending(api):
    """PRD §3.8: "Advancing a batch out of `PENDING` requires that status and requires an
    `ACTIVE` consent with a `scope` of `MEDICATION_HISTORY` or `BOTH`, absent which the advance
    is refused with `ERR_CONSENT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/consent_scope_gates_medication_history_batch
    """
    pharmacy, patient, consent, record, batch = _pharmacy_and_patient_with_consent("BENEFIT_CHECK")

    assert consent["scope"] == "BENEFIT_CHECK"
    assert consent["status"] == "ACTIVE"

    response = api_client.aggregate_history_batch(batch["id"], HUB)
    validate_error(response, "ERR_CONSENT_REQUIRED", expected_status=422)

    stopped = reload_batch(batch["id"])
    assert stopped["status"] == "PENDING"
    assert stopped["source_record_count"] == 0
    # The blocked batch stamped nothing.
    assert reload_history_record(record["id"])["is_superseded"] is False


def test_a_both_scope_consent_that_is_revoked_also_blocks_the_advance(api):
    """PRD §3.8: "Revocation acts on every `ACTIVE` consent the patient holds: each becomes
    `REVOKED` with `revoked_at` stamped, the patient's `consent_status` becomes `REVOKED` and
    its `consent_version` increments"
    PRD §3.8: "Advancing a batch out of `PENDING` requires that status and requires an
    `ACTIVE` consent with a `scope` of `MEDICATION_HISTORY` or `BOTH`, absent which the advance
    is refused with `ERR_CONSENT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/consent_scope_gates_medication_history_batch
    """
    pharmacy, patient, consent, record, batch = _pharmacy_and_patient_with_consent("BOTH")
    assert consent["scope"] == "BOTH"

    revoke_consents(patient["id"])
    after_revoke = reload_patient(patient["id"])
    assert after_revoke["consent_status"] == "REVOKED"
    assert after_revoke["consent_version"] == 2

    response = api_client.aggregate_history_batch(batch["id"], HUB)
    validate_error(response, "ERR_CONSENT_REQUIRED", expected_status=422)

    assert reload_batch(batch["id"])["status"] == "PENDING"