"""Domain types: entity shapes, status enums, and the role enum.

Every enum member's wire value is the exact string the API places on the
envelope. All ten entities carry the four system-managed properties ``id``,
``created_at``, ``updated_at`` and ``version`` alongside their own fields, so
every TypedDict below includes them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The six declared caller roles (exact spellings)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    PROGRAM_MANAGER = "ProgramManager"
    CAPACITY_PLANNER = "CapacityPlanner"
    FINANCE_CONTROLLER = "FinanceController"
    LEGAL_COUNSEL = "LegalCounsel"
    DEVICE_MAKER = "DeviceMaker"


class StandingTier(str, Enum):
    STANDARD = "STANDARD"
    STRATEGIC = "STRATEGIC"
    PROBATION = "PROBATION"


class IpReviewStatus(str, Enum):
    CLEAR = "CLEAR"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED_INFRINGEMENT = "CONFIRMED_INFRINGEMENT"
    CLEARED = "CLEARED"


class Market(str, Enum):
    CONSUMER_ELECTRONICS = "CONSUMER_ELECTRONICS"
    AUTOMOTIVE = "AUTOMOTIVE"
    PHARMA_PACKAGING = "PHARMA_PACKAGING"
    ARCHITECTURAL = "ARCHITECTURAL"


class ConfidentialityTier(str, Enum):
    STANDARD_CONFIDENTIAL = "STANDARD_CONFIDENTIAL"
    HIGH_CONFIDENTIAL = "HIGH_CONFIDENTIAL"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    NDA_EXECUTED = "NDA_EXECUTED"
    COMPOSITION_TUNING = "COMPOSITION_TUNING"
    QUALIFICATION = "QUALIFICATION"
    DESIGN_FROZEN = "DESIGN_FROZEN"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class CompositionStatus(str, Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    TUNED = "TUNED"
    QUALIFIED = "QUALIFIED"
    LOCKED = "LOCKED"
    RETIRED = "RETIRED"


class QualCycleStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_TESTING = "IN_TESTING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class QualOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class TankStatus(str, Enum):
    CONSTRUCTING = "CONSTRUCTING"
    COMMISSIONED = "COMMISSIONED"


class CampaignStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


class CommitmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SIGNED = "SIGNED"
    COUNTERSIGNED = "COUNTERSIGNED"
    SECURED = "SECURED"
    BREACH_WATCH = "BREACH_WATCH"
    EXHAUSTED = "EXHAUSTED"
    BREACHED = "BREACHED"
    RELEASED = "RELEASED"


class CoverageTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"


class LicenseStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class MarketingStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    IP_REVIEW = "IP_REVIEW"
    MANUAL = "MANUAL"


class MarketingDecision(str, Enum):
    APPROVED = "APPROVED"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"


class UsageReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    HELD = "HELD"


class Channel(str, Enum):
    DOMESTIC = "DOMESTIC"
    EXPORT = "EXPORT"


# ── Entity record shapes ─────────────────────────────────────────────────────


class DeviceMaker(TypedDict):
    id: str
    name: str
    region: str
    standing_tier: str
    ip_review_status: str
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    device_maker_id: str
    name: str
    primary_market: str
    confidentiality_tier: str
    status: str
    nda_reference: Optional[str]
    design_freeze_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Composition(TypedDict):
    id: str
    program_id: str
    composition_code: str
    complexity_multiplier: float
    status: str
    created_at: str
    updated_at: str
    version: int


class QualCycle(TypedDict):
    id: str
    composition_id: str
    test_plan_ref: str
    attempt_number: int
    status: str
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tank(TypedDict):
    id: str
    commitment_id: str
    capacity_units_per_day: int
    status: str
    construction_ready_date: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    tank_id: str
    composition_id: str
    start_date: str
    end_date: str
    planned_units: int
    status: str
    expected_good_units: int
    unallocated_units: int
    cumulative_good_units: int
    cumulative_scrap_units: int
    realized_yield: Optional[float]
    provisional_unit_cost_cents: int
    final_unit_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Commitment(TypedDict):
    id: str
    program_id: str
    device_maker_id: str
    committed_units: int
    required_units: int
    prepayment_cents: int
    status: str
    coverage_tier: Optional[str]
    effective_units: Optional[int]
    fulfilled_units: int
    supply_coverage: float
    prepayment_applied_cents: int
    prepayment_remaining_cents: int
    prepayment_refunded_cents: int
    breach_deadline: Optional[str]
    countersigned_by: Optional[str]
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    commitment_id: str
    campaign_id: str
    units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    device_maker_id: str
    program_id: str
    market: str
    effective_date: str
    expiry_date: str
    license_status: str
    marketing_status: str
    suspension_reason: str
    cumulative_royalty_cents: int
    created_at: str
    updated_at: str
    version: int


class UsageReportLine(TypedDict):
    channel: str
    units: int
    net_revenue_cents: int


class UsageReport(TypedDict):
    id: str
    license_id: str
    period_start: str
    period_end: str
    lines: List[UsageReportLine]
    status: str
    royalty_rate_applied: float
    provisional_royalty_cents: int
    final_royalty_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CheckpointResult(TypedDict):
    campaigns_completed: int
    campaigns_cancelled: int
    licenses_expired: int
    commitments_exhausted: int
    commitments_breached: int
