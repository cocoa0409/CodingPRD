"""Entity assertions and conserved-ledger checkers for the Broadcast Operations API."""

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .types import (
    ACTIVE_BOOKING_STATUSES,
    AirStatus,
    BookingRole,
    BookingStatus,
    CameraPositionType,
    CrewCallStatus,
    CrewPosition,
    EmploymentType,
    EventTier,
    FeedKind,
    FeedStatus,
    IncidentKind,
    IncidentSeverity,
    PathType,
    PrepStatus,
    ProductionStatus,
    RedundancyClass,
    RehearsalStatus,
    SignalStatus,
    SurveyStatus,
    SystemKind,
    TruckStatus,
    VenueRoofType,
)

PAGINATION_META_FIELDS = ("limit", "offset", "total_count", "has_more")


# ---------------------------------------------------------------------------
# Structural helpers
# ---------------------------------------------------------------------------
def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_identity_fields(data: dict):
    """Every resource carries a bare-UUID id and a three-digit ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')!r}"
    created_at = data.get("created_at")
    assert is_iso8601_timestamp(created_at or ""), (
        f"created_at must be an ISO 8601 UTC instant: {created_at!r}"
    )
    assert created_at.endswith("Z") and "." in created_at, (
        f"created_at must render three fractional-second digits: {created_at!r}"
    )
    assert len(created_at.split(".")[1]) == 4, (
        f"created_at must render exactly three fractional-second digits: {created_at!r}"
    )


def assert_versioned_row(data: dict, expected_version=None):
    """A row that carries updated_at and a version integer starting at 1."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC instant: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_append_only_row(data: dict):
    """An append-only log row: id and created_at only, no updated_at, no version."""
    assert_identity_fields(data)
    assert "updated_at" not in data, (
        "append-only rows carry no updated_at field"
    )
    assert "version" not in data, "append-only rows carry no version field"


def assert_instant_equals(actual, expected, field="timestamp"):
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {field} == {expected}, got {actual}"
    )


def assert_two_decimal_places(value, field="value"):
    assert isinstance(value, (int, float)), f"{field} must be numeric, got {value!r}"
    assert round(float(value), 2) == pytest.approx(float(value)), (
        f"{field} must be carried to two decimal places, got {value}"
    )


def response_meta(response) -> dict:
    """The meta object of any response, for pagination-field assertions."""
    return response.json()["meta"]


def assert_no_pagination_fields(response):
    """Single-resource reads carry none of the four pagination fields."""
    meta = response_meta(response)
    for field in PAGINATION_META_FIELDS:
        assert field not in meta, (
            f"single-resource read must not carry meta.{field}"
        )


def assert_pagination_meta(meta, limit=None, offset=None, total_count=None,
                           has_more=None):
    if limit is not None:
        assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"Expected total_count {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"Expected has_more {has_more}, got {meta['has_more']}"
        )


