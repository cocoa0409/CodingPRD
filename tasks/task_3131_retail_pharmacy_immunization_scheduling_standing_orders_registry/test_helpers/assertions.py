"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def assert_pharmacy_store(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["store_number"], str) and len(data["store_number"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["address_line"], str)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_state_protocol(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert is_valid_uuid(data.get("vaccine_product_id", "")), "vaccine_product_id must be UUID"
    assert data["authority_type"] in ["STANDING_ORDER", "PROTOCOL", "PRESCRIPTION_REQUIRED"]
    assert isinstance(data["min_patient_age_years"], int)
    assert data["registry_format"] in ["HL7_VXU", "FLAT_FILE_CSV", "STATE_API_JSON"]
    assert isinstance(data["registry_deadline_hours"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_vaccine_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["cvx_code"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["min_patient_age_years"], int)
    assert isinstance(data["doses_per_series"], int)
    assert isinstance(data["min_interval_days"], int)
    assert isinstance(data["cash_price_cents"], int)
    assert isinstance(data["fridge_temp_min_c"], (int, float))
    assert isinstance(data["fridge_temp_max_c"], (int, float))
    assert isinstance(data["observation_minutes"], int)


def assert_patient(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["allergy_flags"], list)
    assert isinstance(data["high_risk_flag"], bool)


def assert_insurance_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["plan_name"], str)
    assert data["benefit_type"] in ["PHARMACY", "MEDICAL", "BOTH"]
    assert isinstance(data["copay_cents"], int)
    assert isinstance(data["coinsurance_pct"], (int, float))
    assert isinstance(data["deductible_remaining_cents"], int)
    assert isinstance(data["covered_cvx_codes"], list)


def assert_vaccine_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be UUID"
    assert is_valid_uuid(data.get("vaccine_product_id", "")), "vaccine_product_id must be UUID"
    assert isinstance(data["lot_number"], str)
    assert isinstance(data["expiration_date"], str)
    assert isinstance(data["doses_received"], int)
    assert isinstance(data["doses_available"], int)
    assert data["doses_available"] >= 0, "doses_available never negative"
    assert data["status"] in ["RELEASED", "QUARANTINED", "RETIRED"]


def assert_temperature_reading(data: dict):
    # common_fields: false — only id + created_at, NO updated_at/version
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["recorded_at"], str)
    assert isinstance(data["temperature_c"], (int, float))
    assert isinstance(data["is_excursion"], bool)
    assert data["excursion_severity_tier"] in ["NONE", "MINOR", "MODERATE", "SEVERE"]
    assert "version" not in data, "TemperatureReading must not carry version"
    assert "updated_at" not in data, "TemperatureReading must not carry updated_at"


def assert_appointment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["store_id"], str)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["vaccine_product_id"], str)
    assert isinstance(data["slot_start"], str)
    assert isinstance(data["is_walk_in"], bool)
    assert data["status"] in [
        "SCHEDULED", "CHECKED_IN", "SCREENED", "CONSENTED",
        "VACCINATED", "CANCELLED", "NO_SHOW", "EXPIRED",
    ]


def assert_questionnaire(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["answers"], dict)
    assert isinstance(data["contraindication_detected"], bool)


def assert_immunization_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["administered_at"], str)
    assert isinstance(data["dose_number"], int)
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0
    assert data["billing_channel"] in ["PHARMACY_BENEFIT", "MEDICAL_BENEFIT", "CASH"]
    assert data["status"] in ["COMPLETED", "VOIDED"]


def assert_registry_submission(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["immunization_record_id"], str)
    assert data["payload_format"] in ["HL7_VXU", "FLAT_FILE_CSV", "STATE_API_JSON"]
    assert isinstance(data["due_at"], str)
    assert isinstance(data["is_late"], bool)
    assert data["status"] in ["PENDING", "SUBMITTED", "ACKNOWLEDGED", "REJECTED", "LATE_UNRESOLVED"]


def assert_observation_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["immunization_record_id"], str)
    assert isinstance(data["required_minutes"], int)
    assert data["status"] in ["IN_PROGRESS", "COMPLETED", "ESCALATED"]


def assert_clinic_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["store_id"], str)
    assert isinstance(data["employer_name"], str)
    assert isinstance(data["event_start"], str)
    assert isinstance(data["event_end"], str)
    assert isinstance(data["mobile_lot_id"], str)
    assert isinstance(data["doses_reserved"], int)
    assert isinstance(data["doses_administered"], int)
    assert data["status"] in ["PLANNED", "ACTIVE", "CLOSED", "CANCELLED"]
