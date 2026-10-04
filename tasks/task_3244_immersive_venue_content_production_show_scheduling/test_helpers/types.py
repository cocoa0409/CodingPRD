"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DARK = "DARK"
    RETIRED = "RETIRED"


class AssetStatus(str, Enum):
    CAPTURED = "CAPTURED"
    RENDERING = "RENDERING"
    QC = "QC"
    QC_FAILED = "QC_FAILED"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"


class RenderBatchStatus(str, Enum):
    OPEN = "OPEN"
    RENDERING = "RENDERING"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class ShowStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    REHEARSAL = "REHEARSAL"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class VenueSystemStatus(str, Enum):
    ONLINE = "ONLINE"
    MAINTENANCE = "MAINTENANCE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


class MaintenanceWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    FINAL = "FINAL"


class Zone(str, Enum):
    MAIN = "MAIN"
    RING = "RING"
    APEX = "APEX"


class SeatKind(str, Enum):
    STANDARD = "STANDARD"
    WHEELCHAIR = "WHEELCHAIR"
    COMPANION = "COMPANION"


class QuotedVariant(str, Enum):
    EXPERIENCE_DIFF = "EXPERIENCE_DIFF"
    HAPTIC_SURCHARGE = "HAPTIC_SURCHARGE"


class ShowFormat(str, Enum):
    FILM = "FILM"
    CONCERT = "CONCERT"
    CORPORATE = "CORPORATE"


class ProductionType(str, Enum):
    ORIGINAL = "ORIGINAL"
    RESIDENCY = "RESIDENCY"
    CORPORATE = "CORPORATE"


class CaptureFormat(str, Enum):
    WRAP_16K = "WRAP_16K"
    WRAP_8K = "WRAP_8K"


class DispatchMode(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class SystemKind(str, Enum):
    AUDIO_BEAM = "AUDIO_BEAM"
    HAPTIC = "HAPTIC"
    ENV_FX = "ENV_FX"


class BrandTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class TechReadiness(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"


class UserRole(str, Enum):
    PRODUCTION_DIRECTOR = "ProductionDirector"
    CONTENT_PRODUCER = "ContentProducer"
    VENUE_SCHEDULER = "VenueScheduler"
    VENUE_OPS_ENGINEER = "VenueOpsEngineer"
    SPONSORSHIP_MANAGER = "SponsorshipManager"
    BOX_OFFICE_AGENT = "BoxOfficeAgent"
    GUEST = "Guest"


# All entities in this PRD carry the common fields
# (id, created_at, updated_at, version) per PRD section on common resource properties.

class Production(TypedDict, total=False):
    id: str
    title: str
    production_type: str
    base_price_cents: int
    is_haptic_capable: bool
    status: str
    gain_cents: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    production_id: str
    title: str
    capture_format: str
    storage_gb: int
    render_hours_base: float
    status: str
    render_cost_cents: float
    created_at: str
    updated_at: str
    version: int


class RenderBatch(TypedDict, total=False):
    id: str
    status: str
    dispatch_mode: str
    render_minutes: int
    batch_cost_cents: int
    submitted_asset_count: int
    failed_asset_count: int
    submitted_asset_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Show(TypedDict, total=False):
    id: str
    production_id: str
    show_format: str
    start_time: str
    length_minutes: int
    peak_rush_minutes: int
    rehearsal_minutes: int
    changeover_minutes: int
    tech_readiness: str
    status: str
    utilization_at_lock: float
    haptic_surcharge_cents_at_lock: int
    settlement_snapshot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    show_id: str
    zone: str
    seats: int
    seat_kind: str
    unit_price_cents: float
    line_total_cents: float
    quoted_variant: str
    refund_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class VenueSystem(TypedDict, total=False):
    id: str
    name: str
    kind: str
    status: str
    consecutive_failed_windows: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    venue_system_id: str
    start_time: str
    end_time: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict, total=False):
    id: str
    name: str
    brand_tier: str
    active_campaign_count: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    sponsor_id: str
    start_time: str
    end_time: str
    exterior_slots: int
    spot_seconds: int
    contracted_impressions: int
    delivered_impressions: int
    under_delivery: int
    make_good_credits: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    show_id: str
    gross_cents: float
    refunds_cents: float
    net_cents: float
    sponsor_payout_cents: float
    venue_retain_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int
