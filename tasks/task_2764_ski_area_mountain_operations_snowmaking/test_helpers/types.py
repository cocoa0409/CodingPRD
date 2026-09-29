"""Typed shapes for request payloads and response rows of the mountain
operations API. These exist so payload construction stays legible and so a
mistyped field name is visible at the call site rather than in a 400.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ─── Aliases ──────────────────────────────────────────
Json = Dict[str, Any]
Headers = Dict[str, str]
EntityId = str
Instant = str  # ISO 8601 UTC with three fractional digits
CalendarDate = str  # YYYY-MM-DD


class EnergyWindow(TypedDict, total=False):
    """One entry of a season's daily-recurring price schedule."""

    code: str
    start_hour_utc: int
    end_hour_utc: int
    price_usd_per_kwh: float
    tier: str


class SeasonPayload(TypedDict, total=False):
    season_label: str
    water_right_seasonal_af: float
    plant_max_gpm: int
    snowmaking_kwh_per_af: float
    energy_windows: List[EnergyWindow]
    base_depth_policy: str
    min_patrollers_per_open_area: int
    groom_freshness_hours: int


class LiftPayload(TypedDict, total=False):
    season_id: EntityId
    lift_code: str
    name: str
    lift_type: str
    wind_hold_threshold_mph: float
    hourly_capacity_pph: int
    required_operator_count: int


class StaffAssignmentPayload(TypedDict, total=False):
    lift_id: EntityId
    operator_code: str
    role_on_lift: str
    shift_start: Instant
    shift_end: Instant


class TerrainAreaPayload(TypedDict, total=False):
    season_id: EntityId
    serving_lift_id: EntityId
    trail_code: str
    name: str
    terrain_class: str
    acres: float
    min_open_base_depth_in: int
    avalanche_terrain: bool


class SnowDepthReadingPayload(TypedDict, total=False):
    stake_code: str
    depth_in: float
    measured_at: Instant
    density_pct: float
    source: str


class ParkFeature(TypedDict, total=False):
    feature_type: str
    size_class: str


class PumpHousePayload(TypedDict, total=False):
    season_id: EntityId
    pump_house_code: str
    name: str
    max_gpm: int
    gun_count: int
    status: str


class SnowmakingSessionPayload(TypedDict, total=False):
    terrain_area_id: EntityId
    pump_house_id: EntityId
    window_start: Instant
    window_end: Instant
    gun_count: int
    gpm: int
    expected_terrain_area_version: int


class GroomingTaskPayload(TypedDict, total=False):
    terrain_area_id: EntityId
    cat_route_code: str
    sequence_index: int
    snowcat_unit_code: str
    window_start: Instant
    window_end: Instant
    winch_required: bool
    winch_anchor_code: Optional[str]


class PatrollerPayload(TypedDict, total=False):
    season_id: EntityId
    patroller_code: str
    full_name: str
    cert_level: str
    blaster_certified: bool
    on_duty: bool
    assigned_terrain_area_id: Optional[EntityId]


class MitigationMissionPayload(TypedDict, total=False):
    terrain_area_id: EntityId
    route_code: str
    method: str
    hazard_rating_pre: str
    planned_charges: int


class IncidentPayload(TypedDict, total=False):
    terrain_area_id: EntityId
    reporter_code: str
    severity: str
    location_note: str


class DayPlanPayload(TypedDict, total=False):
    season_id: EntityId
    operating_date: CalendarDate
    parking_stalls_total: int


class WeatherPayload(TypedDict, total=False):
    wind_speed_mph: float
    wet_bulb_f: float
    new_snow_in: float


class ReservationPayload(TypedDict, total=False):
    day_plan_id: EntityId
    party_code: str
    pass_type: str
    party_size: int
    vehicle_count: int
    expected_day_plan_version: int
