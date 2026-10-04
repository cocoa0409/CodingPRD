"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_station_payload(**overrides) -> dict:
    """Input fields: name, zone_code, surge_enabled (optional)."""
    payload = {
        "name": TEST_DEFAULTS["STATION_NAME"],
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
    }
    payload.update(overrides)
    return payload


def register_driver_payload(**overrides) -> dict:
    """Input fields: legal_name, email."""
    payload = {
        "legal_name": TEST_DEFAULTS["DRIVER_NAME"],
        "email": TEST_DEFAULTS["DRIVER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def decide_screening_payload(**overrides) -> dict:
    """Input fields: decision, failure_reason (required when FAILED)."""
    payload = {"decision": "CLEARED"}
    payload.update(overrides)
    return payload


def create_vehicle_payload(**overrides) -> dict:
    """Input fields: vin, vehicle_class."""
    payload = {
        "vin": TEST_DEFAULTS["VIN"],
        "vehicle_class": TEST_DEFAULTS["VEHICLE_CLASS"],
    }
    payload.update(overrides)
    return payload


def attest_insurance_payload(**overrides) -> dict:
    """Input fields: insurance_expires_on."""
    payload = {"insurance_expires_on": TEST_DEFAULTS["INSURANCE_LONG"]}
    payload.update(overrides)
    return payload


def create_block_payload(**overrides) -> dict:
    """Input fields: starts_at, ends_at, required_vehicle_class, base_pay_cents."""
    payload = {
        "starts_at": "2026-09-01T10:00:00Z",
        "ends_at": "2026-09-01T12:00:00Z",
        "required_vehicle_class": TEST_DEFAULTS["VEHICLE_CLASS"],
        "base_pay_cents": TEST_DEFAULTS["BASE_PAY_CENTS"],
    }
    payload.update(overrides)
    return payload


def revise_block_payload(expected_block_version, **overrides) -> dict:
    """Input fields: expected_block_version plus any of starts_at, ends_at,
    required_vehicle_class, base_pay_cents."""
    payload = {"expected_block_version": expected_block_version}
    payload.update(overrides)
    return payload


def accept_block_payload(vehicle_id, **overrides) -> dict:
    """Input fields: vehicle_id."""
    payload = {"vehicle_id": vehicle_id}
    payload.update(overrides)
    return payload


def create_offer_payload(driver_id, **overrides) -> dict:
    """Input fields: driver_id, tier_floor, expires_at."""
    payload = {
        "driver_id": driver_id,
        "tier_floor": "STANDARD",
        "expires_at": TEST_DEFAULTS["OFFER_EXPIRES"],
    }
    payload.update(overrides)
    return payload


def load_packages_payload(packages, **overrides) -> dict:
    """Input fields: packages (array of {tracking_code, billable_weight_kg,
    promised_by})."""
    payload = {"packages": packages}
    payload.update(overrides)
    return payload


def package_entry_payload(**overrides) -> dict:
    """One entry of the load-packages array."""
    entry = {
        "tracking_code": "PW-1",
        "billable_weight_kg": 1.0,
        "promised_by": "2026-09-01T03:00:00Z",
    }
    entry.update(overrides)
    return entry


def deliver_package_payload(**overrides) -> dict:
    """Input fields: photo_url, photo_gps_tagged."""
    payload = {
        "photo_url": TEST_DEFAULTS["PHOTO_URL"],
        "photo_gps_tagged": True,
    }
    payload.update(overrides)
    return payload


def report_failed_payload(**overrides) -> dict:
    """Input fields: reason."""
    payload = {"reason": "recipient refused"}
    payload.update(overrides)
    return payload


def deactivate_driver_payload(**overrides) -> dict:
    """Input fields: reason."""
    payload = {"reason": "policy violation"}
    payload.update(overrides)
    return payload


def create_appeal_payload(**overrides) -> dict:
    """Input fields: reason."""
    payload = {"reason": "incorrect deactivation"}
    payload.update(overrides)
    return payload


def submit_evidence_payload(**overrides) -> dict:
    """Input fields: evidence_note."""
    payload = {"evidence_note": "dashcam footage link"}
    payload.update(overrides)
    return payload


def request_evidence_payload(**overrides) -> dict:
    """Input fields: request_note (optional)."""
    payload = {"request_note": "need GPS logs"}
    payload.update(overrides)
    return payload


def decide_appeal_payload(**overrides) -> dict:
    """Input fields: decision, decision_reason (optional)."""
    payload = {"decision": "UPHELD", "decision_reason": "evidence insufficient"}
    payload.update(overrides)
    return payload
