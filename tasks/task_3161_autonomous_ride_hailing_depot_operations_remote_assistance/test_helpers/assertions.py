"""Entity shape assertions and domain invariant checkers.

Each ``assert_<entity>`` checks the server-minted identity fields the PRD
guarantees plus the caller-visible business fields, without over-asserting
on fields a PRD-only implementer could reasonably render differently.
Value-level expectations stay in the tests themselves.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from . import constants as c

# Re-export the framework validators so tests can import from one place.
__all__ = [
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
    "assert_territory",
    "assert_depot",
    "assert_vehicle",
    "assert_bay_slot",
    "assert_cycle",
    "assert_wave",
    "assert_demand_signal",
    "assert_area_rule",
    "assert_exclusion_zone",
    "assert_expansion_request",
    "assert_ride",
    "assert_pickup_location",
    "assert_curb_rule",
    "assert_assistance_session",
    "assert_incident_report",
    "assert_roadside_case",
    "assert_roadside_team",
    "assert_vehicle_invariants",
    "assert_depot_invariants",
]


def _common_identity(data, *, expect_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a plain UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    if expect_version:
        assert isinstance(data.get("version"), int), "version must be an integer"
        assert data["version"] >= 1, "version starts at 1 on creation"


def assert_territory(data: dict):
    _common_identity(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["posture"] in [
        c.POSTURE_PENDING, c.POSTURE_MAPPING, c.POSTURE_VALIDATING,
        c.POSTURE_ACTIVE, c.POSTURE_RESTRICTED, c.POSTURE_SUSPENDED,
    ]
    assert isinstance(data["mapped_pct"], int) and 0 <= data["mapped_pct"] <= 100
    assert isinstance(data["validation_hours"], int) and data["validation_hours"] >= 0
    assert isinstance(data["active_zone_count"], int)
    assert isinstance(data["total_credit_cents"], int)
    assert isinstance(data["total_severe_incidents"], int)


def assert_depot(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert data["posture"] in [c.DEPOT_OPEN, c.DEPOT_CONGESTED, c.DEPOT_LOCKDOWN]
    assert isinstance(data["occupancy_pct"], int) and 0 <= data["occupancy_pct"] <= 100
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0
    for field in ("charge_positions", "cleaning_positions", "calib_positions", "software_positions"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_vehicle(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert data["status"] in [
        c.VEHICLE_DRAFT, c.VEHICLE_IN_SERVICE, c.VEHICLE_AT_DEPOT,
        c.VEHICLE_ROADSIDE, c.VEHICLE_SUSPENDED,
    ]
    assert data["service_status"] in [
        c.SERVICE_UNAVAILABLE, c.SERVICE_AVAILABLE, c.SERVICE_DISPATCHED, c.SERVICE_ON_TRIP,
    ]
    assert isinstance(data["battery_pct"], int) and 0 <= data["battery_pct"] <= 100
    assert isinstance(data["cleanliness_score"], int) and 0 <= data["cleanliness_score"] <= 100
    assert isinstance(data["calib_valid"], bool)
    assert isinstance(data["is_roadside_blocked"], bool)
    assert isinstance(data["credit_cents"], int)
    assert data["credit_cents"] >= 0, "credit balance is bounded below at zero"
    assert data.get("current_depot_id") is None or is_valid_uuid(data["current_depot_id"])


def assert_bay_slot(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["depot_id"])
    assert data["service_type"] in [
        c.KIND_CHARGE, c.KIND_CLEAN, c.KIND_CALIBRATION, c.KIND_SOFTWARE
    ]
    assert data["status"] in [c.SLOT_RESERVED, c.SLOT_ACTIVE, c.SLOT_COMPLETED, c.SLOT_RELEASED]
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] > 0


def assert_cycle(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["depot_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["service_kind"] in [
        c.KIND_CHARGE, c.KIND_CLEAN, c.KIND_CALIBRATION, c.KIND_SOFTWARE
    ]
    assert data["status"] in [c.CYCLE_STAGED, c.CYCLE_IN_PROGRESS, c.CYCLE_COMPLETED, c.CYCLE_ABORTED]
    assert isinstance(data["is_scheduled"], bool)


def assert_wave(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert data["status"] in [c.WAVE_PLANNED, c.WAVE_ACTIVE, c.WAVE_COMPLETED, c.WAVE_ABORTED]
    assert isinstance(data["planned_vehicle_count"], int)
    assert isinstance(data["deployed_vehicle_count"], int)
    assert data["deployed_vehicle_count"] >= 0


def assert_demand_signal(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert isinstance(data["projected_rides"], int)
    assert isinstance(data["manual_only_rides"], int)
    assert isinstance(data["effective_demand"], int)
    assert data["effective_demand"] == max(0, data["projected_rides"] - data["manual_only_rides"])


def assert_area_rule(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert isinstance(data["rule_version"], int)
    assert data["route_class"] in [c.ROUTE_FREEWAY, c.ROUTE_ARTERIAL, c.ROUTE_RESIDENTIAL, c.ROUTE_ALLEY]
    assert isinstance(data["allowed"], bool)
    assert data["status"] in [c.RULE_DRAFT, c.RULE_APPROVED, c.RULE_RETIRED]


def assert_exclusion_zone(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert data["kind"] in ["CONSTRUCTION", "EVENT", "EMERGENCY", "WEATHER", "TEMPORARY"]
    assert data["status"] in [c.ZONE_SCHEDULED, c.ZONE_ACTIVE, c.ZONE_EXPIRED]
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert isinstance(data["duration_seconds"], int)


def assert_expansion_request(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert data["status"] in [
        c.EXPANSION_SUBMITTED, c.EXPANSION_MAPPING_COMPLETE, c.EXPANSION_VALIDATION_FAILED,
        c.EXPANSION_CONDITIONALLY_APPROVED, c.EXPANSION_APPROVED, c.EXPANSION_REJECTED,
    ]
    assert isinstance(data["mapped_pct_at_submit"], int)


def assert_ride(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert data["status"] in [
        c.RIDE_REQUESTED, c.RIDE_MATCHED, c.RIDE_PICKED_UP, c.RIDE_COMPLETED,
        c.RIDE_CANCELLED_NO_SHOW, c.RIDE_CANCELLED, c.RIDE_FAILED,
    ]
    assert data["sub_service_type"] in [c.SUB_SERVICE_STANDARD, c.SUB_SERVICE_ASSISTED]
    assert isinstance(data["dispatch_attempts"], int)
    assert data["dispatch_attempts"] >= 0
    assert data.get("vehicle_id") is None or is_valid_uuid(data["vehicle_id"])


def assert_pickup_location(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert data["curb_access"] in [c.CURB_SAFE, c.CURB_NO_STOPPING, c.CURB_LOADING_ONLY]
    assert isinstance(data["is_valid"], bool)


def assert_curb_rule(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert data["curb_access"] in [c.CURB_SAFE, c.CURB_NO_STOPPING, c.CURB_LOADING_ONLY]
    assert data["sub_service_type"] in [c.SUB_SERVICE_STANDARD, c.SUB_SERVICE_ASSISTED]
    assert isinstance(data["allowed"], bool)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_assistance_session(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["ride_request_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["reason"] in ["STUCK", "ROAD_BLOCKED", "SENSOR_FAULT", "PASSENGER_ASSIST", "OTHER"]
    assert data["status"] in [
        c.SESSION_ESCALATED, c.SESSION_ACKNOWLEDGED, c.SESSION_RESOLVED, c.SESSION_UNRESOLVED
    ]
    assert isinstance(data["escalation_tier"], int) and data["escalation_tier"] >= 1
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_incident_report(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["assistance_session_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["severity"] in ["MINOR", "MODERATE", "SEVERE"]
    assert data["status"] in [
        c.INCIDENT_FILED, c.INCIDENT_UNDER_REVIEW, c.INCIDENT_CLOSED, c.INCIDENT_VOIDED
    ]
    assert isinstance(data["crash_evidence_retained"], bool)
    assert data["crash_evidence_retained"] == (data["severity"] in ("MODERATE", "SEVERE"))
    assert is_iso8601_timestamp(data["retention_expires_at"])


def assert_roadside_case(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["road_class"] in [c.ROUTE_ARTERIAL, c.ROUTE_FREEWAY, c.ROUTE_RESIDENTIAL]
    assert data["status"] in [
        c.CASE_OPEN, c.CASE_TEAM_ASSIGNED, c.CASE_RESPONSE_DISPATCHED,
        c.CASE_CLEARED, c.CASE_CANCELLED,
    ]
    assert isinstance(data["raise_count"], int)


def assert_roadside_team(data: dict):
    _common_identity(data)
    assert is_valid_uuid(data["territory_id"])
    assert isinstance(data["team_code"], str) and data["team_code"]
    assert data["road_class"] in [c.ROUTE_ARTERIAL, c.ROUTE_FREEWAY, c.ROUTE_RESIDENTIAL]
    assert data["status"] in [c.TEAM_AVAILABLE, c.TEAM_ON_CASE, c.TEAM_OFF_SHIFT]


def assert_vehicle_invariants(data: dict):
    """Readiness verdict invariants that must hold after any operation."""
    ready = (
        data["battery_pct"] >= c.MIN_BATTERY_PCT
        and data["cleanliness_score"] >= c.MIN_CLEANLINESS_SCORE
        and data["calib_valid"] is True
        and data["software_version"] == data["target_software_version"]
    )
    if data["is_roadside_blocked"] or data["status"] == c.VEHICLE_IN_SERVICE:
        assert data["service_status"] == c.SERVICE_DISPATCHED
    elif data["status"] == c.VEHICLE_AT_DEPOT:
        assert data["service_status"] == (c.SERVICE_AVAILABLE if ready else c.SERVICE_UNAVAILABLE)
    else:
        assert data["service_status"] == c.SERVICE_UNAVAILABLE
    assert data["credit_cents"] >= 0


def assert_depot_invariants(data: dict):
    """Posture invariants that must hold after any operation."""
    if data["occupancy_pct"] == 100:
        assert data["posture"] == c.DEPOT_LOCKDOWN
    elif data["occupancy_pct"] >= c.CONGESTION_THRESHOLD_PCT:
        assert data["posture"] == c.DEPOT_CONGESTED
    else:
        assert data["posture"] == c.DEPOT_OPEN