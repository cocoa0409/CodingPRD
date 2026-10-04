"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    ARCHIVED = "ARCHIVED"


class TitleStatus(str, Enum):
    PITCHED = "PITCHED"
    APPROVED = "APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TitleGenre(str, Enum):
    ROMANCE = "ROMANCE"
    FAMILY = "FAMILY"
    MYSTERY = "MYSTERY"
    COMEDY = "COMEDY"


class ToneRating(str, Enum):
    GENTLE = "GENTLE"
    WARM = "WARM"
    FESTIVE = "FESTIVE"


class ContentFlag(str, Enum):
    VIOLENCE = "VIOLENCE"
    ALCOHOL = "ALCOHOL"
    GAMBLING = "GAMBLING"
    HORROR = "HORROR"


class TalentDealStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    BREACHED = "BREACHED"


class CastingStatus(str, Enum):
    ATTACHED = "ATTACHED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class ProductionSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    WRAPPED = "WRAPPED"
    CANCELLED = "CANCELLED"


class ProgramBlockStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class AirSlotStatus(str, Enum):
    PLANNED = "PLANNED"
    AIRED = "AIRED"
    CANCELLED = "CANCELLED"


class AirSlotKind(str, Enum):
    PREMIERE = "PREMIERE"
    ENCORE = "ENCORE"


class SponsorshipStatus(str, Enum):
    BOOKED = "BOOKED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class StreamingPlatform(str, Enum):
    OWN_STREAMER = "OWN_STREAMER"
    PARTNER_STREAMER = "PARTNER_STREAMER"


class StreamingWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LicenseCategory(str, Enum):
    MERCHANDISE = "MERCHANDISE"
    PUBLISHING = "PUBLISHING"


class LicenseGrantStatus(str, Enum):
    REPORTED = "REPORTED"
    AUDITED = "AUDITED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SLATE_PLANNER = "SlatePlanner"
    PRODUCTION_MANAGER = "ProductionManager"
    TALENT_AGENT = "TalentAgent"
    PROGRAMMING_EXEC = "ProgrammingExec"
    AD_SALES_REP = "AdSalesRep"
    STREAMING_CURATOR = "StreamingCurator"
    LICENSING_MANAGER = "LicensingManager"


# All entities carry the full common-field set (id, created_at, updated_at, version)
# per PRD section on resource identity and versioning.

class Studio(TypedDict, total=False):
    id: str
    name: str
    ad_budget_cents: int
    created_at: str
    updated_at: str
    version: int


class Season(TypedDict, total=False):
    id: str
    studio_id: str
    year: int
    label: str
    required_title_count: int
    air_window_start: str
    air_window_end: str
    delivery_deadline: str
    max_shoot_days: int
    booked_shoot_days: int
    committed_title_count: int
    premiered_title_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    genre: str
    tone_rating: str
    content_flags: List[str]
    duration_minutes: int
    status: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Talent(TypedDict, total=False):
    id: str
    studio_id: str
    stage_name: str
    availability_windows: List[Any]
    created_at: str
    updated_at: str
    version: int


class TalentDeal(TypedDict, total=False):
    id: str
    studio_id: str
    talent_id: str
    season_id: str
    picture_commitment: int
    fulfilled_pictures: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Casting(TypedDict, total=False):
    id: str
    season_id: str
    title_id: str
    talent_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict, total=False):
    id: str
    studio_id: str
    name: str
    blackout_windows: List[Any]
    created_at: str
    updated_at: str
    version: int


class ProductionSlot(TypedDict, total=False):
    id: str
    season_id: str
    title_id: str
    location_id: str
    shoot_start: str
    shoot_end: str
    shoot_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramBlock(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    block_start: str
    premiere_cadence_days: int
    max_encores_per_title: int
    min_minutes_between_airings: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AirSlot(TypedDict, total=False):
    id: str
    block_id: str
    title_id: str
    season_id: str
    air_start: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sponsorship(TypedDict, total=False):
    id: str
    season_id: str
    advertiser: str
    season_cpm_cents: int
    viewership_thousands: int
    projected_cost_cents: int
    actual_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class StreamingWindow(TypedDict, total=False):
    id: str
    season_id: str
    title_id: str
    platform: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseGrant(TypedDict, total=False):
    id: str
    season_id: str
    title_id: str
    category: str
    licensee: str
    royalty_rate: float
    reported_revenue_cents: int
    provisional_royalty_cents: int
    trued_royalty_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
