"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

IL_JURISDICTION = {
    "state_code": "IL",
    "min_age_self_consent": 18,
    "min_age_with_guardian": 6,
    "min_age_absolute": 6,
    "permitted_sites": ["LOBE", "UPPER_LOBE", "HELIX", "TRAGUS"],
    "requires_guardian_presence": False,
    "record_retention_years": 7,
    "consent_form_version": "IL-2026",
    "sterilization_protocol_code": "AUTOCLAVE-B",
}


def create_jurisdiction_payload(**overrides) -> dict:
    payload = dict(IL_JURISDICTION)
    payload.update(overrides)
    return payload


def create_store_payload(jurisdiction_id: str, **overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["STORE_NAME"],
        "jurisdiction_id": jurisdiction_id,
        "piercing_room_count": 2,
    }
    payload.update(overrides)
    return payload


def create_piercer_payload(home_store_id: str, **overrides) -> dict:
    payload = {"full_name": TEST_DEFAULTS["PIERCER_NAME"], "home_store_id": home_store_id}
    payload.update(overrides)
    return payload


def create_certification_payload(piercer_id: str, expected_piercer_version: int, **overrides) -> dict:
    payload = {
        "piercer_id": piercer_id,
        "certification_level": "STANDARD",
        "sterilization_protocol_code": "AUTOCLAVE-B",
        "issued_at": "2026-08-01T00:00:00Z",
        "expires_at": "2027-08-01T00:00:00Z",
        "expected_piercer_version": expected_piercer_version,
    }
    payload.update(overrides)
    return payload


def create_sterilization_cycle_payload(store_location_id: str, **overrides) -> dict:
    payload = {
        "store_location_id": store_location_id,
        "autoclave_unit_id": "AUTO-1",
        "protocol_code": "AUTOCLAVE-B",
        "cycle_start_at": "2026-08-30T08:00:00Z",
        "cycle_end_at": "2026-08-30T08:45:00Z",
        "temperature_celsius": 134.0,
    }
    payload.update(overrides)
    return payload


def create_cartridge_lot_payload(
    store_location_id: str, sterilization_cycle_id: str, expected_store_version: int, **overrides
) -> dict:
    payload = {
        "store_location_id": store_location_id,
        "sterilization_cycle_id": sterilization_cycle_id,
        "lot_number": "L-1",
        "site_type": "LOBE",
        "units_received": 50,
        "expiration_date": "2027-01-01T00:00:00Z",
        "expected_store_version": expected_store_version,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["CUSTOMER_NAME"],
        "date_of_birth": TEST_DEFAULTS["CUSTOMER_DOB"],
    }
    payload.update(overrides)
    return payload


def create_minor_customer_payload(**overrides) -> dict:
    payload = create_customer_payload(
        full_name="Young Client",
        date_of_birth="2015-01-01T00:00:00Z",
        guardian_name="Parent Client",
        guardian_contact="p@x.com",
    )
    payload.update(overrides)
    return payload


def create_consent_payload(customer_id: str, jurisdiction_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "jurisdiction_id": jurisdiction_id,
        "consent_type": "SELF",
        "identification_type": "GOVERNMENT_PHOTO_ID",
        "identification_number_masked": "****1234",
        "signed_at": "2026-08-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(
    store_location_id: str, customer_id: str, piercer_id: str, jurisdiction_id: str, **overrides
) -> dict:
    payload = {
        "store_location_id": store_location_id,
        "customer_id": customer_id,
        "piercer_id": piercer_id,
        "jurisdiction_id": jurisdiction_id,
        "intake_type": "SCHEDULED",
        "site_requested": "LOBE",
        "slot_start_at": "2026-09-01T09:00:00Z",
        "slot_end_at": "2026-09-01T09:30:00Z",
    }
    payload.update(overrides)
    return payload


def create_screening_payload(appointment_id: str, piercer_id: str, expected_appointment_version: int, **overrides) -> dict:
    payload = {
        "appointment_id": appointment_id,
        "piercer_id": piercer_id,
        "anatomy_sites_examined": ["LOBE"],
        "contraindication_codes": [],
        "expected_appointment_version": expected_appointment_version,
    }
    payload.update(overrides)
    return payload


def create_session_payload(
    appointment_id: str, piercer_id: str, cartridge_lot_id: str, **overrides
) -> dict:
    payload = {
        "appointment_id": appointment_id,
        "piercer_id": piercer_id,
        "cartridge_lot_id": cartridge_lot_id,
        "site_pierced": "LOBE",
        "base_fee_cents": TEST_DEFAULTS["BASE_FEE_CENTS"],
        "aftercare_kit_included": True,
        "solution_lot_number": "S-1",
    }
    payload.update(overrides)
    return payload


def create_healing_assessment_payload(**overrides) -> dict:
    payload = {"assessed_at": "2026-09-15T00:00:00Z", "failure_codes": []}
    payload.update(overrides)
    return payload


def create_incident_payload(session_id: str, expected_session_version: int, **overrides) -> dict:
    payload = {
        "session_id": session_id,
        "reported_at": "2026-09-10T00:00:00Z",
        "severity": "MINOR",
        "reaction_codes": ["REDNESS"],
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def create_healing_outcome_payload(session_id: str, expected_session_version: int, **overrides) -> dict:
    payload = {
        "session_id": session_id,
        "assessed_at": "2026-09-20T00:00:00Z",
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return payload


def create_fee_quote_payload(base_fee_cents: int, **overrides) -> dict:
    payload = {
        "base_fee_cents": base_fee_cents,
        "aftercare_kit_included": True,
        "site_pierced": "HELIX",
        "is_re_pierce": False,
        "downgraded_sites": [],
    }
    payload.update(overrides)
    return payload