"""Payload factories — one per creatable resource, input fields only.

Every factory accepts ``**overrides`` so a test controls exactly the fields it
cares about and inherits sane defaults for the rest.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_ACQUISITION_VALUE,
    DEFAULT_EXPIRATION_DATE,
    DEFAULT_LICENSE_EXPIRY,
    DEFAULT_TEMP_MAX_C,
    DEFAULT_TEMP_MIN_C,
    DEFAULT_WHOLESALE_VALUE,
)


def create_donor_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Meridian Pharma",
        "country_code": "US",
        "tax_id": "12-3456789",
    }
    payload.update(overrides)
    return payload


def create_lot_payload(donor_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "donor_id": donor_id,
        "ndc_code": "00001-0001-01",
        "product_name": "Amoxicillin 500mg",
        "product_class": "STANDARD",
        "dosage_form": "TABLET",
        "unit_of_measure": "UNIT",
        "quantity_received": 100,
        "expiration_date": DEFAULT_EXPIRATION_DATE,
        "storage_temp_min_c": DEFAULT_TEMP_MIN_C,
        "storage_temp_max_c": DEFAULT_TEMP_MAX_C,
        "restricted_use_conditions": [],
        "unit_acquisition_value_usd": DEFAULT_ACQUISITION_VALUE,
        "unit_wholesale_value_usd": DEFAULT_WHOLESALE_VALUE,
    }
    payload.update(overrides)
    return payload


def create_site_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_name": "Community Free Clinic",
        "site_type": "FREE_CLINIC",
        "country_code": "US",
        "cold_storage_capacity_l": 100,
        "has_dea_registration": False,
        "monthly_patient_volume": 100,
        "underserved_index": 0.5,
    }
    payload.update(overrides)
    return payload


def create_license_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "license_type": "PHARMACY",
        "issuing_authority": "TX BoP",
        "license_number": "LIC-0001",
        "expires_on": DEFAULT_LICENSE_EXPIRY,
    }
    payload.update(overrides)
    return payload


def create_allocation_request_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "ndc_code": "00001-0001-01",
        "quantity_requested": 10,
        "justification_text": "Program need",
    }
    payload.update(overrides)
    return payload


def create_allocation_decision_payload(
    request_id: str, lines: List[Dict[str, Any]], **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "request_id": request_id,
        "rationale": "Meets need criteria",
        "lines": lines,
    }
    payload.update(overrides)
    return payload


def create_shipment_payload(allocation_decision_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "allocation_decision_id": allocation_decision_id,
        "carrier_name": "Relief Freight",
        "packed_with_cold_shipper": False,
    }
    payload.update(overrides)
    return payload


def create_customs_declaration_payload(
    shipment_id: str, import_license_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shipment_id": shipment_id,
        "hs_code": "3004.90",
        "import_license_id": import_license_id,
    }
    payload.update(overrides)
    return payload


def create_emergency_event_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_name": "Hurricane Delta",
        "severity": 3,
        "affected_country_codes": ["US"],
        "surge_window_ends_at": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_module_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "module_code": "MODULE-IEHK-2026-A",
        "intended_use": "PRIMARY_CARE",
        "holding_country_code": "US",
    }
    payload.update(overrides)
    return payload


def create_valuation_snapshot_payload(donor_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "donor_id": donor_id,
        "snapshot_period": "2026-09",
        "method": "ACQUISITION_COST",
    }
    payload.update(overrides)
    return payload


def create_distribution_report_payload(site_id: str, shipment_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_id": site_id,
        "shipment_id": shipment_id,
        "reporting_period": "2026-09",
        "units_distributed": 5,
        "patients_reached": 5,
        "wastage_units": 0,
    }
    payload.update(overrides)
    return payload
