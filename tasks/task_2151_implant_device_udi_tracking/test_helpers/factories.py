"""Payload factories — one per resource, input fields only."""

from .constants import TEST_DEFAULTS


def create_vendor_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["VENDOR_NAME"],
        "vendor_code": TEST_DEFAULTS["VENDOR_CODE"],
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(vendor_id: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "agreement_code": TEST_DEFAULTS["AGREEMENT_CODE"],
        "billing_trigger": "ON_IMPLANT",
        "reconciliation_method": "UNIT_MATCH",
        "period_start_utc": TEST_DEFAULTS["PERIOD_START_UTC"],
        "period_end_utc": TEST_DEFAULTS["PERIOD_END_UTC"],
        "invoice_tolerance_bps": 150,
    }
    payload.update(overrides)
    return payload


def create_catalog_item_payload(vendor_id: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "device_identifier": TEST_DEFAULTS["DEVICE_IDENTIFIER"],
        "description": TEST_DEFAULTS["DESCRIPTION"],
        "category": "STANDARD_IMPLANT",
        "list_charge_cents": TEST_DEFAULTS["LIST_CHARGE_CENTS"],
        "charge_code": TEST_DEFAULTS["CHARGE_CODE"],
        "shelf_life_days": TEST_DEFAULTS["SHELF_LIFE_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_lot_payload(catalog_item_id: str, **overrides) -> dict:
    payload = {
        "catalog_item_id": catalog_item_id,
        "lot_number": TEST_DEFAULTS["LOT_NUMBER"],
        "expiration_date": TEST_DEFAULTS["EXPIRATION_DATE"],
    }
    payload.update(overrides)
    return payload


def create_device_unit_payload(expected_lot_version: int, **overrides) -> dict:
    payload = {
        "udi_serial": TEST_DEFAULTS["UDI_SERIAL"],
        "acquisition_cost_cents": TEST_DEFAULTS["ACQUISITION_COST_CENTS"],
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = {
        "mrn": TEST_DEFAULTS["MRN"],
        "display_name": TEST_DEFAULTS["PATIENT_NAME"],
        "registry_consent": "GRANTED",
    }
    payload.update(overrides)
    return payload


def create_surgical_case_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "case_number": TEST_DEFAULTS["CASE_NUMBER"],
        "or_room_code": TEST_DEFAULTS["OR_ROOM_CODE"],
        "scheduled_start_utc": TEST_DEFAULTS["SCHEDULED_START_UTC"],
        "scheduled_end_utc": TEST_DEFAULTS["SCHEDULED_END_UTC"],
        "surgeon_code": TEST_DEFAULTS["SURGEON_CODE"],
    }
    payload.update(overrides)
    return payload


def create_implant_record_payload(
    device_unit_id: str,
    udi_di: str,
    udi_pi_serial: str,
    expected_case_version: int,
    **overrides,
) -> dict:
    payload = {
        "device_unit_id": device_unit_id,
        "udi_di": udi_di,
        "udi_pi_serial": udi_pi_serial,
        "anatomic_site": TEST_DEFAULTS["ANATOMIC_SITE"],
        "laterality": "LEFT",
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def create_charge_payload(**overrides) -> dict:
    payload = {"quantity": 1}
    payload.update(overrides)
    return payload


def create_field_action_payload(vendor_id: str, catalog_item_id: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "catalog_item_id": catalog_item_id,
        "action_code": "FA-2026-001",
        "action_class": "CLASS_II",
        "scope_type": "CATALOG",
        "effective_from_utc": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_vendor_invoice_payload(
    vendor_id: str,
    consignment_agreement_id: str,
    device_unit_ids: list,
    submitted_total_cents: int,
    expected_agreement_version: int,
    **overrides,
) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "consignment_agreement_id": consignment_agreement_id,
        "invoice_number": "INV-1",
        "submitted_total_cents": submitted_total_cents,
        "device_unit_ids": device_unit_ids,
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def create_explant_payload(**overrides) -> dict:
    payload = {"reason": "DEVICE_FAILURE"}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
