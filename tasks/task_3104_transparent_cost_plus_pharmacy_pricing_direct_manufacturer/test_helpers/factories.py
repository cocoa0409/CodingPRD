"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS, CLOCK_START, FAR_FUTURE


def create_manufacturer_payload(**overrides) -> dict:
    defaults = {"manufacturer_name": "Bexley Generics"}
    defaults.update(overrides)
    return defaults


def create_drug_payload(**overrides) -> dict:
    defaults = {
        "drug_name": TEST_DEFAULTS["drug_name"],
        "strength": TEST_DEFAULTS["strength"],
        "dosage_form": TEST_DEFAULTS["dosage_form"],
        "is_controlled": False,
        "retail_reference_price_cents": TEST_DEFAULTS["retail_reference_price_cents"],
        "insured_reference_price_cents": TEST_DEFAULTS["insured_reference_price_cents"],
    }
    defaults.update(overrides)
    return defaults


def create_price_payload(drug_id: str, manufacturer_id: str, **overrides) -> dict:
    """A negotiated per-unit price row. Falls outside the sourcing pool until
    it is activated and moved to SOURCED."""
    defaults = {
        "drug_id": drug_id,
        "manufacturer_id": manufacturer_id,
        "unit_cost_cents": TEST_DEFAULTS["unit_cost_cents"],
        "available_units": TEST_DEFAULTS["available_units"],
        "reliability_tier": "A",
        "packaging": "500-count bottle",
    }
    defaults.update(overrides)
    return defaults


def create_pharmacy_payload(**overrides) -> dict:
    defaults = {
        "pharmacy_name": TEST_DEFAULTS["pharmacy_name"],
        "domicile_state_code": TEST_DEFAULTS["domicile_state_code"],
        "shipping_enabled": True,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "state_code": TEST_DEFAULTS["ship_state_code"],
        "license_number": TEST_DEFAULTS["license_number"],
        "expiry_at": FAR_FUTURE,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": TEST_DEFAULTS["patient_name"],
        "email": TEST_DEFAULTS["patient_email"],
        "home_state_code": TEST_DEFAULTS["ship_state_code"],
    }
    defaults.update(overrides)
    return defaults


def create_prescriber_payload(**overrides) -> dict:
    defaults = {
        "prescriber_name": TEST_DEFAULTS["prescriber_name"],
        "npi": TEST_DEFAULTS["prescriber_npi"],
        "license_state_code": TEST_DEFAULTS["ship_state_code"],
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(patient_id: str, prescriber_id: str, drug_id: str,
                                **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "prescriber_id": prescriber_id,
        "drug_id": drug_id,
        "ship_state_code": TEST_DEFAULTS["ship_state_code"],
        "total_refills_authorized": 1,
    }
    defaults.update(overrides)
    return defaults


def create_intake_request_payload(**overrides) -> dict:
    defaults = {"packaged_quantity": 100}
    defaults.update(overrides)
    return defaults


def create_order_payload(prescription_id: str, request_id: str, pharmacy_id: str,
                         source_price_id: str, **overrides) -> dict:
    defaults = {
        "prescription_id": prescription_id,
        "request_id": request_id,
        "pharmacy_id": pharmacy_id,
        "quantity": 30,
        "source_price_id": source_price_id,
    }
    defaults.update(overrides)
    return defaults


def create_substitution_payload(new_drug_id: str, **overrides) -> dict:
    defaults = {
        "new_drug_id": new_drug_id,
        "reason_code": "SHORTAGE_SUBSTITUTION",
    }
    defaults.update(overrides)
    return defaults


def create_substantiation_payload(order_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "source_kind": "RETAIL_SURVEY",
        "source_reference": "Q3-2026 retail survey ref 88",
        "observed_at": "2026-08-15T00:00:00Z",
        "valid_until": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_cancellation_payload(**overrides) -> dict:
    defaults = {"reason_code": "PATIENT_REQUEST"}
    defaults.update(overrides)
    return defaults


def create_rejection_payload(**overrides) -> dict:
    defaults = {"reason_code": "PRESCRIBER_ORDER_ILLEGIBLE"}
    defaults.update(overrides)
    return defaults


def set_clock_payload(current_utc: str = CLOCK_START) -> dict:
    return {"current_utc": current_utc}