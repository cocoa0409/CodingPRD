"""Payload factories — one per resource, carrying only client-supplied input fields."""

DEFAULTS = {
    "PARTICIPANT_NAME": "Test Participant",
    "NPI": "9999999999",
    "DRUG_NDC": "00093314905",
    "FILL_DATE": "2026-06-01T00:00:00Z",
    "DAYS_SUPPLY": 30,
    "QUANTITY": 60,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "EFFECTIVE_TO": "2027-01-01T00:00:00Z",
}


def create_participant_payload(**overrides) -> dict:
    """Registration payload. Only name, participant_type and npi are required; every other
    declared input is optional and carries a server-side default (PRD §3.1)."""
    payload = {
        "name": DEFAULTS["PARTICIPANT_NAME"],
        "participant_type": "PRESCRIBER_CLINIC",
        "npi": DEFAULTS["NPI"],
    }
    payload.update(overrides)
    return payload


def create_clinic_payload(**overrides) -> dict:
    payload = {
        "name": "Northside Family Clinic",
        "participant_type": "PRESCRIBER_CLINIC",
        "npi": "1111111111",
        "volume_billing_mode": "MONTHLY",
        "fallback_channel": "FAX",
        "fax_number": "+1-555-0100",
    }
    payload.update(overrides)
    return payload


def create_second_clinic_payload(**overrides) -> dict:
    """A second prescriber clinic, distinct in name and npi so it coexists with the first.

    A `Prescriber` identity is entity-backed (§2.1), so a fixture needing an acting
    prescriber *in addition to* the clinic a scenario already registered uses this
    participant rather than reusing the first clinic's npi.
    """
    payload = {
        "name": "Eastgate Family Practice",
        "participant_type": "PRESCRIBER_CLINIC",
        "npi": "6666666666",
        "volume_billing_mode": "MONTHLY",
        "fallback_channel": "FAX",
        "fax_number": "+1-555-0300",
    }
    payload.update(overrides)
    return payload


def create_pharmacy_payload(**overrides) -> dict:
    payload = {
        "name": "Riverbend Pharmacy",
        "participant_type": "PHARMACY",
        "npi": "2222222222",
        "volume_billing_mode": "MONTHLY",
        "fallback_channel": "FAX",
        "fax_number": "+1-555-0200",
    }
    payload.update(overrides)
    return payload


def create_payer_payload(**overrides) -> dict:
    payload = {
        "name": "Meridian Health Plan",
        "participant_type": "PAYER",
        "npi": "3333333333",
        "plan_copay_cents": 1500,
        "plan_coinsurance_pct": 0.2,
        "plan_deductible_cents": 10000,
        "plan_deductible_met_cents": 4000,
        "plan_brand_fee_cents": 300,
        "formulary_preferred_pct": 0.3,
        "plan_benefit_cap_cents": 50000,
    }
    payload.update(overrides)
    return payload


def create_endpoint_payload(**overrides) -> dict:
    """Directory endpoint registration payload (PRD §3.1)."""
    payload = {
        "service_set": "NEW_RX",
        "endpoint_role": "BOTH",
        "service_level": "ELIGIBLE_A",
        "sla_response_minutes": 15,
        "message_standard": "NCPDP_SCRIPT_2022011",
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Patient",
        "date_of_birth": "1980-01-01T00:00:00Z",
        "home_state": "MA",
    }
    payload.update(overrides)
    return payload


def create_consent_payload(**overrides) -> dict:
    payload = {
        "scope": "MEDICATION_HISTORY",
        "duration_days": 365,
    }
    payload.update(overrides)
    return payload


def create_prescription_payload(prescriber_id: str, receiving_pharmacy_id: str,
                                patient_id: str, **overrides) -> dict:
    payload = {
        "prescriber_id": prescriber_id,
        "receiving_pharmacy_id": receiving_pharmacy_id,
        "patient_id": patient_id,
        "drug_ndc": DEFAULTS["DRUG_NDC"],
        "transaction_type": "NEW_RX",
        "controlled_schedule": "NON_CONTROLLED",
        "message_standard": "NCPDP_SCRIPT_2022011",
        "days_supply": DEFAULTS["DAYS_SUPPLY"],
        "quantity": DEFAULTS["QUANTITY"],
        "refills_authorized": 3,
    }
    payload.update(overrides)
    return payload


def create_history_record_payload(source_participant_id: str, **overrides) -> dict:
    payload = {
        "source_type": "PHARMACY_FILL",
        "source_participant_id": source_participant_id,
        "drug_ndc": DEFAULTS["DRUG_NDC"],
        "fill_date": DEFAULTS["FILL_DATE"],
        "days_supply": DEFAULTS["DAYS_SUPPLY"],
        "quantity": DEFAULTS["QUANTITY"],
    }
    payload.update(overrides)
    return payload


def create_history_batch_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "trigger_reason": "PRESCRIBER_QUERY",
    }
    payload.update(overrides)
    return payload


def create_benefit_check_payload(prescription_id: str, payer_id: str, **overrides) -> dict:
    payload = {
        "prescription_id": prescription_id,
        "payer_id": payer_id,
        "benchmark_price_cents": 8000,
    }
    payload.update(overrides)
    return payload


def create_transaction_fee_payload(participant_id: str, **overrides) -> dict:
    payload = {
        "participant_id": participant_id,
        "month_key": "2026-09",
        "transaction_type": "NEW_RX",
        "direction": "SENT",
    }
    payload.update(overrides)
    return payload


def create_certification_test_payload(test_code: str, outcome: str = "PASS") -> dict:
    return {"test_code": test_code, "outcome": outcome}