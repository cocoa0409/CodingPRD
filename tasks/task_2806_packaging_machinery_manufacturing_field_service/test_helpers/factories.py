"""Payload factories — one per entity, input fields only.

Money is always an integer number of cents and percentages are plain numbers
carried to two decimals (PRD §2.6); nothing here sends money as a string.
"""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def create_customer_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": TEST_DEFAULTS["CUSTOMER_LEGAL_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "product_variation_pct": TEST_DEFAULTS["PRODUCT_VARIATION_PCT"],
    }
    payload.update(overrides)
    return payload


def create_machine_model_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "model_code": TEST_DEFAULTS["MODEL_CODE"],
        "machine_family": TEST_DEFAULTS["MACHINE_FAMILY"],
        "nameplate_rate_cpm": TEST_DEFAULTS["NAMEPLATE_RATE_CPM"],
        "guarantee_efficiency_pct": TEST_DEFAULTS["GUARANTEE_EFFICIENCY_PCT"],
        "base_price_cents": TEST_DEFAULTS["BASE_PRICE_CENTS"],
        "min_container_diameter_mm": TEST_DEFAULTS["MIN_CONTAINER_DIAMETER_MM"],
        "max_container_diameter_mm": TEST_DEFAULTS["MAX_CONTAINER_DIAMETER_MM"],
    }
    payload.update(overrides)
    return payload


def create_production_line_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "line_code": TEST_DEFAULTS["LINE_CODE"],
        "machine_family": TEST_DEFAULTS["MACHINE_FAMILY"],
        "changeover_buffer_days": TEST_DEFAULTS["CHANGEOVER_BUFFER_DAYS"],
        "capacity_days_per_quarter": TEST_DEFAULTS["CAPACITY_DAYS_PER_QUARTER"],
    }
    payload.update(overrides)
    return payload


def create_field_engineer_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": TEST_DEFAULTS["ENGINEER_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
        "certifications": [TEST_DEFAULTS["MACHINE_FAMILY"]],
        "travel_buffer_minutes": 60,
    }
    payload.update(overrides)
    return payload


def create_product_trial_payload(
    customer_id: str, machine_model_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "customer_id": customer_id,
        "machine_model_id": machine_model_id,
        "product_name": TEST_DEFAULTS["PRODUCT_NAME"],
        "container_family": TEST_DEFAULTS["CONTAINER_FAMILY"],
        "container_diameter_mm": TEST_DEFAULTS["CONTAINER_DIAMETER_MM"],
    }
    payload.update(overrides)
    return payload


def record_trial_result_payload(measured_rate_cpm: int = 570, outcome: str = "PASS") -> Dict[str, Any]:
    return {"measured_rate_cpm": measured_rate_cpm, "outcome": outcome}


def create_machine_order_payload(
    customer_id: str, machine_model_id: str, product_trial_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "customer_id": customer_id,
        "machine_model_id": machine_model_id,
        "product_trial_id": product_trial_id,
        "equipment_price_cents": TEST_DEFAULTS["EQUIPMENT_PRICE_CENTS"],
        "change_parts_price_cents": TEST_DEFAULTS["CHANGE_PARTS_PRICE_CENTS"],
        "guarantee_basis": "NAMEPLATE",
    }
    payload.update(overrides)
    return payload


def create_long_lead_component_payload(
    machine_order_id: str, part_number: str = "PN-VALVE-01", lead_time_days: int = 10, **overrides
) -> Dict[str, Any]:
    payload = {
        "machine_order_id": machine_order_id,
        "part_number": part_number,
        "lead_time_days": lead_time_days,
    }
    payload.update(overrides)
    return payload


def create_build_slot_payload(
    machine_order_id: str,
    production_line_id: str,
    expected_machine_order_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "machine_order_id": machine_order_id,
        "production_line_id": production_line_id,
        "start_date": TEST_DEFAULTS["SLOT_START_DATE"],
        "requested_slot_days": TEST_DEFAULTS["REQUESTED_SLOT_DAYS"],
        "expected_machine_order_version": expected_machine_order_version,
    }
    payload.update(overrides)
    return payload


