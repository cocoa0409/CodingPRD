"""Payload factories — one per entity, input fields only.

Each factory returns the request body for the corresponding create endpoint
with sensible defaults; tests override the values they exercise.
"""

from typing import Any, Dict, List, Optional

_counter = {"n": 0}


def _next(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def create_athlete_payload(**overrides) -> Dict[str, Any]:
    suffix = _next("ath")
    defaults = {
        "email": f"{suffix}@example.com",
        "display_name": f"Athlete {suffix}",
        "home_lat": 37.0,
        "home_lng": -122.0,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(**overrides) -> Dict[str, Any]:
    defaults = {
        "plan": "SUMMIT_MONTHLY",
        "started_at": "2026-08-01T00:00:00Z",
        "expires_at": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_privacy_zone_payload(**overrides) -> Dict[str, Any]:
    defaults = {
        "center_lat": 37.0,
        "center_lng": -122.0,
        "radius_m": 500,
    }
    defaults.update(overrides)
    return defaults


def default_track_points() -> List[Dict[str, Any]]:
    return [
        {"lat": 37.50, "lng": -122.50, "t_offset_s": 0},
        {"lat": 37.51, "lng": -122.50, "t_offset_s": 600},
    ]


def create_activity_payload(**overrides) -> Dict[str, Any]:
    suffix = _next("act")
    defaults = {
        "device_source": "garmin-edge",
        "sport_type": "RUN",
        "started_at": "2026-09-01T06:00:00Z",
        "duration_s": 600,
        "distance_m": 2000,
        "track_points": default_track_points(),
        "start_lat": 37.50,
        "start_lng": -122.50,
        "end_lat": 37.51,
        "end_lng": -122.50,
        "idempotency_key": f"idem-{suffix}",
    }
    defaults.update(overrides)
    return defaults


def create_segment_payload(creator_id: str, **overrides) -> Dict[str, Any]:
    suffix = _next("seg")
    defaults = {
        "creator_id": creator_id,
        "name": f"Segment {suffix}",
        "sport_type": "RUN",
        "start_lat": 37.60,
        "start_lng": -122.60,
        "end_lat": 37.61,
        "end_lng": -122.60,
        "distance_m": 1000,
        "city": "Testville",
    }
    defaults.update(overrides)
    return defaults


def create_flag_payload(reporter_id: str, **overrides) -> Dict[str, Any]:
    defaults = {
        "reporter_id": reporter_id,
        "reason": "IMPOSSIBLE_TIME",
    }
    defaults.update(overrides)
    return defaults


def create_club_payload(owner_id: str, **overrides) -> Dict[str, Any]:
    suffix = _next("club")
    defaults = {
        "owner_id": owner_id,
        "name": f"Club {suffix}",
        "sport_type": "RUN",
        "join_policy": "OPEN",
    }
    defaults.update(overrides)
    return defaults


def create_challenge_payload(**overrides) -> Dict[str, Any]:
    suffix = _next("ch")
    defaults = {
        "name": f"Challenge {suffix}",
        "goal_type": "DISTANCE_M",
        "goal_target": 50000,
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
        "join_mode": "OPEN",
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(segment_id: str, **overrides) -> Dict[str, Any]:
    suffix = _next("ev")
    defaults = {
        "name": f"Event {suffix}",
        "segment_id": segment_id,
        "scheduled_at": "2026-09-06T09:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_safety_contact_payload(**overrides) -> Dict[str, Any]:
    suffix = _next("sos")
    defaults = {
        "contact_email": f"{suffix}@example.com",
        "label": "Emergency",
    }
    defaults.update(overrides)
    return defaults


def create_route_plan_payload(**overrides) -> Dict[str, Any]:
    suffix = _next("plan")
    defaults = {
        "name": f"Plan {suffix}",
        "waypoints": [
            {"lat": 37.0, "lng": -122.0},
            {"lat": 37.1, "lng": -122.0},
        ],
        "distance_m": 10000,
        "week_start": "2026-09-07",
    }
    defaults.update(overrides)
    return defaults
