"""Payload factories -- one per creatable entity, input fields only.

Computed and system-managed fields (``status``, ``resolved_zone_ids``,
``damage_threat``, ``verified_event_count``, timestamps, versions, ...) are never
put into a payload here; the server derives them. Unique-valued fields
(``office_code``, ``zone_code``, channel ``name``, ``employee_code``) default to
counter-generated values so a test can create several of one entity without
colliding, and can always override them explicitly.
"""

import itertools

from .constants import (
    COORDINATION_TIMEOUT_DEFAULT_MINUTES,
    DEFAULT_ISSUE_CLOCK_ISO,
    STANDARD_SURVEYED_AREA_SQ_KM,
    STANDARD_ZONE_LAT_MAX,
    STANDARD_ZONE_LAT_MIN,
    STANDARD_ZONE_LON_MAX,
    STANDARD_ZONE_LON_MIN,
    WEA_ABSOLUTE_MAX_CHARS,
)
from .types import JsonObject, Polygon, ResourceId

_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


def _alpha(n: int) -> str:
    """1 -> A, 2 -> B, ..., 26 -> Z, 27 -> AA (base-26 letter encoding)."""
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


# ---------------------------------------------------------------------------
# Geometry helpers (PRD §3.4: a polygon is {"vertices": [{"lat","lon"}, ...]})
# ---------------------------------------------------------------------------
def square_polygon(
    lat_min: float = STANDARD_ZONE_LAT_MIN,
    lon_min: float = STANDARD_ZONE_LON_MIN,
    lat_max: float = STANDARD_ZONE_LAT_MAX,
    lon_max: float = STANDARD_ZONE_LON_MAX,
) -> Polygon:
    """An axis-aligned rectangle as a 4-vertex convex polygon (counterclockwise
    from the south-west corner). Default is the standard 0.1x0.1-degree cell,
    whose PLANAR area is exactly 123.21 sq km."""
    return {
        "vertices": [
            {"lat": lat_min, "lon": lon_min},
            {"lat": lat_min, "lon": lon_max},
            {"lat": lat_max, "lon": lon_max},
            {"lat": lat_max, "lon": lon_min},
        ]
    }


def triangle_polygon(lat_min: float, lon_min: float, lat_max: float, lon_max: float) -> Polygon:
    """A right triangle on the cell's diagonal (3 vertices, the legal minimum)."""
    return {
        "vertices": [
            {"lat": lat_min, "lon": lon_min},
            {"lat": lat_min, "lon": lon_max},
            {"lat": lat_max, "lon": lon_min},
        ]
    }


# ---------------------------------------------------------------------------
# Configuration entities (PlatformAdmin writes)
# ---------------------------------------------------------------------------
def office_payload(**overrides) -> JsonObject:
    n = _next()
    defaults: JsonObject = {
        "office_code": "K" + _alpha(n)[:3],  # 2-4 letters, e.g. KA, KB, ...
        "name": "Test Office %d" % n,
        "region": "SOUTHERN_PLAINS",
    }
    defaults.update(overrides)
    return defaults


def zone_payload(office_id: ResourceId, **overrides) -> JsonObject:
    n = _next()
    defaults: JsonObject = {
        "zone_code": "Z%s%02d" % (_alpha(n), n % 100),
        "name": "Test Zone %d" % n,
        "office_id": str(office_id),
        "lat_min": STANDARD_ZONE_LAT_MIN,
        "lat_max": STANDARD_ZONE_LAT_MAX,
        "lon_min": STANDARD_ZONE_LON_MIN,
        "lon_max": STANDARD_ZONE_LON_MAX,
        "surveyed_area_sq_km": STANDARD_SURVEYED_AREA_SQ_KM,
        "population_tier": "LOW",
    }
    defaults.update(overrides)
    return defaults


def neighbor_agreement_payload(
    office_a_id: ResourceId,
    office_b_id: ResourceId,
    hazard_types=None,
    **overrides,
) -> JsonObject:
    defaults: JsonObject = {
        "office_a_id": str(office_a_id),
        "office_b_id": str(office_b_id),
        "hazard_types": list(hazard_types) if hazard_types is not None else ["SEVERE_THUNDERSTORM"],
        "coordination_timeout_minutes": COORDINATION_TIMEOUT_DEFAULT_MINUTES,
    }
    defaults.update(overrides)
    return defaults


def alert_channel_payload(**overrides) -> JsonObject:
    n = _next()
    defaults: JsonObject = {
        "name": "CH-%d" % n,
        "channel_type": "EAS",
        "supports_levels": ["WATCH", "WARNING"],
        "max_message_chars": 1800,
    }
    defaults.update(overrides)
    return defaults


def wea_channel_payload(**overrides) -> JsonObject:
    """A WEA channel at the absolute 360-character budget, requiring confirmation."""
    n = _next()
    defaults: JsonObject = {
        "name": "WEA-%d" % n,
        "channel_type": "WEA",
        "supports_levels": ["WARNING"],
        "max_message_chars": WEA_ABSOLUTE_MAX_CHARS,
        "requires_confirmation": True,
    }
    defaults.update(overrides)
    return defaults


