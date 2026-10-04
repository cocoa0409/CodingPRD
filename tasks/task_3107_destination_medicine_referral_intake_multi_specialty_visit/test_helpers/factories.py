"""Payload factories — one per entity, input fields only."""
import itertools

_code_seq = itertools.count(1)


def create_specialty_service_payload(**overrides) -> dict:
    defaults = {
        "code": f"SVC{next(_code_seq):04d}",
        "name": "Test Specialty",
        "destination_daily_capacity": 2,
        "service_window_start_min": 480,
        "service_window_end_min": 1020,
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_date": "2026-09-10",
        "start_min": 540,
        "end_min": 600,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dana Domestic",
        "date_of_birth": "1970-05-01",
        "residence_country": "US",
        "residence_state": "WI",
        "preferred_language": "en",
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "patient": create_patient_payload(),
        "referring_physician_name": "Dr. Riley",
        "referring_physician_contact": "riley@example.org",
        "reason": "syncope workup",
    }
    defaults.update(overrides)
    return defaults


def create_medical_record_payload(**overrides) -> dict:
    defaults = {
        "record_type": "CLINICAL_NOTES",
        "source_facility": "La Crosse General",
    }
    defaults.update(overrides)
    return defaults


def create_visit_case_payload(**overrides) -> dict:
    defaults = {
        "case_type": "DESTINATION",
    }
    defaults.update(overrides)
    return defaults


def create_case_review_payload(**overrides) -> dict:
    defaults = {
        "outcome": "APPROVE",
        "notes": "appropriate for destination eval",
    }
    defaults.update(overrides)
    return defaults


def create_slot_hold_payload(**overrides) -> dict:
    defaults = {
        "visit_type": "CONSULT",
        "listed_price_cents": 200000,
        "sequencing_priority": 1,
    }
    defaults.update(overrides)
    return defaults


def create_billing_transaction_payload(**overrides) -> dict:
    defaults = {
        "txn_type": "DEPOSIT",
        "amount_cents": 60000,
    }
    defaults.update(overrides)
    return defaults


def create_logistics_payload(**overrides) -> dict:
    defaults = {
        "arrangement_type": "TRAVEL",
        "details": "MSP flight",
        "companion_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_communication_payload(**overrides) -> dict:
    defaults = {
        "comm_type": "RESULTS_TO_REFERRER",
        "body": "findings attached",
    }
    defaults.update(overrides)
    return defaults
