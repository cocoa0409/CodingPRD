"""Payload factories for the mountain operations API.

Every factory returns a valid, minimal-but-complete payload and accepts
keyword overrides, so a test states only the field its rule is about. Numeric
fields are emitted as JSON numbers, never as strings.
"""

from typing import Any, Dict, List, Optional

from .constants import INITIAL_CLOCK

# ─── Canonical season shape ───────────────────────────

def energy_windows_full_day() -> List[Dict[str, Any]]:
    """A four-entry price schedule that tiles the whole day exactly: the first
    starts at hour 0, the last ends at hour 24, consecutive entries touch."""
    return [
        {
            "code": "OFF_1",
            "start_hour_utc": 0,
            "end_hour_utc": 6,
            "price_usd_per_kwh": 0.062,
            "tier": "OFF_PEAK",
        },
        {
            "code": "MID_1",
            "start_hour_utc": 6,
            "end_hour_utc": 9,
            "price_usd_per_kwh": 0.113,
            "tier": "MID_PEAK",
        },
        {
            "code": "ON_1",
            "start_hour_utc": 9,
            "end_hour_utc": 21,
            "price_usd_per_kwh": 0.187,
            "tier": "ON_PEAK",
        },
        {
            "code": "MID_2",
            "start_hour_utc": 21,
            "end_hour_utc": 24,
            "price_usd_per_kwh": 0.113,
            "tier": "MID_PEAK",
        },
    ]


def energy_windows_single_flat(price_usd_per_kwh: float = 0.100) -> List[Dict[str, Any]]:
    """A one-entry schedule covering hour 0 up to hour 24 at a flat rate."""
    return [
        {
            "code": "FLAT",
            "start_hour_utc": 0,
            "end_hour_utc": 24,
            "price_usd_per_kwh": price_usd_per_kwh,
            "tier": "OFF_PEAK",
        }
    ]


def season_payload(**overrides: Any) -> Dict[str, Any]:
    """A season configuration carrying the water right, the plant ceiling, the
    energy intensity and the price schedule."""
    payload: Dict[str, Any] = {
        "season_label": "2026-27",
        "water_right_seasonal_af": 250.000,
        "plant_max_gpm": 6000,
        "snowmaking_kwh_per_af": 620.0,
        "energy_windows": energy_windows_full_day(),
    }
    payload.update(overrides)
    return payload


# ─── Lifts and staffing ───────────────────────────────

def lift_payload(season_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "lift_code": "L1",
        "name": "Summit Express",
        "lift_type": "DETACHABLE",
        "wind_hold_threshold_mph": 35.0,
        "hourly_capacity_pph": 1800,
    }
    payload.update(overrides)
    return payload


def inspection_payload(result: str = "PASS", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"result": result}
    payload.update(overrides)
    return payload


def service_status_payload(target_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_status": target_status}
    payload.update(overrides)
    return payload


def staff_assignment_payload(lift_id: str, **overrides: Any) -> Dict[str, Any]:
    """An operator assigned to a lift role for a shift bounded by shift_start
    inclusive and shift_end exclusive."""
    payload: Dict[str, Any] = {
        "lift_id": lift_id,
        "operator_code": "OP-1",
        "role_on_lift": "TOP_OP",
        "shift_start": "2026-08-01T00:00:00Z",
        "shift_end": "2026-08-01T16:00:00Z",
    }
    payload.update(overrides)
    return payload


# ─── Terrain areas, readings and parks ────────────────

def terrain_area_payload(
    season_id: str, serving_lift_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "serving_lift_id": serving_lift_id,
        "trail_code": "T1",
        "name": "Lower Bowl",
        "terrain_class": "BLUE",
        "acres": 18.0,
        "min_open_base_depth_in": 30,
    }
    payload.update(overrides)
    return payload


def snow_depth_reading_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "stake_code": "S1",
        "depth_in": 40.0,
        "measured_at": INITIAL_CLOCK,
    }
    payload.update(overrides)
    return payload


def park_feature(feature_type: str, size_class: str) -> Dict[str, str]:
    return {"feature_type": feature_type, "size_class": size_class}


def park_build_payload(
    features: Optional[List[Dict[str, str]]] = None, **overrides: Any
) -> Dict[str, Any]:
    """A park build declaring its feature set. An empty features array
    submitted from PARK_INSPECTED is how a park is torn down."""
    payload: Dict[str, Any] = {
        "features": features
        if features is not None
        else [
            park_feature("JUMP", "L"),
            park_feature("JUMP", "M"),
            park_feature("RAIL", "M"),
            park_feature("RAIL", "S"),
            park_feature("JIB", "S"),
            park_feature("HALFPIPE", "S"),
        ]
    }
    payload.update(overrides)
    return payload


def park_inspection_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def opening_decision_payload(decision: str = "OPEN", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── Snowmaking ───────────────────────────────────────

def pump_house_payload(season_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "pump_house_code": "PH1",
        "name": "Base Pump House",
        "max_gpm": 2400,
        "gun_count": 40,
    }
    payload.update(overrides)
    return payload


def pump_house_status_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": status}
    payload.update(overrides)
    return payload


def session_payload(
    terrain_area_id: str,
    pump_house_id: str,
    expected_terrain_area_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """A snowmaking session over a half-open window, carrying the terrain area
    version the caller observed."""
    payload: Dict[str, Any] = {
        "terrain_area_id": terrain_area_id,
        "pump_house_id": pump_house_id,
        "window_start": "2026-08-01T05:00:00Z",
        "window_end": "2026-08-01T12:00:00Z",
        "gun_count": 30,
        "gpm": 1200,
        "expected_terrain_area_version": expected_terrain_area_version,
    }
    payload.update(overrides)
    return payload


def session_status_payload(target_state: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"target_state": target_state}
    payload.update(overrides)
    return payload


# ─── Grooming ─────────────────────────────────────────

def grooming_task_payload(terrain_area_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "terrain_area_id": terrain_area_id,
        "cat_route_code": "R1",
        "sequence_index": 1,
        "snowcat_unit_code": "CAT-1",
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-01T04:00:00Z",
    }
    payload.update(overrides)
    return payload


def grooming_completion_payload(passes_completed: int = 20, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"passes_completed": passes_completed}
    payload.update(overrides)
    return payload


# ─── Patrol ───────────────────────────────────────────

def patroller_payload(season_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "patroller_code": "P1",
        "full_name": "Avery Nordstrom",
        "cert_level": "EMT",
        "on_duty": True,
    }
    payload.update(overrides)
    return payload


def duty_payload(on_duty: bool, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"on_duty": on_duty}
    payload.update(overrides)
    return payload


def mission_payload(terrain_area_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "terrain_area_id": terrain_area_id,
        "route_code": "AV-1",
        "method": "EXPLOSIVE",
        "hazard_rating_pre": "CONSIDERABLE",
        "planned_charges": 4,
    }
    payload.update(overrides)
    return payload


def mission_execute_payload(charges_used: int = 4, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"charges_used": charges_used}
    payload.update(overrides)
    return payload


def mission_clear_payload(hazard_rating_post: str = "LOW", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"hazard_rating_post": hazard_rating_post}
    payload.update(overrides)
    return payload


def incident_payload(terrain_area_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "terrain_area_id": terrain_area_id,
        "reporter_code": "RPT-1",
        "severity": "MODERATE",
    }
    payload.update(overrides)
    return payload


def incident_dispatch_payload(patroller_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"patroller_id": patroller_id}
    payload.update(overrides)
    return payload


def incident_transport_payload(transport_mode: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"transport_mode": transport_mode}
    payload.update(overrides)
    return payload


def incident_close_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition}
    payload.update(overrides)
    return payload


# ─── Operating day and admission ──────────────────────

def day_plan_payload(season_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "operating_date": "2026-08-01",
        "parking_stalls_total": 500,
    }
    payload.update(overrides)
    return payload


def weather_payload(
    wind_speed_mph: float = 10.0, wet_bulb_f: float = 22.0, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "wind_speed_mph": wind_speed_mph,
        "wet_bulb_f": wet_bulb_f,
    }
    payload.update(overrides)
    return payload


def close_day_payload(season_final: bool = False, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"season_final": season_final}
    payload.update(overrides)
    return payload


def reservation_payload(
    day_plan_id: str, expected_day_plan_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "day_plan_id": day_plan_id,
        "party_code": "PTY-1",
        "pass_type": "DAY_TICKET",
        "party_size": 4,
        "vehicle_count": 1,
        "expected_day_plan_version": expected_day_plan_version,
    }
    payload.update(overrides)
    return payload
