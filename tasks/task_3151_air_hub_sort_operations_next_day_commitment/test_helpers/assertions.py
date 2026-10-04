"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

# ─── Enumerations the PRD pins, used for membership assertions ─────────────

HUB_POSTURES = ["OPEN", "CONGESTED", "LOCKDOWN", "GROUND_STOP"]
BANK_STATUSES = ["SCHEDULED", "EN_ROUTE", "UNLOADING", "UNLOADED", "CLOSED", "ABANDONED"]
AIRCRAFT_STATUSES = ["SCHEDULED", "IN_FLIGHT", "LANDED", "UNLOADING", "UNLOADED", "CANCELLED"]
COMMODITY_CLASSES = ["GENERAL", "IRREGULAR", "HAZMAT", "PERISHABLE"]
SERVICE_LEVELS = ["NEXT_DAY_AIR", "SECOND_DAY_AIR", "GROUND"]
INDUCTION_STATUSES = ["NOT_INDUCTED", "INDUCTED", "REJECTED"]
SORT_STATUSES = ["UNSORTED", "PRIMARY_SORTED", "SECONDARY_SORTED", "LOADED"]
COMMITMENT_STATUSES = ["COMMITTED", "DOWNGRADED", "REROUTED", "VOIDED", "UPGRADED_HELD"]
HANDLING_STATUSES = ["NORMAL", "ROUTED_TO_IRREGULAR", "ROUTED_TO_HAZMAT", "DIVERTED", "HOLD_AT_HUB"]
HANDLING_POSTURES = ["STANDARD", "IRREGULAR_LANE", "HAZMAT_LANE"]
COMMITMENT_POSTURES = ["COMMITTED_OK", "DOWNGRADE_PENDING", "REROUTE_PENDING"]
LANE_KINDS = ["PRIMARY", "SECONDARY", "IRREGULAR", "HAZMAT"]
LANE_STATUSES = ["AVAILABLE", "SATURATED", "CLOSED"]
LOAD_MOVE_STATUSES = ["DRAFT", "PLANNED", "LOADING", "LOADED", "REWORK_REQUIRED", "CANCELLED"]
BUILDUP_STATUSES = ["OPEN", "SEALED", "WEIGHT_BREACH", "CANCELLED"]
LOAD_PLAN_TIERS = ["UNDER_CAPACITY", "AT_CAPACITY", "RESERVE_TIER"]
FEEDER_STATUSES = ["SCHEDULED", "STAGING", "LOADING", "DEPARTED", "CANCELLED"]
SHIFT_STATUSES = ["SCHEDULED", "OVERRUN", "COMPLETED", "CANCELLED"]
STAFFING_POSTURES = ["GREEN", "AMBER", "RED", "SATURATED"]
OPS_RUN_LEVELS = ["MINOR", "MAJOR"]
OPS_RUN_VERDICTS = ["ADVANCED", "HELD", "RELEASED"]
FAILURE_STATUSES = ["OPEN", "FINALIZED", "DISPUTED", "VOIDED"]
ATTRIBUTED_ROLES = ["CARRIER", "CUSTOMER", "WEATHER_EVENT", "MECHANICAL_EVENT"]


# ─── Shared envelope-level helpers ─────────────────────────────────────────

def confirm(response, expected_status: int = 200) -> dict:
    """Validate a mutating call under test and return its data payload."""
    return validate_success(response, expected_status)


def confirm_list(response, expected_status: int = 200) -> tuple:
    """Validate a list read under test and return ``(data, meta)``.

    ``validate_success`` returns only ``data``, so call sites that need the
    pagination fields must use this helper instead of ``confirm``.
    """
    assert response.status_code == expected_status, (
        f"Expected {expected_status}, got {response.status_code}: {response.text}"
    )
    return validate_paginated(response)


