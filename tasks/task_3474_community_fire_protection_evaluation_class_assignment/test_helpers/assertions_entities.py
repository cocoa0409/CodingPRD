"""Entity assertions: registry, department, and water-domain resources.

Each ``assert_*`` checks the structural contract of a single resource body:
common fields, field presence, primitive types, and enum membership. Values
that depend on computation are checked for presence/nullability only —
exact numbers belong to the tests that pin them.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApparatusKind,
    ApparatusStatus,
    CommunityStatus,
    CycleStatus,
    DepartmentType,
    FlowTestStatus,
    HydrantStatus,
    TrainingFacilityLevel,
)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def assert_common_fields(data: Dict[str, Any]) -> None:
    """Every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_community(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["population"], int) and data["population"] > 0
    assert _is_number(data["area_sq_miles"]) and data["area_sq_miles"] > 0
    assert _is_number(data["rural_area_pct"]) and 0 <= data["rural_area_pct"] <= 100
    assert isinstance(data["comms_operators_on_duty_min"], int)
    assert isinstance(data["comms_avg_alarm_to_dispatch_seconds"], int)
    assert isinstance(data["comms_redundant_circuits"], bool)
    assert isinstance(data["comms_backup_power"], bool)
    assert isinstance(data["comms_attested"], bool)
    assert data.get("comms_attested_by") is None or isinstance(data["comms_attested_by"], str)
    assert data.get("comms_attested_at") is None or is_iso8601_timestamp(data["comms_attested_at"])
    assert data["status"] in {s.value for s in CommunityStatus}
    for key in ("current_class_number", "current_split_class"):
        assert data.get(key) is None or (isinstance(data[key], int) and 1 <= data[key] <= 10), key
    assert data.get("current_premium_modifier") is None or _is_number(data["current_premium_modifier"])
    assert isinstance(data["bound_exposure_cents"], int) and data["bound_exposure_cents"] >= 0
    assert data.get("next_evaluation_due_date") is None or isinstance(data["next_evaluation_due_date"], str)


def assert_evaluation_cycle(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert isinstance(data["field_analyst_id"], str) and data["field_analyst_id"]
    assert isinstance(data["scheduled_open_date"], str)
    assert isinstance(data["data_freeze_date"], str)
    assert data["status"] in {s.value for s in CycleStatus}
    assert data.get("opened_at") is None or is_iso8601_timestamp(data["opened_at"])


def assert_fire_department(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert data["dept_type"] in {t.value for t in DepartmentType}
    assert isinstance(data["stations_active_count"], int) and data["stations_active_count"] >= 0
    assert isinstance(data["career_on_duty_per_shift"], int) and data["career_on_duty_per_shift"] >= 0
    assert _is_number(data["volunteers_on_duty_avg"]) and data["volunteers_on_duty_avg"] >= 0
    assert _is_number(data["training_hours_per_firefighter_annual"])
    assert data["training_facility_level"] in {t.value for t in TrainingFacilityLevel}
    assert isinstance(data["live_fire_training"], bool)
    assert _is_number(data["coverage_pct_within_5mi"]) and 0 <= data["coverage_pct_within_5mi"] <= 100
    assert isinstance(data["data_submitted"], bool)


def assert_apparatus(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("department_id", "")), "department_id must be a UUID"
    assert data["kind"] in {k.value for k in ApparatusKind}
    for key in ("pump_capacity_gpm", "tank_capacity_gal", "ladder_height_ft"):
        assert data.get(key) is None or (isinstance(data[key], int) and data[key] >= 0), key
    assert data["status"] in {s.value for s in ApparatusStatus}


def assert_water_supply_system(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert isinstance(data["needed_fire_flow_gpm"], int) and 500 <= data["needed_fire_flow_gpm"] <= 50000
    assert isinstance(data["storage_capacity_gal"], int) and data["storage_capacity_gal"] >= 0
    assert isinstance(data["supply_works_capacity_gpm"], int) and data["supply_works_capacity_gpm"] > 0
    assert isinstance(data["daily_consumption_gpm"], int) and data["daily_consumption_gpm"] >= 0
    assert isinstance(data["alternate_shuttle_capacity_gpm"], int) and data["alternate_shuttle_capacity_gpm"] >= 0
    assert isinstance(data["alternate_sites_count"], int) and data["alternate_sites_count"] >= 0
    assert isinstance(data["alternate_verified"], bool)
    assert _is_number(data["active_certified_flow_gpm"]) and data["active_certified_flow_gpm"] >= 0
    assert isinstance(data["creditworthy_hydrant_count"], int) and data["creditworthy_hydrant_count"] >= 0


def assert_hydrant(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("system_id", "")), "system_id must be a UUID"
    assert isinstance(data["location_descriptor"], str)
    assert data["status"] in {s.value for s in HydrantStatus}
    assert data.get("max_flow_gpm") is None or isinstance(data["max_flow_gpm"], int)
    assert data.get("last_certified_test_date") is None or isinstance(data["last_certified_test_date"], str)


def assert_flow_test(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("system_id", "")), "system_id must be a UUID"
    assert is_valid_uuid(data.get("hydrant_id", "")), "hydrant_id must be a UUID"
    assert data.get("supersedes_test_id") is None or is_valid_uuid(data["supersedes_test_id"])
    assert isinstance(data["test_date"], str)
    assert _is_number(data["static_psi"]) and 20 < data["static_psi"] <= 300
    assert _is_number(data["residual_psi"]) and data["residual_psi"] >= 10
    assert data["residual_psi"] < data["static_psi"], "residual must stay strictly below static"
    assert _is_number(data["measured_flow_gpm"]) and data["measured_flow_gpm"] > 0
    assert data.get("flow_at_20psi_gpm") is None or isinstance(data["flow_at_20psi_gpm"], int)
    assert data["status"] in {s.value for s in FlowTestStatus}
    assert data.get("witnessed_by") is None or isinstance(data["witnessed_by"], str)
    assert data.get("certified_by") is None or isinstance(data["certified_by"], str)
    assert data.get("correction_reason") is None or isinstance(data["correction_reason"], str)
