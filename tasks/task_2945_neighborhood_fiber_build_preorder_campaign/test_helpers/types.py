"""Domain types for the Neighborhood Fiber Build & Preorder Campaign API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
declares them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    PERMIT_OFFICE = "PermitOffice"
    UTILITY_OPERATOR = "UtilityOperator"
    INSTALL_COORDINATOR = "InstallCoordinator"
    CLAIMS_ASSESSOR = "ClaimsAssessor"
    CLAIMS_APPROVER = "ClaimsApprover"
    SUBSCRIBER = "Subscriber"
    MDU_OWNER = "MduOwner"


class AccountType(str, Enum):
    RESIDENT = "RESIDENT"
    PROPERTY_OWNER = "PROPERTY_OWNER"
    BUSINESS = "BUSINESS"


class CampaignStatus(str, Enum):
    PREREG_OPEN = "PREREG_OPEN"
    PREREG_EXTENDED = "PREREG_EXTENDED"
    QUALIFIED = "QUALIFIED"
    NOT_QUALIFIED = "NOT_QUALIFIED"


class ConstructionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    SEQUENCED = "SEQUENCED"
    IN_CONSTRUCTION = "IN_CONSTRUCTION"
    SUSPENDED = "SUSPENDED"
    SERVICE_READY = "SERVICE_READY"


class ReadinessPosture(str, Enum):
    BLOCKED = "BLOCKED"
    PERMIT_PENDING = "PERMIT_PENDING"
    POLE_PENDING = "POLE_PENDING"
    SUSPENDED = "SUSPENDED"
    READY = "READY"


class SuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    POLE_DENIED = "POLE_DENIED"
    PERMIT_EXPIRED = "PERMIT_EXPIRED"


class Serviceability(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    SERVICEABLE = "SERVICEABLE"
    CONDITIONAL_MDU = "CONDITIONAL_MDU"
    NOT_SERVICEABLE = "NOT_SERVICEABLE"


class NotServiceableReason(str, Enum):
    NO_ROW_ACCESS = "NO_ROW_ACCESS"
    EXCESSIVE_DISTANCE = "EXCESSIVE_DISTANCE"
    MDU_AGREEMENT_UNAVAILABLE = "MDU_AGREEMENT_UNAVAILABLE"
    BUILD_NOT_QUALIFIED = "BUILD_NOT_QUALIFIED"


class ExceptionStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class ExceptionAction(str, Enum):
    REQUEST = "REQUEST"
    GRANT = "GRANT"
    DENY = "DENY"


class DwellingType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    MDU = "MDU"


class MduAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class OwnerResponse(str, Enum):
    SIGN = "SIGN"
    DECLINE = "DECLINE"
    COUNTER = "COUNTER"


class PermitType(str, Enum):
    ROW = "ROW"
    TRAFFIC_CONTROL = "TRAFFIC_CONTROL"
    ENVIRONMENTAL = "ENVIRONMENTAL"


class PermitApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PermitDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class PoleRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SURVEYED = "SURVEYED"
    ACCEPTED = "ACCEPTED"
    ATTACHED = "ATTACHED"
    DENIED = "DENIED"


class PoleDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DENY = "DENY"


class PoleDenialReason(str, Enum):
    INSUFFICIENT_CLEARANCE = "INSUFFICIENT_CLEARANCE"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    CAPACITY_FULL = "CAPACITY_FULL"


class PlanTier(str, Enum):
    BASIC_300 = "BASIC_300"
    GIGABIT_1000 = "GIGABIT_1000"
    MULTIGIG_2000 = "MULTIGIG_2000"


class DropMethod(str, Enum):
    BURY = "BURY"
    AERIAL = "AERIAL"


class PreorderStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"
    LAPSED = "LAPSED"


class DepositStatus(str, Enum):
    HELD = "HELD"
    REFUNDED = "REFUNDED"
    APPLIED = "APPLIED"
    FORFEITED = "FORFEITED"


class LapseReason(str, Enum):
    ZONE_NOT_QUALIFIED = "ZONE_NOT_QUALIFIED"
    ADDRESS_NOT_COUNTED = "ADDRESS_NOT_COUNTED"


class CrewType(str, Enum):
    BURY = "BURY"
    AERIAL = "AERIAL"
    RESTORATION = "RESTORATION"


class AppointmentType(str, Enum):
    DROP_BURY = "DROP_BURY"
    AERIAL_DROP = "AERIAL_DROP"
    RESTORATION_FOLLOWUP = "RESTORATION_FOLLOWUP"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AppointmentOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AppointmentCancellationReason(str, Enum):
    SUBSCRIBER_REQUEST = "SUBSCRIBER_REQUEST"
    CREW_UNAVAILABLE = "CREW_UNAVAILABLE"
    ZONE_SUSPENDED = "ZONE_SUSPENDED"


class DamageType(str, Enum):
    LAWN = "LAWN"
    IRRIGATION = "IRRIGATION"
    DRIVEWAY = "DRIVEWAY"
    UTILITY_LINE = "UTILITY_LINE"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    PAID = "PAID"
    DENIED = "DENIED"


class AssessmentVariant(str, Enum):
    STANDARD_SCHEDULE = "STANDARD_SCHEDULE"
    LATE_FILING_SCHEDULE = "LATE_FILING_SCHEDULE"


class ClaimDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class FallbackTechnology(str, Enum):
    FIXED_WIRELESS = "FIXED_WIRELESS"
    DSL_PARTNER = "DSL_PARTNER"
    SATELLITE_PARTNER = "SATELLITE_PARTNER"


class FallbackOptionStatus(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class FallbackOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class FallbackOfferResponse(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class LedgerEntryType(str, Enum):
    DEPOSIT_HELD = "DEPOSIT_HELD"
    DEPOSIT_REFUNDED = "DEPOSIT_REFUNDED"
    DEPOSIT_APPLIED = "DEPOSIT_APPLIED"
    DEPOSIT_FORFEITED = "DEPOSIT_FORFEITED"
    CLAIM_PAYOUT = "CLAIM_PAYOUT"


# --- Entity shapes -----------------------------------------------------------
# The thirteen versioned entity types carry id, created_at, updated_at, version.
# LedgerEntry is append-only and carries ONLY id and created_at.


class Campaign(TypedDict):
    id: str
    name: str
    city: str
    prereg_window_open_at: str
    prereg_window_close_at: str
    default_threshold_pct: float
    deposit_amount_cents: int
    max_deadline_extensions: int
    extension_grant_days: int
    claim_filing_window_days: int
    restoration_sla_days: int
    late_filing_factor: float
    zone_count: int
    created_at: str
    updated_at: str
    version: int


class BuildZone(TypedDict):
    id: str
    campaign_id: str
    name: str
    zone_code: str
    household_count: int
    threshold_pct: float
    required_permit_types: List[str]
    max_concurrent_bury_ops: int
    campaign_status: str
    construction_status: str
    prereg_deadline_at: str
    extension_count: int
    cumulative_extension_days: int
    suspension_reason: Optional[str]
    prereg_rate_pct: float
    provisional_qualifying_count: int
    final_qualifying_count: Optional[int]
    final_rate_pct: Optional[float]
    make_ready_cost_cents: int
    readiness_score: Optional[float]
    readiness_posture: str
    build_sequence_index: Optional[int]
    outstanding_restoration_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceAddress(TypedDict):
    id: str
    build_zone_id: str
    street_address: str
    dwelling_type: str
    unit_count: int
    distance_to_node_m: int
    serviceability: str
    not_serviceable_reason: Optional[str]
    serviceability_determined_at: Optional[str]
    exception_status: str
    exception_reason: Optional[str]
    counts_toward_threshold: bool
    active_fallback_technology: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    account_type: str
    deposit_held_cents: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class MduOwnerAgreement(TypedDict):
    id: str
    service_address_id: str
    owner_account_id: str
    access_fee_cents: int
    countered_fee_cents: Optional[int]
    max_counter_rounds: int
    counter_round: int
    offer_round: int
    status: str
    expires_at: str
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    build_zone_id: str
    permit_type: str
    valid_days: int
    max_resubmissions: int
    submission_round: int
    status: str
    rejection_reason: Optional[str]
    approved_at: Optional[str]
    expires_at: Optional[str]
    reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PoleAttachmentRequest(TypedDict):
    id: str
    build_zone_id: str
    utility_owner: str
    pole_count: int
    status: str
    make_ready_cost_cents: int
    survey_completed_at: Optional[str]
    denial_reason: Optional[str]
    attached_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Preorder(TypedDict):
    id: str
    build_zone_id: str
    service_address_id: str
    account_id: str
    plan_tier: str
    unit_designator: Optional[str]
    preorder_status: str
    deposit_status: str
    deposit_amount_cents: int
    lapse_reason: Optional[str]
    make_ready_share_cents: Optional[int]
    drop_method: Optional[str]
    conversion_pre_discount_total_cents: Optional[int]
    conversion_discount_cents: Optional[int]
    conversion_total_due_cents: Optional[int]
    converted_at: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallCrew(TypedDict):
    id: str
    name: str
    crew_type: str
    travel_buffer_minutes: int
    daily_capacity_minutes: int
    booked_minutes_total: int
    scheduled_appointment_count: int
    created_at: str
    updated_at: str
    version: int


class InstallAppointment(TypedDict):
    id: str
    preorder_id: str
    crew_id: str
    appointment_type: str
    parent_appointment_id: Optional[str]
    window_start_at: str
    window_end_at: str
    occupied_minutes: int
    status: str
    completed_at: Optional[str]
    restoration_required: bool
    restoration_due_by: Optional[str]
    restoration_satisfied_at: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    install_appointment_id: str
    service_address_id: str
    claimant_account_id: str
    damage_type: str
    claimed_amount_cents: int
    description: Optional[str]
    status: str
    filed_at: str
    assessed_amount_cents: Optional[int]
    assessment_variant: Optional[str]
    assessed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    paid_at: Optional[str]
    max_appeals: int
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class FallbackOption(TypedDict):
    id: str
    campaign_id: str
    technology: str
    min_downstream_mbps: int
    monthly_price_cents: int
    max_serviceable_distance_m: int
    priority_rank: int
    supports_mdu: bool
    option_status: str
    created_at: str
    updated_at: str
    version: int


class FallbackOffer(TypedDict):
    id: str
    service_address_id: str
    fallback_option_id: str
    account_id: str
    technology: str
    min_downstream_mbps: int
    monthly_price_cents: int
    status: str
    offered_at: str
    expires_at: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    """Append-only: carries only id and created_at beyond its own columns."""

    id: str
    account_id: str
    entry_type: str
    amount_cents: int
    memo: Optional[str]
    occurred_at: str
    preorder_id: Optional[str]
    damage_claim_id: Optional[str]
    created_at: str