def _assert_identity(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"


def _assert_mutable(data: dict):
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


# ─── Per-entity assertions ─────────────────────────────────────────────────

def assert_hub(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert isinstance(data["iata_code"], str) and len(data["iata_code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["sort_window_open_minutes"], int)
    assert isinstance(data["sort_window_close_minutes"], int)
    assert data["posture"] in HUB_POSTURES
    assert isinstance(data["contingency_mode"], bool)
    assert isinstance(data["live_planned_package_total"], int)
    assert isinstance(data["ops_run_index"], int)


def assert_arrival_bank(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert isinstance(data["bank_code"], str)
    assert isinstance(data["hydraulic_crew_available"], bool)
    assert data["status"] in BANK_STATUSES
    assert isinstance(data["effective_sort_budget_minutes"], int)


def assert_aircraft(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert isinstance(data["tail_number"], str)
    assert isinstance(data["origin_station_code"], str)
    assert data["status"] in AIRCRAFT_STATUSES
    assert isinstance(data["maintenance_hold"], bool)


def assert_package(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert data["commodity_class"] in COMMODITY_CLASSES
    assert data["service_level"] in SERVICE_LEVELS
    assert data["induction_status"] in INDUCTION_STATUSES
    assert data["sort_status"] in SORT_STATUSES
    assert data["commitment_status"] in COMMITMENT_STATUSES
    assert data["handling_status"] in HANDLING_STATUSES
    assert data["handling_posture"] in HANDLING_POSTURES
    assert data["commitment_posture"] in COMMITMENT_POSTURES
    assert isinstance(data["commitment_cutoff_minutes"], int)
    assert isinstance(data["planned_weight_grams"], int) and data["planned_weight_grams"] > 0
    assert isinstance(data["dimension_weight_grams"], int) and data["dimension_weight_grams"] > 0


def assert_sort_lane(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert data["lane_kind"] in LANE_KINDS
    assert data["commodity_capability"] in COMMODITY_CLASSES
    assert data["status"] in LANE_STATUSES
    assert isinstance(data["capacity_weight_grams"], int) and data["capacity_weight_grams"] > 0
    assert isinstance(data["lane_load_grams"], int) and data["lane_load_grams"] >= 0


def assert_load_move(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert data["status"] in LOAD_MOVE_STATUSES
    assert data["load_plan_tier"] in LOAD_PLAN_TIERS
    assert isinstance(data["weight_limit_grams"], int) and data["weight_limit_grams"] > 0
    assert isinstance(data["forward_capacity_grams"], int)
    assert data["forward_capacity_grams"] >= 0, "forward_capacity_grams is floored at zero"
    assert isinstance(data["gateway_requirements"], dict)


def assert_buildup(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert data["status"] in BUILDUP_STATUSES
    assert data["load_plan_tier"] in LOAD_PLAN_TIERS
    assert isinstance(data["hazardous_load"], bool)
    assert isinstance(data["requires_container"], bool)
    assert isinstance(data["container_limit_grams"], int) and data["container_limit_grams"] > 0
    assert isinstance(data["hazardous_cap_grams"], int)
    assert isinstance(data["hazardous_weight_grams"], int)


def assert_ground_feeder(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert data["status"] in FEEDER_STATUSES
    assert isinstance(data["scheduled_departure_minutes"], int)
    assert isinstance(data["stage_capacity_grams"], int) and data["stage_capacity_grams"] > 0
    assert isinstance(data["window_minutes"], int) and data["window_minutes"] > 0
    assert isinstance(data["staged_weight_grams"], int) and data["staged_weight_grams"] >= 0


def assert_labor_shift(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert data["status"] in SHIFT_STATUSES
    assert data["staffing_posture"] in STAFFING_POSTURES
    assert isinstance(data["headcount"], int) and data["headcount"] > 0
    assert isinstance(data["productivity_grams_per_operator_hour"], int)
    assert isinstance(data["forecast_volume_grams"], int) and data["forecast_volume_grams"] > 0
    assert isinstance(data["certified_for_hazmat"], bool)
    assert isinstance(data["volume_variance_pct"], (int, float))


def assert_service_failure(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert data["attributed_role"] in ATTRIBUTED_ROLES
    assert data["status"] in FAILURE_STATUSES
    assert isinstance(data["refund_eligible"], bool)
    assert isinstance(data["refund_amount_cents"], int)
    assert isinstance(data["failure_minutes"], int)
    # refund eligibility is exactly the carrier attribution
    assert data["refund_eligible"] == (data["attributed_role"] == "CARRIER"), (
        "refund_eligible must equal (attributed_role == CARRIER)"
    )


def assert_ops_run(data: dict):
    """OpsRun is created once and never modified: id + created_at only."""
    _assert_identity(data)
    assert "version" not in data, "OpsRun must not carry a version field"
    assert "updated_at" not in data, "OpsRun must not carry an updated_at field"
    assert isinstance(data["run_index"], int) and data["run_index"] >= 1
    assert isinstance(data["minute_of_day"], int)
    assert data["level"] in OPS_RUN_LEVELS
    assert data["verdict"] in OPS_RUN_VERDICTS


def assert_service_failure_claim(data: dict):
    """ServiceFailureClaim is append-only: id + created_at only."""
    _assert_identity(data)
    assert "version" not in data, "ServiceFailureClaim must not carry a version field"
    assert "updated_at" not in data, "ServiceFailureClaim must not carry an updated_at field"
    assert isinstance(data["claim_index"], int) and data["claim_index"] >= 1
    assert isinstance(data["service_failure_id"], str) and len(data["service_failure_id"]) > 0
    if data.get("note") is not None:
        assert isinstance(data["note"], str)


# ─── Domain invariant checkers ─────────────────────────────────────────────

def assert_hub_invariants(data: dict):
    """Invariants that must hold on every hub read."""
    assert data["sort_window_close_minutes"] > data["sort_window_open_minutes"], \
        "a hub whose close is at or before its open is refused"
    assert data["live_planned_package_total"] >= 0
    assert data["ops_run_index"] >= 0
    if data["posture"] == "LOCKDOWN":
        # LOCKDOWN is either the contingency branch or the volume branch
        assert data["contingency_mode"] or data["live_planned_package_total"] >= 0


def assert_package_invariants(data: dict):
    """Consistency the PRD requires between the four state planes and the postures."""
    expected_handling_posture = {
        "NORMAL": "STANDARD",
        "ROUTED_TO_IRREGULAR": "IRREGULAR_LANE",
        "ROUTED_TO_HAZMAT": "HAZMAT_LANE",
        "DIVERTED": "STANDARD",
        "HOLD_AT_HUB": "STANDARD",
    }[data["handling_status"]]
    if data["handling_status"] in ("NORMAL", "ROUTED_TO_IRREGULAR", "ROUTED_TO_HAZMAT"):
        assert data["handling_posture"] == expected_handling_posture, (
            f"handling_posture {data['handling_posture']} disagrees with "
            f"handling_status {data['handling_status']}"
        )

    if data["commitment_status"] in ("REROUTED", "UPGRADED_HELD"):
        assert data["commitment_posture"] == "REROUTE_PENDING"
    elif data["commitment_status"] == "DOWNGRADED":
        assert data["commitment_posture"] == "DOWNGRADE_PENDING"
    else:
        assert data["commitment_posture"] == "COMMITTED_OK"

    if data["assigned_lane_id"] is not None:
        assert data["sort_status"] in ("PRIMARY_SORTED", "SECONDARY_SORTED"), (
            "a package occupies a lane only while it is primary- or secondary-sorted"
        )
    if data["sort_status"] == "UNSORTED":
        assert data["assigned_lane_id"] is None
    if data["rated_weight_grams"] is not None:
        assert data["rated_weight_grams"] % 100 == 0, \
            "rated_weight_grams is rounded to the nearest 100 grams"
        assert data["rated_weight_grams"] >= 2000, \
            "the dimensional minimum of 2000 grams is applied before any comparison"


def assert_load_move_invariants(data: dict):
    """The pinned evaluation order of the move's capacity arithmetic."""
    raw_forward = data["weight_limit_grams"] - data["planned_weight_grams"]
    expected_tier = (
        "UNDER_CAPACITY" if raw_forward > 0
        else "AT_CAPACITY" if raw_forward == 0
        else "RESERVE_TIER"
    )
    assert data["load_plan_tier"] == expected_tier, (
        f"load_plan_tier {data['load_plan_tier']} must be derived from the raw forward "
        f"capacity {raw_forward}, not from the floored {data['forward_capacity_grams']}"
    )
    assert data["forward_capacity_grams"] == max(0, raw_forward), (
        "forward_capacity_grams is the raw forward capacity floored at zero"
    )
    assert data["loaded_weight_grams"] <= data["planned_weight_grams"]


def assert_buildup_invariants(data: dict):
    """The buildup's own band arithmetic."""
    delta = data["rated_weight_grams"] - data["container_limit_grams"]
    expected_tier = (
        "UNDER_CAPACITY" if delta <= 0
        else "AT_CAPACITY" if delta <= 25000
        else "RESERVE_TIER"
    )
    assert data["load_plan_tier"] == expected_tier
    if delta > 25000:
        assert data["status"] == "WEIGHT_BREACH"
    assert data["hazardous_weight_grams"] <= data["rated_weight_grams"]