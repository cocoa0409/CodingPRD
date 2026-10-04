"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "STORE_NUMBER": "S-DEFAULT",
    "STATE_CODE": "CA",
    "ADDRESS_LINE": "1 Main St",
    "CVX_CODE": "141",
    "PRODUCT_NAME": "Influenza Quadrivalent",
    "CASH_PRICE_CENTS": 5000,
    "FRIDGE_MIN_C": 2.0,
    "FRIDGE_MAX_C": 8.0,
    "OBSERVATION_MINUTES": 15,
    "MIN_INTERVAL_DAYS": 0,
    "DOSES_PER_SERIES": 1,
    "MIN_PATIENT_AGE": 0,
    "REGISTRY_FORMAT": "HL7_VXU",
    "REGISTRY_DEADLINE_HOURS": 24,
    "AUTHORITY_TYPE": "STANDING_ORDER",
    "LOT_EXPIRATION": "2027-01-01",
    "DOSES_RECEIVED": 10,
}


def create_store_payload(**overrides) -> dict:
    defaults = {
        "store_number": DEFAULTS["STORE_NUMBER"],
        "state_code": DEFAULTS["STATE_CODE"],
        "address_line": DEFAULTS["ADDRESS_LINE"],
    }
    defaults.update(overrides)
    return defaults


def create_state_protocol_payload(**overrides) -> dict:
    defaults = {
        "state_code": DEFAULTS["STATE_CODE"],
        "authority_type": DEFAULTS["AUTHORITY_TYPE"],
        "min_patient_age_years": DEFAULTS["MIN_PATIENT_AGE"],
        "registry_format": DEFAULTS["REGISTRY_FORMAT"],
        "registry_deadline_hours": DEFAULTS["REGISTRY_DEADLINE_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_vaccine_product_payload(**overrides) -> dict:
    defaults = {
        "cvx_code": DEFAULTS["CVX_CODE"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "min_patient_age_years": DEFAULTS["MIN_PATIENT_AGE"],
        "doses_per_series": DEFAULTS["DOSES_PER_SERIES"],
        "cash_price_cents": DEFAULTS["CASH_PRICE_CENTS"],
        "fridge_temp_min_c": DEFAULTS["FRIDGE_MIN_C"],
        "fridge_temp_max_c": DEFAULTS["FRIDGE_MAX_C"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": "Test Plan",
        "benefit_type": "PHARMACY",
        "copay_cents": 1000,
        "covered_cvx_codes": ["141"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Patient",
        "date_of_birth": "1980-01-01",
        "state_code": DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_number": "L1",
        "expiration_date": DEFAULTS["LOT_EXPIRATION"],
        "doses_received": DEFAULTS["DOSES_RECEIVED"],
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "slot_start": "2026-09-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_temperature_reading_payload(**overrides) -> dict:
    defaults = {
        "recorded_at": "2026-09-01T08:00:00Z",
        "temperature_c": 5.0,
    }
    defaults.update(overrides)
    return defaults


def create_questionnaire_payload(**overrides) -> dict:
    defaults = {
        "answers": {
            "FEVER_TODAY": False,
            "PREGNANT": False,
            "IMMUNOCOMPROMISED": False,
            "PRIOR_ANAPHYLAXIS": False,
        }
    }
    defaults.update(overrides)
    return defaults


def create_clinic_event_payload(**overrides) -> dict:
    defaults = {
        "employer_name": "Acme Corp",
        "event_start": "2026-09-01T10:00:00Z",
        "event_end": "2026-09-01T12:00:00Z",
        "doses_reserved": 4,
    }
    defaults.update(overrides)
    return defaults