def assert_created_at_ascending(rows):
    """List endpoints return rows ordered by created_at ascending."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows are not ordered by created_at ascending: {stamps}"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_truck(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["truck_code"], str) and data["truck_code"]
    assert data["tier_rating"] in _values(EventTier)
    assert isinstance(data["camera_channel_capacity"], int)
    assert data["camera_channel_capacity"] >= 1
    assert isinstance(data["power_draw_amps"], int) and data["power_draw_amps"] >= 0
    assert isinstance(data["home_base_code"], str) and data["home_base_code"]
    assert isinstance(data["engine_hours_since_service"], int)
    assert data["engine_hours_since_service"] >= 0
    assert isinstance(data["service_interval_hours"], int)
    assert data["service_interval_hours"] >= 1
    assert data["hours_to_service"] == (
        data["service_interval_hours"] - data["engine_hours_since_service"]
    ), "hours_to_service is service_interval_hours less engine_hours_since_service"
    assert data["status"] in _values(TruckStatus)
    if data.get("last_service_completed_at") is not None:
        assert is_iso8601_timestamp(data["last_service_completed_at"])


def assert_production(data: dict):
    assert_versioned_row(data)
    assert data["event_tier"] in _values(EventTier)
    assert isinstance(data["league_code"], str) and data["league_code"]
    assert isinstance(data["venue_name"], str) and data["venue_name"]
    assert isinstance(data["venue_power_capacity_amps"], int)
    assert data["venue_power_capacity_amps"] >= 1
    assert data["venue_roof_type"] in _values(VenueRoofType)
    for field in ("venue_curfew_utc", "scheduled_start_utc", "scheduled_end_utc"):
        assert is_iso8601_timestamp(data[field]), f"{field} must be an ISO 8601 instant"
    assert canonical_instant(data["scheduled_end_utc"]) > canonical_instant(
        data["scheduled_start_utc"]
    ), "scheduled_end_utc must be strictly later than scheduled_start_utc"
    assert canonical_instant(data["venue_curfew_utc"]) > canonical_instant(
        data["scheduled_end_utc"]
    ), "venue_curfew_utc must be strictly later than scheduled_end_utc"
    assert data["status"] in _values(ProductionStatus)
    assert isinstance(data["labor_budget_total_cents"], int)
    assert isinstance(data["labor_committed_cents"], int)
    assert isinstance(data["labor_available_cents"], int)
    assert isinstance(data["required_crew_positions"], int)
    assert isinstance(data["required_validated_preps"], int)
    assert_two_decimal_places(data["readiness_score_preflight"], "readiness_score_preflight")
    assert_two_decimal_places(data["readiness_score_certified"], "readiness_score_certified")
    assert 0 <= float(data["readiness_score_preflight"]) <= 100
    assert 0 <= float(data["readiness_score_certified"]) <= 100
    assert_labor_ledger_conserved(data)


def assert_venue_survey(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["production_id"])
    assert isinstance(data["surveyor_name"], str) and data["surveyor_name"]
    assert isinstance(data["fiber_drops_required"], int)
    assert data["fiber_drops_required"] >= 0
    assert data["status"] in _values(SurveyStatus)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["camera_position_count"], int)
    assert isinstance(data["total_cable_run_feet"], int)
    assert isinstance(data["total_power_draw_amps"], int)
    assert isinstance(data["power_headroom_amps"], int)
    assert_two_decimal_places(data["total_signal_loss_db"], "total_signal_loss_db")


def assert_camera_position(data: dict):
    """A camera position is append-only and carries the two derived plot values."""
    assert_append_only_row(data)
    assert is_valid_uuid(data["survey_id"])
    assert isinstance(data["label"], str) and data["label"]
    assert data["position_type"] in _values(CameraPositionType)
    assert isinstance(data["cable_run_feet"], int) and data["cable_run_feet"] >= 1
    assert isinstance(data["power_draw_amps"], int) and data["power_draw_amps"] >= 0
    assert_two_decimal_places(data["signal_loss_db"], "signal_loss_db")
    assert isinstance(data["requires_operator"], bool)
    assert data["requires_operator"] is (data["position_type"] != "ROBO"), (
        "requires_operator is true for HARD, HANDHELD and AERIAL and false for ROBO"
    )


def assert_transmission_path(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["path_code"], str) and data["path_code"]
    assert data["path_type"] in _values(PathType)
    assert isinstance(data["carrier_code"], str) and data["carrier_code"]
    assert isinstance(data["capacity_mbps"], int) and data["capacity_mbps"] >= 1
    assert isinstance(data["guard_band_minutes"], int)
    assert data["guard_band_minutes"] >= 0
    assert data["redundancy_class"] in _values(RedundancyClass)
    assert isinstance(data["committed_mbps_total"], int)
    assert data["committed_mbps_total"] >= 0
    assert isinstance(data["active_booking_count"], int)
    assert data["active_booking_count"] >= 0


def assert_path_booking(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["path_id"])
    assert data["booking_role"] in _values(BookingRole)
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert canonical_instant(data["window_end_utc"]) > canonical_instant(
        data["window_start_utc"]
    ), "an end instant at or before the start is not a booking window"
    assert isinstance(data["requested_mbps"], int) and data["requested_mbps"] >= 1
    assert data["status"] in _values(BookingStatus)
    assert isinstance(data["test_attempt_count"], int)
    assert 0 <= data["test_attempt_count"] <= 3


def assert_crew_member(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["position"] in _values(CrewPosition)
    assert data["employment_type"] in _values(EmploymentType)
    assert isinstance(data["union_local"], str) and data["union_local"]
    assert isinstance(data["certified_tiers"], list) and data["certified_tiers"]
    for tier in data["certified_tiers"]:
        assert tier in _values(EventTier)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 1
    assert isinstance(data["home_base_code"], str) and data["home_base_code"]
    assert isinstance(data["lifetime_meal_penalty_units"], int)
    assert data["lifetime_meal_penalty_units"] >= 0


def assert_crew_call(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["crew_member_id"])
    assert is_iso8601_timestamp(data["call_time_utc"])
    assert is_iso8601_timestamp(data["scheduled_release_utc"])
    assert canonical_instant(data["scheduled_release_utc"]) > canonical_instant(
        data["call_time_utc"]
    ), "scheduled_release_utc must be later than call_time_utc"
    assert data["status"] in _values(CrewCallStatus)
    assert isinstance(data["effective_rate_cents"], int)
    assert data["effective_rate_cents"] >= 1
    assert isinstance(data["provisional_total_cents"], int)
    assert data["provisional_total_cents"] >= 0
    assert isinstance(data["meal_penalty_units"], int)
    assert 0 <= data["meal_penalty_units"] <= 4


def assert_data_feed(data: dict):
    assert_versioned_row(data)
    assert isinstance(data["provider_code"], str) and data["provider_code"]
    assert data["feed_kind"] in _values(FeedKind)
    assert isinstance(data["latency_ms"], int) and data["latency_ms"] >= 0
    assert is_iso8601_timestamp(data["contract_expiry_utc"])
    assert isinstance(data["max_concurrent_consumers"], int)
    assert data["max_concurrent_consumers"] >= 1
    assert data["status"] in _values(FeedStatus)
    assert isinstance(data["active_consumer_count"], int)
    assert data["active_consumer_count"] >= 0


def assert_system_prep(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["production_id"])
    assert is_valid_uuid(data["data_feed_id"])
    assert data["system_kind"] in _values(SystemKind)
    assert data["status"] in _values(PrepStatus)
    if data["system_kind"] == "REPLAY":
        assert isinstance(data["replay_channel_count"], int)
        assert data["replay_channel_count"] >= 1
    if data["status"] != "VALIDATED":
        assert data.get("feed_validated_at") is None, (
            "feed_validated_at is stamped only when the preparation is validated"
        )


def assert_rehearsal(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["production_id"])
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert data["status"] in _values(RehearsalStatus)


def assert_show_execution(data: dict):
    assert_versioned_row(data)
    assert is_valid_uuid(data["production_id"])
    assert data["air_status"] in _values(AirStatus)
    assert data["signal_status"] in _values(SignalStatus)
    assert isinstance(data["readiness_hold"], bool)
    for field in (
        "weather_hold_minutes",
        "extended_play_minutes",
        "technical_downtime_minutes",
        "air_minutes_total",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative whole number of minutes"
        )
    if data.get("on_air_at_utc") is None or data.get("off_air_at_utc") is None:
        assert data["air_minutes_total"] == 0, (
            "air_minutes_total reads 0 while either air instant is null"
        )


def assert_incident(data: dict):
    """An incident is append-only and folded into exactly one accumulator."""
    assert_append_only_row(data)
    assert is_valid_uuid(data["show_execution_id"])
    assert data["kind"] in _values(IncidentKind)
    assert is_iso8601_timestamp(data["started_at_utc"])
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 1
    assert data["severity"] in _values(IncidentSeverity)


# ---------------------------------------------------------------------------
# Conserved ledgers
# ---------------------------------------------------------------------------
def assert_labor_ledger_conserved(production: dict):
    """labor_budget_total_cents always equals committed plus available."""
    total = production["labor_budget_total_cents"]
    committed = production["labor_committed_cents"]
    available = production["labor_available_cents"]
    assert committed + available == total, (
        f"labor ledger broken: {committed} + {available} != {total}"
    )


def assert_labor_ledger(production: dict, committed: int, available: int):
    assert production["labor_committed_cents"] == committed, (
        f"Expected labor_committed_cents {committed}, "
        f"got {production['labor_committed_cents']}"
    )
    assert production["labor_available_cents"] == available, (
        f"Expected labor_available_cents {available}, "
        f"got {production['labor_available_cents']}"
    )
    assert_labor_ledger_conserved(production)


def assert_path_ledger(path: dict, committed_mbps_total: int, active_booking_count: int):
    assert path["committed_mbps_total"] == committed_mbps_total, (
        f"Expected committed_mbps_total {committed_mbps_total}, "
        f"got {path['committed_mbps_total']}"
    )
    assert path["active_booking_count"] == active_booking_count, (
        f"Expected active_booking_count {active_booking_count}, "
        f"got {path['active_booking_count']}"
    )


def assert_path_ledger_matches_bookings(path: dict, bookings: list):
    """committed_mbps_total is the sum of requested_mbps over the active statuses."""
    active = [b for b in bookings if b["status"] in ACTIVE_BOOKING_STATUSES]
    expected_total = sum(b["requested_mbps"] for b in active)
    assert path["committed_mbps_total"] == expected_total, (
        f"committed_mbps_total {path['committed_mbps_total']} != "
        f"sum over active bookings {expected_total}"
    )
    assert path["active_booking_count"] == len(active), (
        f"active_booking_count {path['active_booking_count']} != {len(active)}"
    )


def assert_readiness(production: dict, preflight=None, certified=None):
    if preflight is not None:
        assert float(production["readiness_score_preflight"]) == pytest.approx(
            preflight, abs=0.005
        ), (
            f"Expected readiness_score_preflight {preflight}, "
            f"got {production['readiness_score_preflight']}"
        )
    if certified is not None:
        assert float(production["readiness_score_certified"]) == pytest.approx(
            certified, abs=0.005
        ), (
            f"Expected readiness_score_certified {certified}, "
            f"got {production['readiness_score_certified']}"
        )


def assert_status(data: dict, expected: str, label="status", field="status"):
    assert data[field] == expected, (
        f"Expected {label} {expected}, got {data[field]}"
    )
