"""Domain types: entity TypedDicts, status enums, role enum.

Every top-level resource in this API carries the four system-managed fields
`id`, `created_at`, `updated_at` and `version`; there are no write-once
resources, so none of these TypedDicts are append-only.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enums ────────────────────────────────────────────

class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    STORE_ORGANIZER = "StoreOrganizer"
    JUDGE = "Judge"
    DISTRIBUTOR = "Distributor"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ReportingTier(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"


class SetReleaseStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    PRERELEASE = "PRERELEASE"
    RELEASED = "RELEASED"
    RETIRED = "RETIRED"


class FormatRotationPolicy(str, Enum):
    FIXED = "FIXED"
    ROLLING = "ROLLING"


class EventTier(str, Enum):
    LOCAL = "LOCAL"
    QUALIFIER = "QUALIFIER"
    CHAMPIONSHIP = "CHAMPIONSHIP"


class EventApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"
    REPORTED = "REPORTED"


class PrizingReportStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    SUBMITTED = "SUBMITTED"


class PrizeAllocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RELEASED = "RELEASED"


class PrizeDistributionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PASSED = "PASSED"
    VOIDED = "VOIDED"


class PrizeReportStatus(str, Enum):
    FILED = "FILED"
    OVERDUE = "OVERDUE"


class OffenseClass(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class RulesEnforcementLevel(str, Enum):
    REGULAR = "REGULAR"
    COMPETITIVE = "COMPETITIVE"
    PROFESSIONAL = "PROFESSIONAL"


class EnforcementCaseStatus(str, Enum):
    FILED = "FILED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"
    REDUCED = "REDUCED"


class CodeKind(str, Enum):
    DIGITAL = "DIGITAL"
    PHYSICAL = "PHYSICAL"


class CodeRedemptionStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    REDEEMED = "REDEEMED"
    DECLINED = "DECLINED"


class PhysicalGrantStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    RESERVED = "RESERVED"
    DISBURSED = "DISBURSED"


class ProductConfigurationKind(str, Enum):
    DRAFT_BOOSTER = "DRAFT_BOOSTER"
    COLLECTOR_BOOSTER = "COLLECTOR_BOOSTER"
    BUNDLE = "BUNDLE"


class AllocationOrderStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"


class JudgeLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class JudgeCertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECERTIFIED = "DECERTIFIED"


class ReprintVerdict(str, Enum):
    REPRINT_ALLOWED = "REPRINT_ALLOWED"
    REPRINT_DENIED = "REPRINT_DENIED"


class ReprintPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"


# ─── Entity TypedDicts (all carry id + created_at + updated_at + version) ──

class Store(TypedDict):
    id: str
    name: str
    region_code: str
    reporting_tier: str
    daily_event_capacity: int
    event_space_capacity: int
    status: str
    tp_balance: int
    reporting_violation_points: int
    created_at: str
    updated_at: str
    version: int


class SetRelease(TypedDict):
    id: str
    set_code: str
    prerelease_start_date: str
    prerelease_end_date: str
    street_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Format(TypedDict):
    id: str
    name: str
    format_code: str
    rotation_policy: str
    current_epoch: int
    banned_card_refs: List[str]
    restricted_card_refs: List[str]
    created_at: str
    updated_at: str
    version: int


class EventApplication(TypedDict):
    id: str
    store_id: str
    set_release_id: str
    format_id: str
    format_code: str
    tier: str
    scheduled_date: str
    expected_headcount: int
    status: str
    prizing_report_status: str
    reporting_due_by: Optional[str]
    prize_allocation_id: Optional[str]
    prize_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrizeAllocation(TypedDict):
    id: str
    store_id: str
    event_application_id: str
    tier: str
    base_tp: int
    remaining_tp: int
    total_drawn_tp: int
    total_restored_tp: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrizeDistribution(TypedDict):
    id: str
    prize_allocation_id: str
    recipient_ref: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrizeReport(TypedDict):
    id: str
    event_application_id: str
    prize_allocation_id: str
    unclaimed_tp: int
    reported_headcount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RulesEnforcementCase(TypedDict):
    id: str
    event_application_id: str
    player_ref: str
    judge_ref: str
    offense_class: str
    rules_enforcement_level: str
    repeated_offense: bool
    penalty_points: int
    current_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CodeRedemption(TypedDict):
    id: str
    code_kind: str
    redemption_code: str
    event_application_id: str
    redemption_seq: Optional[int]
    status: str
    physical_grant_status: str
    prize_allocation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductConfiguration(TypedDict):
    id: str
    set_release_id: str
    configuration_kind: str
    pack_count: int
    print_run_units: int
    units_allocated: int
    units_available: int
    created_at: str
    updated_at: str
    version: int


class AllocationOrder(TypedDict):
    id: str
    distributor_name: str
    product_configuration_id: str
    quantity: int
    submitted_seq: int
    status: str
    approval_rank: Optional[int]
    fulfilled_qty: int
    created_at: str
    updated_at: str
    version: int


class JudgeCertification(TypedDict):
    id: str
    judge_ref: str
    name: str
    level: str
    status: str
    practice_events: int
    promotion_eligible: bool
    created_at: str
    updated_at: str
    version: int


class ReprintPlan(TypedDict):
    id: str
    card_name: str
    set_release_id: str
    format_id: str
    secondary_market_index: int
    first_print_index: int
    verdict: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrizingSummary(TypedDict):
    """Computed read returned by GET /op/event-applications/{id}/prizing-summary."""
    reporting_due_by: Optional[str]
    reporting_due_status: str
    qualified_headcount: bool
    prize_pool_remaining_tp: int
    report_status: str
    headcount_gate_error: Optional[str]