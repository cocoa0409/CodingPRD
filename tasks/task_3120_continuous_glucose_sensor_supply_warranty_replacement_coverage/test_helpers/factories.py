"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_patient_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Test Patient {n}",
        "date_of_birth": TEST_DEFAULTS["DOB"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_prescriber_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Dr. Test Prescriber {n}",
        "npi": f"{1234567000 + n:010d}",
        "specialty": "ENDOCRINOLOGY",
    }
    defaults.update(overrides)
    return defaults


def create_payer_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "name": f"Test Payer {n}",
        "plan_code": f"PLAN-{n:05d}",
        "benefit_route": "PHARMACY",
        "cgm_coverage_policy": "STANDARD",
        "pharmacy_copay_pct": 0.20,
        "dme_coinsurance_pct": 0.0,
        "deductible_cap_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_sensor_product_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "sku": f"SKU-{n:05d}",
        "generation": TEST_DEFAULTS["GENERATION"],
        "wear_days": TEST_DEFAULTS["WEAR_DAYS"],
        "reader_channel": "HYBRID",
        "compatible_prior_generations": [],
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_sensor_lot_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "lot_code": f"LOT-{n:05d}",
        "quantity_manufactured": 10,
        "manufacture_date": TEST_DEFAULTS["MANUFACTURE_DATE"],
        "expiry_date": TEST_DEFAULTS["EXPIRY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_sensor_unit_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "serial_number": f"SN-{n:06d}",
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(prescriber_id, product_id, expected_patient_version, **overrides) -> dict:
    defaults = {
        "prescriber_id": prescriber_id,
        "product_id": product_id,
        "diagnosis_code": "E11.9",
        "insulin_use": "INTENSIVE",
        "documentation_attached": True,
        "quantity_per_fill": 1,
        "fills_authorized": 12,
        "written_on": TEST_DEFAULTS["WRITTEN_ON"],
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_verification_payload(payer_id, **overrides) -> dict:
    defaults = {"payer_id": payer_id}
    defaults.update(overrides)
    return defaults


def create_sensor_order_payload(prescription_id, coverage_verification_id, lot_id, quantity, **overrides) -> dict:
    defaults = {
        "prescription_id": prescription_id,
        "coverage_verification_id": coverage_verification_id,
        "lot_id": lot_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_device_binding_payload(sensor_unit_id, channel="READER", **overrides) -> dict:
    defaults = {"sensor_unit_id": sensor_unit_id, "channel": channel}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "reported_failure_day_index": 3,
        "failure_category": "SENSOR_ERROR",
        "device_data_attached": True,
    }
    defaults.update(overrides)
    return defaults


def create_support_enrollment_payload(payer_id, **overrides) -> dict:
    defaults = {"payer_id": payer_id, "card_max_per_fill_cents": 5000}
    defaults.update(overrides)
    return defaults


def create_adverse_event_report_payload(sensor_unit_id, patient_id, **overrides) -> dict:
    defaults = {
        "sensor_unit_id": sensor_unit_id,
        "patient_id": patient_id,
        "severity": "HIGH",
        "event_type": "SKIN_IRRITATION",
    }
    defaults.update(overrides)
    return defaults
