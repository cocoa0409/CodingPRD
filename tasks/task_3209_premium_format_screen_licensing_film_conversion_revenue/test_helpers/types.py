"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_PLANNER = "NetworkPlanner"
    PLATFORM_CONTRACT_MANAGER = "PlatformContractManager"
    STUDIO_RELATIONSHIP_MANAGER = "StudioRelationshipManager"
    POST_PRODUCTION_SCHEDULER = "PostProductionScheduler"
    QUALITY_ASSURANCE_REVIEWER = "QualityAssuranceReviewer"
    RELEASE_SCHEDULER = "ReleaseScheduler"
    BOX_OFFICE_ANALYST = "BoxOfficeAnalyst"
    EXHIBITOR_FINANCE_USER = "ExhibitorFinanceUser"
    FIELD_ENGINEER = "FieldEngineer"


class MarketStatus(str, Enum):
    PROSPECT = "PROSPECT"
    EVALUATING = "EVALUATING"
    APPROVED = "APPROVED"
    BUILDING = "BUILDING"
    LIVE = "LIVE"
    ABANDONED = "ABANDONED"


class AgreementStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AgreementType(str, Enum):
    REVENUE_SHARE = "REVENUE_SHARE"
    LEASE = "LEASE"


class AuditoriumStatus(str, Enum):
    DESIGN = "DESIGN"
    CONSTRUCTION = "CONSTRUCTION"
    CALIBRATION = "CALIBRATION"
    CERTIFIED = "CERTIFIED"
    OPERATING = "OPERATING"
    DEGRADED = "DEGRADED"
    DECOMMISSIONED = "DECOMMISSIONED"


class StudioStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FilmStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    IN_DISTRIBUTION = "IN_DISTRIBUTION"
    OUT_OF_WINDOW = "OUT_OF_WINDOW"
    ARCHIVED = "ARCHIVED"


class ConversionOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_POST = "IN_POST"
    QC_REVIEW = "QC_REVIEW"
    APPROVED_FOR_RELEASE = "APPROVED_FOR_RELEASE"
    REWORK_REQUESTED = "REWORK_REQUESTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class WindowStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_BOOKING = "OPEN_FOR_BOOKING"
    LOCKED = "LOCKED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class SlotStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    HELD_OVER = "HELD_OVER"
    PULLED = "PULLED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class ReportStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    FLAGGED_DISCREPANCY = "FLAGGED_DISCREPANCY"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"
    RECONCILED = "RECONCILED"


class AlertStatus(str, Enum):
    RAISED = "RAISED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"


class DispatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"


class Format(str, Enum):
    PREMIUM_2D = "PREMIUM_2D"
    PREMIUM_3D = "PREMIUM_3D"
    PREMIUM_70MM = "PREMIUM_70MM"


class AlertCode(str, Enum):
    LAMP_DEGRADED = "LAMP_DEGRADED"
    SOUND_DRIFT = "SOUND_DRIFT"
    PROJECTOR_TEMP = "PROJECTOR_TEMP"
    NETWORK_LOSS = "NETWORK_LOSS"
    CALIBRATION_OVERDUE = "CALIBRATION_OVERDUE"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class TechSpecialty(str, Enum):
    PROJECTION = "PROJECTION"
    SOUND = "SOUND"
    NETWORK = "NETWORK"
    GENERAL = "GENERAL"


class PriorityTier(str, Enum):
    BLOCKBUSTER = "BLOCKBUSTER"
    STANDARD = "STANDARD"
    FILLER = "FILLER"


class SubmissionChannel(str, Enum):
    EXHIBITOR_PORTAL = "EXHIBITOR_PORTAL"
    API_INGEST = "API_INGEST"
    MANUAL_UPLOAD = "MANUAL_UPLOAD"


# --- Entity TypedDicts (PRD §2.4: primary resources carry id/created_at/
# updated_at/version; BoxOfficeReport carries only id/created_at) ---


class Market(TypedDict, total=False):
    id: str
    market_name: str
    country_code: str
    screen_capacity_cap: int
    target_format_mix: List[str]
    opened_screen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExhibitorAgreement(TypedDict, total=False):
    id: str
    exhibitor_legal_name: str
    market_id: str
    agreement_type: str
    committed_screen_count: int
    revenue_share_tier1_pct: float
    revenue_share_tier2_pct: float
    revenue_share_tier3_pct: float
    annual_lease_fee_cents: int
    term_start_date: str
    term_end_date: str
    total_slots_committed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Auditorium(TypedDict, total=False):
    id: str
    agreement_id: str
    auditorium_label: str
    screen_geometry: Dict[str, Any]
    seating_capacity: int
    supported_formats: List[str]
    sound_calibration_profile: Dict[str, Any]
    last_calibration_at: str
    calibration_overdue: bool
    current_week_admissions: int
    quality_score_arithmetic: float
    quality_score_recency: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Studio(TypedDict, total=False):
    id: str
    studio_legal_name: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StudioFilm(TypedDict, total=False):
    id: str
    studio_id: str
    title: str
    runtime_minutes: int
    worldwide_release_date: str
    format_targets: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConversionOrder(TypedDict, total=False):
    id: str
    studio_film_id: str
    target_format: str
    scheduled_post_start_date: str
    scheduled_post_end_date: str
    filmmaker_approval_required: bool
    filmmaker_signoff: bool
    delivered_master_url: Optional[str]
    post_cost_estimate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseWindow(TypedDict, total=False):
    id: str
    window_label: str
    window_start_date: str
    window_end_date: str
    total_premium_screen_seconds_pool: int
    committed_premium_screen_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreenSlot(TypedDict, total=False):
    id: str
    window_id: str
    auditorium_id: str
    studio_film_id: str
    conversion_order_id: str
    slot_start_date: str
    slot_end_date: str
    showings_per_day: int
    priority_tier: str
    committed_screen_seconds: int
    weekly_gross_cents: int
    weekly_admissions: int
    per_screen_attendance_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BoxOfficeReport(TypedDict, total=False):
    # PRD §2.4: immutable ledger record — id and created_at ONLY.
    id: str
    created_at: str
    screen_slot_id: str
    reported_date: str
    gross_receipts_cents: int
    admissions: int
    submission_channel: str
    status: str


class RevenueShareStatement(TypedDict, total=False):
    id: str
    agreement_id: str
    window_id: str
    statement_lines: List[Dict[str, Any]]
    provisional_total_cents: float
    final_total_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int


class QAAlert(TypedDict, total=False):
    id: str
    auditorium_id: str
    alert_code: str
    severity: str
    raised_at: str
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TechDispatch(TypedDict, total=False):
    id: str
    qa_alert_id: str
    auditorium_id: str
    scheduled_visit_date: str
    tech_specialty: str
    resolution_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
