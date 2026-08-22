"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted resource in this system carries the same four common
properties (id, created_at, updated_at, version), so every TypedDict below
lists all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    MUSIC_HOUSE_PRODUCER = "MusicHouseProducer"
    CLIENT_REP = "ClientRep"
    COMPOSER = "Composer"
    RIGHTS_ADMIN = "RightsAdmin"
    AFM_STEWARD = "AFMSteward"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    BRIEFING = "BRIEFING"
    IN_DEMO = "IN_DEMO"
    IN_PRODUCTION = "IN_PRODUCTION"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    ON_HOLD = "ON_HOLD"


class BudgetPosture(str, Enum):
    HEALTHY = "HEALTHY"
    CONSTRAINED = "CONSTRAINED"
    FROZEN = "FROZEN"


class CreativeBriefStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ProAffiliation(str, Enum):
    ASCAP = "ASCAP"
    BMI = "BMI"
    SESAC = "SESAC"
    NONE = "NONE"


class DemoStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SHORTLISTED = "SHORTLISTED"
    SELECTED = "SELECTED"
    ARCHIVED = "ARCHIVED"


class AfmMemberStatus(str, Enum):
    SIGNATORY_CLEARED = "SIGNATORY_CLEARED"
    NON_UNION = "NON_UNION"
    SUSPENDED = "SUSPENDED"


class StudioRoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class SessionCallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUSPENDED_BUDGET = "SUSPENDED_BUDGET"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED_INSIDE_WINDOW = "CANCELLED_INSIDE_WINDOW"
    CANCELLED_OUTSIDE_WINDOW = "CANCELLED_OUTSIDE_WINDOW"


class MusicianBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    WAGE_ACCRUED = "WAGE_ACCRUED"
    PENALTY_ACCRUED = "PENALTY_ACCRUED"
    RELEASED = "RELEASED"


class LicenseStructure(str, Enum):
    BUYOUT = "BUYOUT"
    TERM = "TERM"


class LicenseDealStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    LAPSED = "LAPSED"
    SUPERSEDED = "SUPERSEDED"


class ReuseExtensionStatus(str, Enum):
    ACTIVE = "ACTIVE"


class MarketTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class MasterStatus(str, Enum):
    PENDING = "PENDING"
    STEMS_DELIVERED = "STEMS_DELIVERED"
    CLIENT_APPROVED = "CLIENT_APPROVED"


class CueSheetStatus(str, Enum):
    NOT_FILED = "NOT_FILED"
    FILED = "FILED"
    REGISTERED = "REGISTERED"


class CueSheetEntryStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    VOIDED = "VOIDED"


class CueSheetRole(str, Enum):
    COMPOSER = "COMPOSER"
    ARRANGER = "ARRANGER"
    PUBLISHER = "PUBLISHER"


class LibraryTrackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RecommendedMode(str, Enum):
    LIBRARY = "LIBRARY"
    CUSTOM = "CUSTOM"


class AfmReportBasis(str, Enum):
    SESSION = "SESSION"
    DAY = "DAY"


class Client(TypedDict):
    id: str
    name: str
    agency_code: str
    billing_email: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    client_id: str
    title: str
    budget_cents: int
    committed_cents: int
    available_cents: int
    spent_cents: int
    budget_posture: str
    status: str
    status_before_hold: Optional[str]
    delivery_deadline_utc: str
    created_at: str
    updated_at: str
    version: int


class CreativeBrief(TypedDict):
    id: str
    project_id: str
    tempo_bpm: int
    mood_tags: List[str]
    target_markets: List[str]
    required_lengths: List[int]
    reference_track_url: Optional[str]
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Composer(TypedDict):
    id: str
    display_name: str
    pro_affiliation: str
    created_at: str
    updated_at: str
    version: int


class Demo(TypedDict):
    id: str
    project_id: str
    composer_id: str
    title: str
    demo_fee_cents: int
    submitted_length_seconds: int
    revision_count: int
    accrued_fee_cents: int
    last_revision_note: Optional[str]
    selected_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Musician(TypedDict):
    id: str
    full_name: str
    instrument: str
    scale_hourly_cents: int
    afm_member_status: str
    created_at: str
    updated_at: str
    version: int


class StudioRoom(TypedDict):
    id: str
    name: str
    hourly_rate_cents: int
    capacity_players: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionCall(TypedDict):
    id: str
    project_id: str
    studio_room_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    actual_end_utc: Optional[str]
    scheduled_hours: float
    billed_hours: float
    studio_cost_cents: int
    wage_estimate_cents: int
    committed_cents: int
    wage_total_cents: int
    settled_total_cents: int
    wage_liability_cents: int
    cancelled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MusicianBooking(TypedDict):
    id: str
    session_call_id: str
    musician_id: str
    is_leader: bool
    doubles_count: int
    line_wage_cents: int
    pension_health_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseDeal(TypedDict):
    id: str
    project_id: str
    demo_id: str
    license_structure: str
    term_months: Optional[int]
    market_codes: List[str]
    creative_fee_cents: int
    license_fee_quoted_cents: int
    license_fee_invoiced_cents: int
    renewal_count: int
    renewal_fee_cents: int
    counter_round_count: int
    effective_start_utc: Optional[str]
    effective_end_utc: Optional[str]
    drafted_by_user_id: str
    activated_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReuseExtension(TypedDict):
    id: str
    license_deal_id: str
    market_code: str
    market_tier: str
    reuse_base_cents: int
    admin_pct: int
    admin_fee_cents: int
    reuse_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    license_deal_id: str
    master_status: str
    cuesheet_status: str
    delivered_lengths: List[int]
    stem_manifest: List[str]
    unallocated_bps: int
    registered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CueSheetEntry(TypedDict):
    id: str
    deliverable_id: str
    composer_id: str
    role: str
    declared_weight: int
    share_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LibraryTrack(TypedDict):
    id: str
    title: str
    blanket_fee_cents: int
    per_market_fee_cents: int
    max_markets: int
    min_length_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int
