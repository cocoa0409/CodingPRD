"""Payload factories — one per entity, request-input fields only."""
from .constants import (
    PLMD_JURISDICTION, SNVL_JURISDICTION, P1_PROPERTY, P2_PROPERTY,
    PROJECT_A, PROJECT_B, ALL_CERTIFICATIONS,
)


def jurisdiction_payload(**overrides) -> dict:
    """Palmdale ordinance by default: 1000 sqft ceiling, 7-day minimum lease."""
    payload = dict(PLMD_JURISDICTION)
    payload.update(overrides)
    return payload


def snvl_jurisdiction_payload(**overrides) -> dict:
    """Sunnyvale ordinance: restrictive 750 sqft ceiling, separate meter required."""
    payload = dict(SNVL_JURISDICTION)
    payload.update(overrides)
    return payload


def inspector_payload(jurisdiction_id: str, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "full_name": "R. Okafor",
        "certifications": list(ALL_CERTIFICATIONS),
        "daily_capacity": 4,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def property_payload(jurisdiction_id: str, **overrides) -> dict:
    """Parcel P2 by default: unoccupied, 400 A service, 1.0 in meter."""
    payload = {"jurisdiction_id": jurisdiction_id}
    payload.update(P2_PROPERTY)
    payload.update(overrides)
    return payload


def occupied_property_payload(jurisdiction_id: str, **overrides) -> dict:
    """Parcel P1: occupied primary dwelling, 200 A service, 0.75 in meter."""
    payload = {"jurisdiction_id": jurisdiction_id}
    payload.update(P1_PROPERTY)
    payload.update(overrides)
    return payload


def adu_project_payload(property_id: str, expected_property_version: int, **overrides) -> dict:
    """Project B by default: 767 sqft DETACHED_NEW at 24,000,000 cents."""
    payload = {
        "property_id": property_id,
        "expected_property_version": expected_property_version,
    }
    payload.update(PROJECT_B)
    payload.update(overrides)
    return payload


def large_adu_project_payload(property_id: str, expected_property_version: int, **overrides) -> dict:
    """Project A: 800 sqft DETACHED_NEW at 28,000,000 cents."""
    payload = {
        "property_id": property_id,
        "expected_property_version": expected_property_version,
    }
    payload.update(PROJECT_A)
    payload.update(overrides)
    return payload


def feasibility_screening_payload(pathway: str = "LOCAL_ORDINANCE") -> dict:
    return {"pathway": pathway}


def utility_connection_payload(service_type: str = "ELECTRIC") -> dict:
    return {"service_type": service_type}


def permit_submittal_payload(**overrides) -> dict:
    payload = {"design_sheet_count": 14, "title24_compliant": True}
    payload.update(overrides)
    return payload


def correction_item_payload(**overrides) -> dict:
    payload = {
        "discipline": "STRUCTURAL",
        "severity": "BLOCKING",
        "description": "Shear wall schedule missing on sheet S2",
    }
    payload.update(overrides)
    return payload


def financing_scenario_payload(expected_adu_project_version: int, **overrides) -> dict:
    payload = {
        "expected_adu_project_version": expected_adu_project_version,
        "product_type": "HELOC",
        "appraisal_approach": "SALES_COMPARISON",
        "comparable_adjustment_cents": 9_000_000,
        "projected_monthly_rent_cents": 250_000,
    }
    payload.update(overrides)
    return payload


def change_order_payload(expected_adu_project_version: int, **overrides) -> dict:
    payload = {
        "expected_adu_project_version": expected_adu_project_version,
        "title": "Upgrade to mini-split HVAC",
        "scope_items": ["Remove wall heater", "Install ductless mini-split"],
        "cost_delta_cents": 1_000_000,
        "schedule_delta_days": 4,
    }
    payload.update(overrides)
    return payload


def construction_phase_payload(**overrides) -> dict:
    payload = {
        "phase_code": "FOUNDATION",
        "disruption_class": "INVASIVE",
        "sequence_index": 0,
    }
    payload.update(overrides)
    return payload


def inspection_appointment_payload(inspector_id: str, **overrides) -> dict:
    payload = {
        "inspector_id": inspector_id,
        "inspection_type": "FOUNDATION",
        "slot_date": "2026-09-03",
        "slot_start": "2026-09-03T09:00:00Z",
        "slot_end": "2026-09-03T10:00:00Z",
    }
    payload.update(overrides)
    return payload
