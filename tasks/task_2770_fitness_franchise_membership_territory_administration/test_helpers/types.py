"""Domain types for the Fitness Franchise Membership & Territory Administration API.

Status enums, role enum and entity TypedDicts mirroring the PRD resource shapes.
Every field name here is the PRD-exact name.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    BRAND_ADMINISTRATOR = "BrandAdministrator"
    FRANCHISE_OWNER = "FranchiseOwner"
    CLUB_MANAGER = "ClubManager"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    BILLING_PARTNER = "BillingPartner"
    MEMBER = "Member"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------


class FranchiseeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"


class TerritoryStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"


class ClubStatus(str, Enum):
    PRE_OPENING = "PRE_OPENING"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class EquipmentComplianceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    NON_COMPLIANT = "NON_COMPLIANT"


class RelocationRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class MembershipPlanTemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class PromotionStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN_BY_BRAND = "WITHDRAWN_BY_BRAND"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CorporateAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AllocationMethod(str, Enum):
    USAGE_SHARE = "USAGE_SHARE"
    EQUAL_SPLIT = "EQUAL_SPLIT"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CANCELLATION_PENDING = "CANCELLATION_PENDING"
    CANCELLED = "CANCELLED"


class DuesStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"
    IN_COLLECTIONS = "IN_COLLECTIONS"
    WRITTEN_OFF = "WRITTEN_OFF"


class TransferRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    COMPLETED = "COMPLETED"


class UsageSettlementStatus(str, Enum):
    OPEN = "OPEN"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class BillingEventType(str, Enum):
    DUES_POSTED = "DUES_POSTED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    WRITE_OFF = "WRITE_OFF"
    TRANSFER_FEE_POSTED = "TRANSFER_FEE_POSTED"
    COLLECTION_PLACED = "COLLECTION_PLACED"


class BillingEventSource(str, Enum):
    BILLING_PARTNER = "BILLING_PARTNER"
    SYSTEM = "SYSTEM"


class RoyaltyReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"


class FacilityInspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    REMEDIATION_WAIVED = "REMEDIATION_WAIVED"
    CLOSED = "CLOSED"


class InspectionVariant(str, Enum):
    STANDARD_CYCLE = "STANDARD_CYCLE"
    ACCELERATED_CYCLE = "ACCELERATED_CYCLE"


class StateCode(str, Enum):
    CA = "CA"
    TX = "TX"
    NY = "NY"


class RelocationDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class PromotionDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class TransferDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class WithdrawnReason(str, Enum):
    FRANCHISEE_PROBATION = "FRANCHISEE_PROBATION"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------


class Franchisee(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    royalty_rate_bps: int
    status: str
    inspection_fail_streak: int
    collections_watch_club_count: int
    disputed_royalty_count: int
    compliance_score: int
    corporate_allocation_cents: int
    national_account_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict):
    id: str
    franchisee_id: str
    center_lat: float
    center_lng: float
    protected_radius_km: float
    state_code: str
    status: str
    encroachment_km: Optional[float]
    relocation_count: int
    created_at: str
    updated_at: str
    version: int


class Club(TypedDict):
    id: str
    territory_id: str
    franchisee_id: str
    name: str
    state_code: str
    lat: float
    lng: float
    opened_on: str
    guest_fee_cents: int
    status: str
    equipment_compliance_state: str
    last_inspection_score: Optional[int]
    active_agreement_count: int
    delinquent_member_count: int
    collections_watch: bool
    settlement_ledger_cents: int
    created_at: str
    updated_at: str
    version: int


class RelocationRequest(TypedDict):
    id: str
    club_id: str
    requested_lat: float
    requested_lng: float
    requested_radius_km: float
    justification: str
    status: str
    revision_count: int
    encroachment_km: Optional[float]
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MembershipPlanTemplate(TypedDict):
    id: str
    code: str
    monthly_dues_cents: int
    initiation_fee_cents: int
    term_months: int
    cancellation_notice_days: int
    floor_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    franchisee_id: str
    plan_template_id: str
    code: str
    discount_pct: float
    starts_on: str
    ends_on: str
    status: str
    reviewed_by_user_id: Optional[str]
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    home_state_code: str
    status: str
    agreement_count: int
    created_at: str
    updated_at: str
    version: int


class CorporateAccount(TypedDict):
    id: str
    name: str
    corporate_credit_pct: float
    allocation_method: str
    status: str
    pool_balance_cents: int
    allocated_cents: int
    lifetime_funded_cents: int
    enrolled_agreement_count: int
    created_at: str
    updated_at: str
    version: int


class MembershipAgreement(TypedDict):
    id: str
    member_id: str
    home_club_id: str
    plan_template_id: str
    promotion_id: Optional[str]
    corporate_account_id: Optional[str]
    multi_club_access: bool
    state_code: str
    signed_on: str
    term_end_on: str
    monthly_dues_base_cents: int
    initiation_fee_cents: int
    cancellation_notice_days: int
    promo_discount_cents: int
    corporate_credit_cents: int
    multi_club_credit_cents: int
    effective_monthly_dues_cents: int
    agreement_status: str
    dues_status: str
    outstanding_balance_cents: int
    dues_paid_cents: int
    delinquency_days: int
    transfer_count: int
    cancellation_requested_on: Optional[str]
    cancellation_effective_on: Optional[str]
    refund_cents: Optional[int]
    early_termination_fee_cents: Optional[int]
    net_settlement_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    agreement_id: str
    from_club_id: str
    to_club_id: str
    reason: str
    status: str
    transfer_fee_cents: Optional[int]
    effective_on: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuestUsageEvent(TypedDict):
    """Append-only visit batch: carries only id + created_at as system fields."""

    id: str
    agreement_id: str
    host_club_id: str
    home_club_id_at_visit: str
    period_month: str
    visit_count: int
    guest_fee_cents_at_visit: int
    usage_fee_cents: int
    settlement_id: Optional[str]
    created_at: str


class UsageSettlement(TypedDict):
    id: str
    period_month: str
    home_club_id: str
    host_club_id: str
    event_count: int
    visit_count: int
    gross_fee_cents: int
    admin_hold_cents: int
    net_before_rebate_cents: int
    rebate_pct: float
    volume_rebate_cents: int
    net_payable_cents: int
    status: str
    posted_on: Optional[str]
    reversed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingEvent(TypedDict):
    """Append-only ledger entry: carries only id + created_at as system fields."""

    id: str
    agreement_id: str
    event_type: str
    amount_cents: int
    occurred_on: str
    due_on: Optional[str]
    source: str
    resulting_outstanding_balance_cents: int
    created_at: str


class RoyaltyReport(TypedDict):
    id: str
    franchisee_id: str
    period_month: str
    reported_member_count: int
    verified_member_count: int
    reported_dues_basis_cents: int
    verified_dues_basis_cents: int
    reported_royalty_cents: int
    royalty_due_cents: int
    variance_pct: float
    status: str
    adjusted_royalty_cents: Optional[int]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FacilityInspection(TypedDict):
    id: str
    club_id: str
    inspection_date: str
    equipment_condition_pts: Optional[int]
    cleanliness_pts: Optional[int]
    safety_pts: Optional[int]
    equipment_age_months_max: Optional[int]
    refresh_cycle_months_applied: Optional[int]
    refresh_pts: Optional[int]
    score: Optional[int]
    variant_applied: Optional[str]
    status: str
    scored_by_user_id: Optional[str]
    waived_by_user_id: Optional[str]
    waiver_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
