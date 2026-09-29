"""Payload factories: one per creatable resource, input fields only.

Money is always an integer number of cents and every datetime is a full ISO 8601
instant, exactly as the PRD types them.
"""

from .constants import (
    AIR_CLOCK,
    BOOKING_WINDOW_END,
    BOOKING_WINDOW_START,
    CALL_SCHEDULED_RELEASE,
    CALL_TIME,
    CANONICAL_EVENT,
    REHEARSAL_START,
    STAFF_HOURLY_RATE_CENTS,
    TEST_WINDOW_END,
    TEST_WINDOW_START,
)


def create_production_payload(**overrides) -> dict:
    """The canonical TIER_3 remote out of Riverside Arena."""
    payload = dict(CANONICAL_EVENT)
    payload.update(overrides)
    return payload


def create_truck_payload(**overrides) -> dict:
    payload = {
        "truck_code": "TRK-01",
        "tier_rating": "TIER_3",
        "camera_channel_capacity": 4,
        "power_draw_amps": 60,
        "home_base_code": "SEA",
    }
    payload.update(overrides)
    return payload


def create_transmission_path_payload(**overrides) -> dict:
    payload = {
        "path_code": "FIB-01",
        "path_type": "FIBER",
        "carrier_code": "LUMEN",
        "capacity_mbps": 300,
        "redundancy_class": "PRIMARY_ELIGIBLE",
    }
    payload.update(overrides)
    return payload


def create_satellite_path_payload(**overrides) -> dict:
    payload = {
        "path_code": "SAT-1",
        "path_type": "SATELLITE",
        "carrier_code": "TELE1",
        "capacity_mbps": 300,
        "guard_band_minutes": 10,
        "redundancy_class": "PRIMARY_ELIGIBLE",
    }
    payload.update(overrides)
    return payload


def create_crew_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dana Reyes",
        "position": "TD",
        "employment_type": "STAFF",
        "union_local": "L600",
        "certified_tiers": ["TIER_3"],
        "hourly_rate_cents": STAFF_HOURLY_RATE_CENTS,
        "home_base_code": "SEA",
    }
    payload.update(overrides)
    return payload


def create_data_feed_payload(**overrides) -> dict:
    payload = {
        "provider_code": "STATSCO",
        "feed_kind": "LIVE_STATS",
        "latency_ms": 120,
        "contract_expiry_utc": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_venue_survey_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "surveyor_name": "R. Ito",
        "fiber_drops_required": 2,
    }
    payload.update(overrides)
    return payload


def create_camera_position_payload(**overrides) -> dict:
    payload = {
        "label": "HIGH_HOME",
        "position_type": "HARD",
        "cable_run_feet": 150,
        "power_draw_amps": 20,
    }
    payload.update(overrides)
    return payload


def create_path_booking_payload(
    production_id, path_id, expected_production_version, **overrides
) -> dict:
    payload = {
        "production_id": production_id,
        "path_id": path_id,
        "booking_role": "PRIMARY",
        "window_start_utc": BOOKING_WINDOW_START,
        "window_end_utc": BOOKING_WINDOW_END,
        "requested_mbps": 200,
        "expected_production_version": expected_production_version,
    }
    payload.update(overrides)
    return payload


def schedule_path_test_payload(**overrides) -> dict:
    payload = {
        "test_window_start_utc": TEST_WINDOW_START,
        "test_window_end_utc": TEST_WINDOW_END,
    }
    payload.update(overrides)
    return payload


def path_test_result_payload(outcome="PASS", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_crew_call_payload(
    production_id, crew_member_id, expected_production_version, **overrides
) -> dict:
    payload = {
        "production_id": production_id,
        "crew_member_id": crew_member_id,
        "call_time_utc": CALL_TIME,
        "scheduled_release_utc": CALL_SCHEDULED_RELEASE,
        "expected_production_version": expected_production_version,
    }
    payload.update(overrides)
    return payload


def crew_call_response_payload(decision="ACCEPT") -> dict:
    return {"decision": decision}


def release_crew_call_payload(actual_release_utc, meal_break_start_utc=None) -> dict:
    payload = {"actual_release_utc": actual_release_utc}
    if meal_break_start_utc is not None:
        payload["meal_break_start_utc"] = meal_break_start_utc
    return payload


def create_system_prep_payload(production_id, data_feed_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "data_feed_id": data_feed_id,
        "system_kind": "GRAPHICS",
    }
    payload.update(overrides)
    return payload


def create_rehearsal_payload(production_id, **overrides) -> dict:
    payload = {
        "production_id": production_id,
        "scheduled_start_utc": REHEARSAL_START,
    }
    payload.update(overrides)
    return payload


def rehearsal_outcome_payload(outcome="COMPLETED", **overrides) -> dict:
    payload = {
        "outcome": outcome,
        "camera_blocking_positions_cleared": 2,
        "venue_signoff": True,
        "league_ops_signoff": True,
    }
    payload.update(overrides)
    return payload


def create_show_execution_payload(production_id, **overrides) -> dict:
    payload = {"production_id": production_id}
    payload.update(overrides)
    return payload


def create_incident_payload(**overrides) -> dict:
    payload = {
        "kind": "WEATHER_HOLD",
        "started_at_utc": AIR_CLOCK,
        "duration_minutes": 5,
        "severity": "MINOR",
    }
    payload.update(overrides)
    return payload


def truck_assignment_payload(truck_id, expected_production_version) -> dict:
    return {
        "truck_id": truck_id,
        "expected_production_version": expected_production_version,
    }


def survey_review_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload
