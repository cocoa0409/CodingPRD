"""Payload factories — one per resource, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_ASSEMBLY,
    POSTURE_LADDER_DEFAULT,
    RATE_EFFECTIVE_FROM_ISO,
    STRAP_ASSEMBLY,
    TEST_DEFAULTS,
)

ASSEMBLY_CATALOG = {
    DEFAULT_ASSEMBLY["assembly_code"]: DEFAULT_ASSEMBLY,
    STRAP_ASSEMBLY["assembly_code"]: STRAP_ASSEMBLY,
}


def project_payload(**overrides) -> dict:
    payload = {
        "project_code": "P-3333-GEN",
        "project_name": "Deck GEN",
        "jurisdiction_key": TEST_DEFAULTS["JURISDICTION"],
        "planned_value_cents": TEST_DEFAULTS["PLANNED_VALUE_CENTS"],
        "power_on_iso": TEST_DEFAULTS["POWER_ON_ISO"],
        "laydown_slots": TEST_DEFAULTS["LAYDOWN_SLOTS"],
        "credit_policy": "FIRST_ACCEPTED",
        "posture_thresholds": dict(POSTURE_LADDER_DEFAULT),
        "shop_utilization_pct": TEST_DEFAULTS["SHOP_UTILIZATION_PCT"],
        "total_quantity": TEST_DEFAULTS["TOTAL_QUANTITY"],
        "released_quantity": 0,
        "float_band_low_pct": TEST_DEFAULTS["FLOAT_BAND_LOW_PCT"],
        "safety_program_required": True,
    }
    payload.update(overrides)
    return payload


def model_version_payload(**overrides) -> dict:
    payload = {
        "model_id": "mdl-gen",
        "revision_letter": "A",
        "status": "DRAFT",
    }
    payload.update(overrides)
    return payload


def takeoff_line_payload(**overrides) -> dict:
    payload = {
        "model_version_id": None,
        "zone_code": "Z-1",
        "assembly_code": DEFAULT_ASSEMBLY["assembly_code"],
        "conduit_run_type": "RIGID_RACK",
        "conduit_run_type_code": "RC50",
        "quantity": 100,
        "prefab_share_pct": 0.5,
    }
    payload.update(overrides)
    return payload


def rack_payload(**overrides) -> dict:
    payload = {
        "model_version_id": None,
        "rack_code": "R-GEN",
        "zone_code": "Z-1",
        "top_elevation_ft": 12.0,
        "rack_hoist_date": TEST_DEFAULTS["RACK_HOIST_DATE_ISO"],
        "value_capacity_cf": TEST_DEFAULTS["RACK_CAPACITY_CF"],
        "direct_assignment": True,
        "ordering_strength_rule": "HOLD_WINDOW",
    }
    payload.update(overrides)
    return payload


def prefab_order_payload(**overrides) -> dict:
    payload = {
        "project_id": None,
        "model_version_id": None,
        "stage_code": "FIRST_STAGE",
        "zone_code": "Z-1",
        "transport_kind": "FLATBED",
        "hoisting_window_id": "HW-GEN",
        "required_on_site_iso": TEST_DEFAULTS["REQUIRED_ON_SITE_ISO"],
        "installation_window_start_iso": TEST_DEFAULTS["INSTALL_WINDOW_START_ISO"],
        "fabricate_quantity": 1,
        "shop_utilisation_basis_pct": TEST_DEFAULTS["SHOP_UTILIZATION_PCT"],
    }
    payload.update(overrides)
    return payload


def prefab_component_payload(**overrides) -> dict:
    payload = {
        "prefab_order_id": None,
        "rack_id": None,
        "takeoff_line_id": None,
        "predecessor_component_id": None,
        "assembly_code": DEFAULT_ASSEMBLY["assembly_code"],
        "quantity": 50,
        "chain_mode": "PARALLEL_FABRICATION",
        "chain_dependency_link": "LNK-GEN",
    }
    payload.update(overrides)
    return payload


def worker_payload(**overrides) -> dict:
    payload = {
        "worker_code": "W-GEN-1",
        "full_name": "General Wireman",
        "classification": "JOURNEYMAN",
        "apprentice_period": None,
        "home_jurisdiction_key": TEST_DEFAULTS["JURISDICTION"],
        "qualification_state_code": "GEN-1",
        "percent_complete_certified": 0,
        "percent_complete_verified": 0,
        "safety_verified_status": "VERIFIED",
        "safety_verification_code": "SAFE-GEN-1",
    }
    payload.update(overrides)
    return payload


def apprentice_payload(**overrides) -> dict:
    payload = worker_payload(
        worker_code="W-GEN-AP",
        full_name="A. Learner",
        classification="APPRENTICE",
        apprentice_period=2,
        qualification_state_code="AP-GEN",
        safety_verification_code="SAFE-GEN-AP",
    )
    payload.update(overrides)
    return payload


def trade_contract_rate_payload(**overrides) -> dict:
    payload = {
        "jurisdiction_key": TEST_DEFAULTS["JURISDICTION"],
        "classification": "JOURNEYMAN",
        "apprentice_period": None,
        "hourly_rate_cents": TEST_DEFAULTS["JOURNEYMAN_RATE_CENTS"],
        "burden_pct": TEST_DEFAULTS["BURDEN_PCT"],
        "apprentice_ratio_max": 1.0,
        "wait_ratio_max": 1.0,
        "effective_from_iso": RATE_EFFECTIVE_FROM_ISO,
    }
    payload.update(overrides)
    return payload


def trade_activity_payload(**overrides) -> dict:
    payload = {
        "project_id": None,
        "trade_key": "ELECTRICAL",
        "activity_kind": "ELECTRICAL_INSTALL",
        "work_front_code": "WF-1",
        "bay_code": "BAY-A",
        "planned_start_iso": "2026-10-01T00:00:00Z",
        "planned_duration_days": 5,
        "written_sequence_index": 1,
        "revision_id": None,
        "rate_id": None,
        "permit_id": None,
    }
    payload.update(overrides)
    return payload


def crew_day_payload(**overrides) -> dict:
    payload = {
        "project_id": None,
        "worker_id": None,
        "foreman_id": None,
        "trade_activity_id": None,
        "work_date_iso": TEST_DEFAULTS["WORK_DATE_ISO"],
        "regular_hours": 8.0,
        "overtime_hours": 0.0,
        "report_sequence": 1,
        "acknowledge_mode": "FINAL",
    }
    payload.update(overrides)
    return payload


def revision_payload(**overrides) -> dict:
    payload = {
        "project_id": None,
        "model_version_id": None,
        "revised_version_id": None,
        "revision_kind": "DESIGN_CHANGE",
        "impact_keys": [],
        "maintenance_hours": 4,
        "buffer_before_hours": 2,
        "momentum_before_hours": 1,
        "base_service_hours": 120,
        "paid_service_hours": 0,
        "billed_service_hours": 0,
        "percent_complete_mode": "FLOW",
        "label_percent_complete": 40,
        "label_codes": ["FAB_CONTENT"],
        "fabricated_content_codes": ["FAB_CONTENT"],
        "shop_parts_value_cents": 250000,
        "shop_parts_quantity": 5,
        "revision_quantity": 3,
        "impact_qualified_hours": 40,
        "effort_hours": 12,
        "kludge_rate_per_hour_cents": 8500,
        "negotiated_rate_per_hour_cents": 7800,
        "submitted_markup_pct": 0.18,
        "direct_shop_cost_cents": 200000,
        "replacement_lifecycle_percent": 100,
        "prior_lifecycle_percent": 60,
        "safety_gate_status": "PASSED",
        "label_verified_status": "VERIFIED",
        "safety_verified_status": "VERIFIED",
        "label_percentage": 40,
        "qualified_lifecycle_percent": 25,
        "proposed_waiver": False,
    }
    payload.update(overrides)
    return payload


def material_release_payload(**overrides) -> dict:
    payload = {
        "project_id": None,
        "model_version_id": None,
        "vendor_key": "V-GEN",
        "material_commodity": "MC_CABLE",
        "quantity": 500,
        "unit_price_cents": 3200,
        "lead_time_days": 7,
        "service_priority": "NEXT_DAY",
        "commitment_mode": "PLANNED",
        "planned_release_iso": TEST_DEFAULTS["MATERIAL_PLANNED_RELEASE_ISO"],
        "receiving_user_id": "op-recv-1",
    }
    payload.update(overrides)
    return payload