def forecaster_payload(office_id: ResourceId, **overrides) -> JsonObject:
    n = _next()
    defaults: JsonObject = {
        "office_id": str(office_id),
        "full_name": "Forecaster %d" % n,
        "employee_code": "EMP-%d" % n,
        "level": "SENIOR",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Storm events (PRD §3.3)
# ---------------------------------------------------------------------------
def storm_event_payload(office_id: ResourceId, hazard_type: str = "SEVERE_THUNDERSTORM", **readings) -> JsonObject:
    """Open a storm; every omitted reading defaults server-side to zero/false."""
    payload: JsonObject = {"office_id": str(office_id), "hazard_type": hazard_type}
    payload.update(readings)
    return payload


def storm_event_update_payload(expected_storm_event_version: int, **readings) -> JsonObject:
    """An OCC-guarded readings update (PRD §2.6)."""
    payload: JsonObject = {"expected_storm_event_version": expected_storm_event_version}
    payload.update(readings)
    return payload


# ---------------------------------------------------------------------------
# Products (PRD §3.4)
# ---------------------------------------------------------------------------
def product_payload(
    product_level: str,
    hazard_type: str,
    issuing_office_id: ResourceId,
    expires_at: str,
    **overrides,
) -> JsonObject:
    defaults: JsonObject = {
        "product_level": product_level,
        "hazard_type": hazard_type,
        "issuing_office_id": str(issuing_office_id),
        "expires_at": expires_at,
    }
    defaults.update(overrides)
    return defaults


def warning_polygon_payload(
    issuing_office_id: ResourceId,
    storm_event_id: ResourceId,
    hazard_type: str = "SEVERE_THUNDERSTORM",
    polygon: Polygon = None,
    expires_at: str = "2026-09-01T10:45:00Z",
    **overrides,
) -> JsonObject:
    """A WARNING draft over a polygon; 45 minutes from the canonical 10:00 issue
    instant, inside the severe-thunderstorm 15..120 duration range (PRD §3.5)."""
    payload = product_payload(
        "WARNING",
        hazard_type,
        issuing_office_id,
        expires_at,
        storm_event_id=str(storm_event_id),
        polygon=polygon if polygon is not None else square_polygon(),
    )
    payload.update(overrides)
    return payload


def zone_product_payload(
    product_level: str,
    issuing_office_id: ResourceId,
    zone_ids,
    hazard_type: str = "WINTER_STORM",
    effective_from: str = "2026-09-02T00:00:00Z",
    expires_at: str = "2026-09-02T12:00:00Z",
    **overrides,
) -> JsonObject:
    """A zone-based OUTLOOK/WATCH (or zone-based ADVISORY) draft. The default
    window sits a full day after the logical-clock startup instant, so it is
    comfortably in the future (PRD §3.4: an earlier onset is ERR_EFFECTIVE_IN_PAST)."""
    payload = product_payload(
        product_level,
        hazard_type,
        issuing_office_id,
        expires_at,
        zone_ids=[str(z) for z in zone_ids],
        effective_from=effective_from,
    )
    payload.update(overrides)
    return payload


def issue_payload(expected_product_version: int, coordination_override: bool = None) -> JsonObject:
    """An OCC-guarded issue call (PRD §2.6); ``coordination_override`` is only
    ever sent when explicitly requested -- it is MIC-only (PRD §3.5)."""
    payload: JsonObject = {"expected_product_version": expected_product_version}
    if coordination_override is not None:
        payload["coordination_override"] = coordination_override
    return payload


def coordination_respond_payload(outcome: str) -> JsonObject:
    return {"outcome": outcome}


# ---------------------------------------------------------------------------
# Verification (PRD §3.8)
# ---------------------------------------------------------------------------
def verification_event_payload(
    zone_id: ResourceId,
    hazard_type: str,
    observed_at: str,
    location_lat: float,
    location_lon: float,
    magnitude: str,
    **overrides,
) -> JsonObject:
    payload: JsonObject = {
        "zone_id": str(zone_id),
        "hazard_type": hazard_type,
        "observed_at": observed_at,
        "location_lat": location_lat,
        "location_lon": location_lon,
        "magnitude": magnitude,
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(outcome: str) -> JsonObject:
    return {"outcome": outcome}


def verification_statistic_payload(
    office_id: ResourceId,
    hazard_type: str,
    period_start: str = "2026-09-01T00:00:00Z",
    period_end: str = "2026-09-02T00:00:00Z",
    matching_variant: str = "POLYGON_STRICT",
    **overrides,
) -> JsonObject:
    payload: JsonObject = {
        "office_id": str(office_id),
        "hazard_type": hazard_type,
        "period_start": period_start,
        "period_end": period_end,
        "matching_variant": matching_variant,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Emergency actions (PRD §3.9)
# ---------------------------------------------------------------------------
def emergency_action_payload(
    zone_id: ResourceId,
    product_id: ResourceId,
    action_type: str = "EVACUATION",
    effective_from: str = "2026-09-01T10:00:00Z",
    effective_until: str = "2026-09-01T11:00:00Z",
    **overrides,
) -> JsonObject:
    payload: JsonObject = {
        "zone_id": str(zone_id),
        "product_id": str(product_id),
        "action_type": action_type,
        "effective_from": effective_from,
        "effective_until": effective_until,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Platform capabilities (unprefixed endpoints, PRD §2.4)
# ---------------------------------------------------------------------------
def settle_payload(record_id: ResourceId, outcome: str) -> JsonObject:
    return {"record_id": str(record_id), "outcome": outcome}


__all__ = [
    "square_polygon",
    "triangle_polygon",
    "office_payload",
    "zone_payload",
    "neighbor_agreement_payload",
    "alert_channel_payload",
    "wea_channel_payload",
    "forecaster_payload",
    "storm_event_payload",
    "storm_event_update_payload",
    "product_payload",
    "warning_polygon_payload",
    "zone_product_payload",
    "issue_payload",
    "coordination_respond_payload",
    "verification_event_payload",
    "adjudicate_payload",
    "verification_statistic_payload",
    "emergency_action_payload",
    "settle_payload",
    "DEFAULT_ISSUE_CLOCK_ISO",
]