def create_acceptance_test_payload(
    machine_order_id: str, kind: str = "FAT", **overrides
) -> Dict[str, Any]:
    payload = {
        "machine_order_id": machine_order_id,
        "kind": kind,
        "scheduled_on": (
            TEST_DEFAULTS["FAT_SCHEDULED_ON"] if kind == "FAT" else TEST_DEFAULTS["SAT_SCHEDULED_ON"]
        ),
    }
    payload.update(overrides)
    return payload


def start_acceptance_test_payload(
    customer_product_supplied: bool = True, containers_supplied_count: int = 500
) -> Dict[str, Any]:
    return {
        "customer_product_supplied": customer_product_supplied,
        "containers_supplied_count": containers_supplied_count,
    }


def finalize_acceptance_test_payload(
    measured_rate_cpm: int = 570,
    measured_efficiency_pct: float = 96.00,
    operators_trained_count: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "measured_rate_cpm": measured_rate_cpm,
        "measured_efficiency_pct": measured_efficiency_pct,
    }
    if operators_trained_count is not None:
        payload["operators_trained_count"] = operators_trained_count
    return payload


def create_installed_machine_payload(
    machine_order_id: str, customer_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "machine_order_id": machine_order_id,
        "customer_id": customer_id,
        "serial_number": TEST_DEFAULTS["SERIAL_NUMBER"],
        "remote_diagnostics_enabled": True,
    }
    payload.update(overrides)
    return payload


def kit_component(
    part_number: str = "CP-001",
    lead_time_days: int = 30,
    unit_price_cents: int = 100_000,
    qty: int = 2,
) -> Dict[str, Any]:
    return {
        "part_number": part_number,
        "lead_time_days": lead_time_days,
        "unit_price_cents": unit_price_cents,
        "qty": qty,
    }


def create_format_kit_payload(
    installed_machine_id: str, components: Optional[List[Dict[str, Any]]] = None, **overrides
) -> Dict[str, Any]:
    payload = {
        "installed_machine_id": installed_machine_id,
        "container_family": "GLASS_SQUARE",
        "container_diameter_mm": 82,
        "components": [kit_component()] if components is None else components,
    }
    payload.update(overrides)
    return payload


def create_service_contract_payload(installed_machine_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "installed_machine_id": installed_machine_id,
        "tier": "SILVER",
        "start_date": TEST_DEFAULTS["CONTRACT_START_DATE"],
        "end_date": TEST_DEFAULTS["CONTRACT_END_DATE"],
        "pm_visits_included": 2,
        "goodwill_budget_initial_cents": 500_000,
    }
    payload.update(overrides)
    return payload


def create_pm_visit_payload(service_contract_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "service_contract_id": service_contract_id,
        "visit_type": "PM",
        "start_ts": "2026-08-10T08:00:00.000Z",
        "end_ts": "2026-08-10T12:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(
    installed_machine_id: str, service_contract_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "installed_machine_id": installed_machine_id,
        "service_contract_id": service_contract_id,
        "failure_summary": "Filling valve seat fractured after 300 hours",
    }
    payload.update(overrides)
    return payload


def create_warranty_claim_line_payload(
    warranty_claim_id: str,
    amount_cents: int = 400_000,
    defect_attribution_pct: float = 100.00,
    line_label: str = "Valve seat assembly",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "warranty_claim_id": warranty_claim_id,
        "line_label": line_label,
        "amount_cents": amount_cents,
        "defect_attribution_pct": defect_attribution_pct,
    }
    payload.update(overrides)
    return payload


def create_stocking_recommendation_payload(
    installed_machine_id: str, expected_installed_machine_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "installed_machine_id": installed_machine_id,
        "part_number": "SP-SEAL-01",
        "annual_usage_qty": 365,
        "unit_lead_time_days": 20,
        "criticality": "A",
        "basis": "LEAD_TIME_DEMAND",
        "expected_installed_machine_version": expected_installed_machine_version,
    }
    payload.update(overrides)
    return payload
