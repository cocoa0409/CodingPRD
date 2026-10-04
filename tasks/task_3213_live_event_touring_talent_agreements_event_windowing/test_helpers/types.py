"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CONTRACT_ADMIN = "ContractAdmin"
    TOUR_PLANNER = "TourPlanner"
    TALENT_RELATIONS = "TalentRelations"
    STORYLINE_EDITOR = "StorylineEditor"
    DISTRIBUTION_MANAGER = "DistributionManager"
    MERCH_OPS = "MerchOps"
    MEDIC = "Medic"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"


class RosterTier(str, Enum):
    DEVELOPMENTAL = "DEVELOPMENTAL"
    MAIN_ROSTER = "MAIN_ROSTER"


class AvailabilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INJURED = "INJURED"
    SUSPENDED = "SUSPENDED"


class BookingMode(str, Enum):
    BOOKABLE = "BOOKABLE"
    LIMITED = "LIMITED"
    UNBOOKABLE = "UNBOOKABLE"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class EventType(str, Enum):
    TELEVISION = "TELEVISION"
    PREMIUM = "PREMIUM"
    HOUSE_SHOW = "HOUSE_SHOW"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    SCRATCHED = "SCRATCHED"
    FULFILLED = "FULFILLED"
    NO_SHOW = "NO_SHOW"


class StorylineStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    SHELVED = "SHELVED"
    CONCLUDED = "CONCLUDED"


class ChapterStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class WindowType(str, Enum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"


class WindowStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    PUBLISHED = "PUBLISHED"
    REVOKED = "REVOKED"


class BasisMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class MedicalCaseStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"


class VisaStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class CallUpDecisionKind(str, Enum):
    PROMOTE = "PROMOTE"
    DEFER = "DEFER"


class Talent(TypedDict, total=False):
    id: str
    ring_name: str
    legal_name: str
    contractor_status: str
    roster_tier: str
    availability_status: str
    wellness_score: float
    booking_mode: str
    likeness_granted: bool
    created_at: str
    updated_at: str
    version: int


class TalentAgreement(TypedDict, total=False):
    id: str
    talent_id: str
    start_date: str
    end_date: str
    downside_guarantee_cents: int
    royalty_rate_bp: int
    likeness_rights_granted: bool
    min_appearances_per_quarter: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Arena(TypedDict, total=False):
    id: str
    name: str
    city: str
    country_code: str
    capacity: int
    merch_booths: int
    timezone: str
    created_at: str
    updated_at: str
    version: int


class BroadcastAnchor(TypedDict, total=False):
    id: str
    name: str
    weekly_day_of_week: int
    territory_code: str
    must_have_event_each_week: bool
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict, total=False):
    id: str
    name: str
    event_type: str
    arena_id: str
    anchor_id: Optional[str]
    event_date: str
    start_time: str
    end_time: str
    tour_country_code: str
    status: str
    roster_min_main: int
    roster_min_total: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    event_id: str
    talent_id: str
    storyline_id: Optional[str]
    segment_label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Storyline(TypedDict, total=False):
    id: str
    title: str
    status: str
    gap_count: int
    created_at: str
    updated_at: str
    version: int


class Chapter(TypedDict, total=False):
    id: str
    storyline_id: str
    event_id: str
    chapter_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StreamingPartner(TypedDict, total=False):
    id: str
    name: str
    partner_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TerritoryRight(TypedDict, total=False):
    id: str
    partner_id: str
    territory_code: str
    window_start_date: str
    window_end_date: str
    exclusive: bool
    created_at: str
    updated_at: str
    version: int


class DistributionWindow(TypedDict, total=False):
    id: str
    event_id: str
    partner_id: str
    territory_code: str
    window_type: str
    opens_at: str
    closes_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MerchSale(TypedDict, total=False):
    # Immutable ledger entry: carries only id + created_at plus domain fields.
    # updated_at and version MUST NOT be present.
    id: str
    event_id: str
    talent_id: str
    quantity: int
    unit_price_cents: int
    sold_at: str
    royalty_cents: int
    created_at: str


class RoyaltyStatement(TypedDict, total=False):
    id: str
    talent_id: str
    period_start_date: str
    period_end_date: str
    basis_mode: str
    status: str
    event_id: Optional[str]
    total_sales_cents: int
    total_royalty_cents: int
    created_at: str
    updated_at: str
    version: int


class MedicalCase(TypedDict, total=False):
    id: str
    talent_id: str
    severity: str
    evaluation_ids: List[str]
    clearance_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicalEvaluation(TypedDict, total=False):
    id: str
    medical_case_id: str
    evaluator_id: str
    findings: str
    recommends_clearance: bool
    created_at: str
    updated_at: str
    version: int


class MedicalClearance(TypedDict, total=False):
    id: str
    medical_case_id: str
    cleared_by: str
    cleared_at: str
    created_at: str
    updated_at: str
    version: int


class VisaCase(TypedDict, total=False):
    id: str
    talent_id: str
    country_code: str
    required_by_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CallUpDecision(TypedDict, total=False):
    id: str
    talent_id: str
    readiness_score: int
    decision: str
    decided_by: str
    created_at: str
    updated_at: str
    version: int
