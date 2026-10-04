"""Domain types: entity shapes, status enums, role enum.

Every resource in the Watch Warning Issuance API shares the four system-managed
fields ``id``, ``created_at``, ``updated_at`` and ``version`` (PRD §2.4); each
TypedDict below lists the entity-specific fields on top of those. Field names are
exactly the names the API returns. Values that stay null until a lifecycle event
are typed ``Optional``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

# Lightweight aliases for the shapes that flow between helpers and tests.
JsonObject = Dict[str, Any]
JsonList = List[Any]
Headers = Dict[str, str]
Filters = Dict[str, Any]
ResourceId = str
Instant = str


# ---------------------------------------------------------------------------
# Role and shared enumerations (PRD §2.1, §2.7)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FORECASTER = "Forecaster"
    METEOROLOGIST_IN_CHARGE = "MeteorologistInCharge"
    VERIFICATION_ANALYST = "VerificationAnalyst"
    EMERGENCY_MANAGER = "EmergencyManager"


class HazardType(str, Enum):
    TORNADO = "TORNADO"
    SEVERE_THUNDERSTORM = "SEVERE_THUNDERSTORM"
    FLASH_FLOOD = "FLASH_FLOOD"
    HURRICANE = "HURRICANE"
    WINTER_STORM = "WINTER_STORM"


class ProductLevel(str, Enum):
    OUTLOOK = "OUTLOOK"
    WATCH = "WATCH"
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"


class DamageThreat(str, Enum):
    NONE = "NONE"
    CONSIDERABLE = "CONSIDERABLE"
    CATASTROPHIC = "CATASTROPHIC"


class AreaMethod(str, Enum):
    PLANAR = "PLANAR"
    GEODETIC = "GEODETIC"


class PerformanceBand(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class PopulationTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URBAN = "URBAN"


class ChannelType(str, Enum):
    EAS = "EAS"
    WEA = "WEA"
    NOAA_WEATHER_RADIO = "NOAA_WEATHER_RADIO"
    DATA_FEED = "DATA_FEED"


class ChannelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ForecasterLevel(str, Enum):
    JOURNEYMAN = "JOURNEYMAN"
    SENIOR = "SENIOR"
    MIC = "MIC"


class SupersedeReason(str, Enum):
    UPGRADE = "UPGRADE"
    CONTINUATION = "CONTINUATION"
    CORRECTION = "CORRECTION"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class MatchingVariant(str, Enum):
    POLYGON_STRICT = "POLYGON_STRICT"
    COUNTY_FALLBACK = "COUNTY_FALLBACK"


class EmergencyActionType(str, Enum):
    EVACUATION = "EVACUATION"
    SHELTER_IN_PLACE = "SHELTER_IN_PLACE"
    SHELTER_OPEN = "SHELTER_OPEN"


# ---------------------------------------------------------------------------
# Lifecycle enumerations (PRD §2.7)
# ---------------------------------------------------------------------------
class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_COORDINATION = "PENDING_COORDINATION"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class CoordinationRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    OVERRIDDEN = "OVERRIDDEN"


class DisseminationRecordStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"
    DEAD = "DEAD"


class StormEventStatus(str, Enum):
    DETECTED = "DETECTED"
    TRACKING = "TRACKING"
    DISSIPATED = "DISSIPATED"


class VerificationEventStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class EmergencyActionStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    ORDERED = "ORDERED"
    LIFTED = "LIFTED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Geometry payload shapes (PRD §3.4)
# ---------------------------------------------------------------------------
class Vertex(TypedDict):
    lat: float
    lon: float


class Polygon(TypedDict):
    vertices: List[Vertex]


# ---------------------------------------------------------------------------
# Entity shapes (PRD §2.4 common fields + per-entity fields)
# ---------------------------------------------------------------------------
class ForecastOffice(TypedDict):
    id: ResourceId
    office_code: str
    name: str
    region: str
    area_method: str
    performance_band: str
    last_statistic_at: Optional[Instant]
    created_at: Instant
    updated_at: Instant
    version: int


class CountyZone(TypedDict):
    id: ResourceId
    zone_code: str
    name: str
    office_id: ResourceId
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    surveyed_area_sq_km: float
    population_tier: str
    coastal: bool
    created_at: Instant
    updated_at: Instant
    version: int


class NeighborAgreement(TypedDict):
    id: ResourceId
    office_a_id: ResourceId
    office_b_id: ResourceId
    hazard_types: List[str]
    coordination_timeout_minutes: int
    created_at: Instant
    updated_at: Instant
    version: int


class AlertChannel(TypedDict):
    id: ResourceId
    name: str
    channel_type: str
    supports_levels: List[str]
    max_message_chars: int
    requires_confirmation: bool
    status: str
    created_at: Instant
    updated_at: Instant
    version: int


class Forecaster(TypedDict):
    id: ResourceId
    office_id: ResourceId
    full_name: str
    employee_code: str
    level: str
    created_at: Instant
    updated_at: Instant
    version: int


class StormEvent(TypedDict):
    id: ResourceId
    office_id: ResourceId
    hazard_type: str
    max_wind_mph: int
    max_hail_inches: float
    rainfall_rate_in_hr: float
    rotation_couplet: bool
    debris_signature: bool
    motion_degrees: int
    speed_kt: int
    detected_at: Instant
    status: str
    dissipated_at: Optional[Instant]
    created_at: Instant
    updated_at: Instant
    version: int


class Product(TypedDict):
    id: ResourceId
    product_level: str
    hazard_type: str
    issuing_office_id: ResourceId
    storm_event_id: Optional[ResourceId]
    zone_ids: Optional[List[ResourceId]]
    polygon: Optional[Polygon]
    resolved_zone_ids: List[ResourceId]
    polygon_area_sq_km: Optional[float]
    damage_threat: str
    wea_360: bool
    effective_from: Optional[Instant]
    expires_at: Instant
    issued_at: Optional[Instant]
    cancelled_at: Optional[Instant]
    superseded_at: Optional[Instant]
    expired_at: Optional[Instant]
    window_end: Optional[Instant]
    supersedes_product_id: Optional[ResourceId]
    supersede_reason: Optional[str]
    coordination_required: bool
    verified_event_count: int
    verification_status: str
    status: str
    created_at: Instant
    updated_at: Instant
    version: int


class CoordinationRequest(TypedDict):
    id: ResourceId
    product_id: ResourceId
    from_office_id: ResourceId
    to_office_id: ResourceId
    hazard_type: str
    status: str
    requested_at: Instant
    deadline_at: Instant
    responded_at: Optional[Instant]
    created_at: Instant
    updated_at: Instant
    version: int


class DisseminationRecord(TypedDict):
    id: ResourceId
    product_id: ResourceId
    channel_id: ResourceId
    channel_type: str
    status: str
    rendered_message: Optional[str]
    included_zone_ids: Optional[List[ResourceId]]
    retry_count: int
    queued_at: Instant
    sent_at: Optional[Instant]
    confirmed_at: Optional[Instant]
    created_at: Instant
    updated_at: Instant
    version: int


class VerificationEvent(TypedDict):
    id: ResourceId
    zone_id: ResourceId
    storm_event_id: Optional[ResourceId]
    hazard_type: str
    observed_at: Instant
    location_lat: float
    location_lon: float
    magnitude: str
    status: str
    matched_product_ids: List[ResourceId]
    adjudicated_at: Optional[Instant]
    created_at: Instant
    updated_at: Instant
    version: int


class VerificationStatistic(TypedDict):
    id: ResourceId
    office_id: ResourceId
    hazard_type: str
    period_start: Instant
    period_end: Instant
    matching_variant: str
    total_warnings: int
    events_total: int
    events_warned: int
    events_unwarned: int
    false_alarms: int
    pod: Optional[float]
    far: Optional[float]
    avg_lead_time_minutes: Optional[float]
    computed_at: Instant
    created_at: Instant
    updated_at: Instant
    version: int


class EmergencyAction(TypedDict):
    id: ResourceId
    zone_id: ResourceId
    product_id: ResourceId
    action_type: str
    effective_from: Instant
    effective_until: Instant
    status: str
    decided_by: str
    ordered_at: Optional[Instant]
    lifted_at: Optional[Instant]
    created_at: Instant
    updated_at: Instant
    version: int


class WeaPreview(TypedDict):
    """Response body of the WEA preview capability (PRD §3.6)."""

    message: str
    included_zone_ids: List[ResourceId]
    dropped_zone_ids: List[ResourceId]
    char_count: int
    would_overflow: bool


__all__ = [
    "JsonObject",
    "JsonList",
    "Headers",
    "Filters",
    "ResourceId",
    "Instant",
    "UserRole",
    "HazardType",
    "ProductLevel",
    "DamageThreat",
    "AreaMethod",
    "PerformanceBand",
    "PopulationTier",
    "ChannelType",
    "ChannelStatus",
    "ForecasterLevel",
    "SupersedeReason",
    "VerificationStatus",
    "MatchingVariant",
    "EmergencyActionType",
    "ProductStatus",
    "CoordinationRequestStatus",
    "DisseminationRecordStatus",
    "StormEventStatus",
    "VerificationEventStatus",
    "EmergencyActionStatus",
    "Vertex",
    "Polygon",
    "ForecastOffice",
    "CountyZone",
    "NeighborAgreement",
    "AlertChannel",
    "Forecaster",
    "StormEvent",
    "Product",
    "CoordinationRequest",
    "DisseminationRecord",
    "VerificationEvent",
    "VerificationStatistic",
    "EmergencyAction",
    "WeaPreview",
]
