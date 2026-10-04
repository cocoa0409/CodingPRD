"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the four common server-managed properties (id, created_at,
updated_at, version) per PRD section "Common Resource Properties".
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    COACH = "Coach"
    SUPPORT = "Support"
    PLATFORM_ADMIN = "PlatformAdmin"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DataSharingPosture(str, Enum):
    NORMAL = "NORMAL"
    SUPPRESSED = "SUPPRESSED"


class TermStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PAST_DUE = "PAST_DUE"
    CANCELLED_EARLY = "CANCELLED_EARLY"
    COMPLETED = "COMPLETED"


class HardwareTier(str, Enum):
    BAND_STD = "BAND_STD"
    BAND_PRO = "BAND_PRO"


class CancelFeePolicy(str, Enum):
    REMAINING_MONTHS = "REMAINING_MONTHS"
    PAID_MONTHS_FLOOR = "PAID_MONTHS_FLOOR"


class DeviceStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    SUSPECT_FAULT = "SUSPECT_FAULT"
    RMA_INBOUND = "RMA_INBOUND"
    RETIRED = "RETIRED"


class DeviceDiagnosis(str, Enum):
    CONFIRMED_FAILURE = "CONFIRMED_FAILURE"
    NO_FAULT = "NO_FAULT"
    USER_DAMAGE = "USER_DAMAGE"


class InterpretationStatus(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    RECOMPUTED = "RECOMPUTED"


class ReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class TeamType(str, Enum):
    SPORTS = "SPORTS"
    CORPORATE_WELLNESS = "CORPORATE_WELLNESS"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ConsentScope(str, Enum):
    STRAIN = "STRAIN"
    RECOVERY = "RECOVERY"
    SLEEP = "SLEEP"


class ConsentStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class StudyStatus(str, Enum):
    RECRUITING = "RECRUITING"
    CLOSED = "CLOSED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class ReplacementReason(str, Enum):
    HARDWARE_FAILURE = "HARDWARE_FAILURE"
    BATTERY_DRAIN = "BATTERY_DRAIN"
    SENSOR_DRIFT = "SENSOR_DRIFT"


class ReplacementRequestStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class OrderStatus(str, Enum):
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class MerchCategory(str, Enum):
    BAND_ACCESSORY = "BAND_ACCESSORY"
    APPAREL = "APPAREL"
    RECOVERY_GEAR = "RECOVERY_GEAR"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    member_status: str
    wallet_credit_cents: int
    data_sharing_posture: str
    algorithm_ack_release_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PauseWindow(TypedDict, total=False):
    start_on: str
    end_on: Optional[str]
    window_status: str


class MembershipTerm(TypedDict, total=False):
    id: str
    member_id: str
    plan_name: str
    monthly_fee_cents: int
    commitment_months: int
    hardware_tier: str
    upgrade_eligibility_months: int
    pause_days_per_term: int
    cancel_fee_policy: str
    early_cancel_fee_floor_cents: int
    term_status: str
    started_on: str
    commitment_end_on: str
    months_paid: int
    pause_days_used: int
    pause_windows: List[PauseWindow]
    open_pause_end_on: Optional[str]
    cancel_fee_charged_cents: Optional[int]
    last_upgrade_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    member_id: str
    term_id: str
    serial_number: str
    hardware_tier: str
    device_status: str
    activated_on: Optional[str]
    continuity_start_on: Optional[str]
    continuity_end_on: Optional[str]
    diagnosis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DailyMetricSet(TypedDict, total=False):
    id: str
    member_id: str
    day_on: str
    avg_hr: float
    hrv_ms: float
    resting_hr: float
    sleep_minutes: int
    algorithm_version: int
    strain_score: float
    recovery_score: int
    sleep_performance_pct: int
    interpretation_status: str
    created_at: str
    updated_at: str
    version: int


class AlgorithmRelease(TypedDict, total=False):
    id: str
    version: int
    requires_member_ack: bool
    release_notes: str
    release_status: str
    published_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    name: str
    team_type: str
    coach_user_id: str
    created_at: str
    updated_at: str
    version: int


class ConsentScopeEntry(TypedDict, total=False):
    scope: str
    status: str
    granted_on: Optional[str]
    expires_on: Optional[str]


class TeamMembership(TypedDict, total=False):
    id: str
    team_id: str
    member_id: str
    membership_status: str
    consent_scopes: List[ConsentScopeEntry]
    created_at: str
    updated_at: str
    version: int


class ResearchStudy(TypedDict, total=False):
    id: str
    code: str
    title: str
    min_paid_months: int
    enrollment_window_start_on: str
    enrollment_window_end_on: str
    study_status: str
    created_at: str
    updated_at: str
    version: int


class ResearchEnrollment(TypedDict, total=False):
    id: str
    study_id: str
    member_id: str
    enrollment_status: str
    enrolled_on: str
    member_seq: int
    created_at: str
    updated_at: str
    version: int


class ReplacementRequest(TypedDict, total=False):
    id: str
    device_id: str
    reason: str
    request_status: str
    diagnosis: Optional[str]
    replacement_device_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MerchOrderLine(TypedDict, total=False):
    sku: str
    category: str
    unit_price_cents: int
    qty: int


class MerchOrder(TypedDict, total=False):
    id: str
    member_id: str
    lines: List[MerchOrderLine]
    order_status: str
    subtotal_cents: int
    member_discount_cents: int
    bundle_discount_cents: int
    discount_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int
