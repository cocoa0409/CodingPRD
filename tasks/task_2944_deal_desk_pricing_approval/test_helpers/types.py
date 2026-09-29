"""Domain types: status enums, role enum and entity TypedDicts.

Twelve record types carry `updated_at` and `version`. Three record types —
the approval matrix row, the product quantity band and the bundle rule — are
pure configuration rows carrying only `id` and `created_at`; their TypedDicts
deliberately omit `updated_at` and `version`.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SALES_REP = "SalesRep"
    DEAL_DESK_ANALYST = "DealDeskAnalyst"
    SALES_DIRECTOR = "SalesDirector"
    VP_SALES = "VPSales"
    CFO = "CFO"
    LEGAL_COUNSEL = "LegalCounsel"
    REVENUE_ACCOUNTANT = "RevenueAccountant"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLES = [r.value for r in UserRole]

APPROVER_ROLES = [
    UserRole.DEAL_DESK_ANALYST.value,
    UserRole.SALES_DIRECTOR.value,
    UserRole.VP_SALES.value,
    UserRole.CFO.value,
]


class DeskPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ProductType(str, Enum):
    SUBSCRIPTION_LICENSE = "SUBSCRIPTION_LICENSE"
    USAGE_METERED = "USAGE_METERED"
    PROFESSIONAL_SERVICES = "PROFESSIONAL_SERVICES"
    SUPPORT_PLAN = "SUPPORT_PLAN"


class RevRecCategory(str, Enum):
    RATABLE = "RATABLE"
    POINT_IN_TIME = "POINT_IN_TIME"
    USAGE_AS_INCURRED = "USAGE_AS_INCURRED"


class AccountSegment(str, Enum):
    ENTERPRISE = "ENTERPRISE"
    MID_MARKET = "MID_MARKET"
    SMB = "SMB"


class CreditStatus(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    HOLD = "HOLD"


class BillingFrequency(str, Enum):
    ANNUAL = "ANNUAL"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    QUARTERLY = "QUARTERLY"
    MONTHLY = "MONTHLY"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    BOOKED = "BOOKED"


class ArrangementType(str, Enum):
    SINGLE_ELEMENT = "SINGLE_ELEMENT"
    MULTI_ELEMENT = "MULTI_ELEMENT"
    USAGE_BASED_HYBRID = "USAGE_BASED_HYBRID"


class TermCategory(str, Enum):
    PAYMENT_TERMS = "PAYMENT_TERMS"
    SLA_COMMITMENT = "SLA_COMMITMENT"
    INDEMNITY_CAP = "INDEMNITY_CAP"
    TERMINATION_FOR_CONVENIENCE = "TERMINATION_FOR_CONVENIENCE"
    PRICE_HOLD_RENEWAL = "PRICE_HOLD_RENEWAL"


class TermReviewState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ExceptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    RELEASED = "RELEASED"


class RevRecStatus(str, Enum):
    ASSESSED = "ASSESSED"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"


class ApprovalRequestStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DiscountTrackState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class TermsTrackState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_LEGAL = "PENDING_LEGAL"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class SlaState(str, Enum):
    ON_TRACK = "ON_TRACK"
    BREACHED = "BREACHED"
    MET = "MET"


class StepDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class DelegationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class OrderFormStatus(str, Enum):
    GENERATED = "GENERATED"
    OUT_FOR_SIGNATURE = "OUT_FOR_SIGNATURE"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    BOOKED = "BOOKED"
    VOID = "VOID"


# ---------------------------------------------------------------------------
# Entity shapes. The twelve versioned record types carry id + created_at +
# updated_at + version; the three configuration row types carry only
# id + created_at.
# ---------------------------------------------------------------------------

class DeskPolicy(TypedDict):
    id: str
    name: str
    status: str
    margin_floor_pct: float
    absolute_margin_floor_pct: float
    quote_validity_days: int
    standard_payment_terms_days: int
    uplift_rate_per_30_days: float
    max_stack_discount_pct: float
    volume_rebate_tier1_min_cents: int
    volume_rebate_tier1_pct: float
    volume_rebate_tier2_min_cents: int
    volume_rebate_tier2_pct: float
    surge_window_days: int
    surge_sla_multiplier: float
    price_hold_cooldown_days: int
    exception_allowance_cents: int
    terms_review_risk_threshold: float
    terms_cfo_risk_threshold: float
    activated_at: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovalTier(TypedDict):
    """Approval matrix row — configuration only: no updated_at, no version."""
    id: str
    desk_policy_id: str
    tier_level: int
    min_discount_pct: float
    max_discount_pct: float
    required_role: str
    sla_hours: int
    max_delegation_levels: int
    created_at: str


class Product(TypedDict):
    id: str
    sku: str
    name: str
    product_type: str
    list_unit_price_cents: int
    unit_cost_cents: int
    rev_rec_category: str
    min_term_months: int
    created_at: str
    updated_at: str
    version: int


class VolumeTier(TypedDict):
    """Product quantity band — configuration only: no updated_at, no version."""
    id: str
    product_id: str
    tier_level: int
    min_quantity: int
    max_quantity: Optional[int]
    tier_discount_pct: float
    created_at: str


class BundleRule(TypedDict):
    """Bundle rule — configuration only: no updated_at, no version."""
    id: str
    anchor_product_id: str
    attached_product_id: str
    bundle_discount_pct: float
    min_attach_quantity_ratio: float
    created_at: str


class Account(TypedDict):
    id: str
    name: str
    segment: str
    region: str
    existing_arr_cents: int
    credit_status: str
    credit_note: Optional[str]
    booked_arr_cents: int
    exception_allowance_used_cents: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    account_id: str
    desk_policy_id: str
    title: str
    owner_rep_user_id: str
    status: str
    term_months: int
    payment_terms_days: int
    billing_frequency: str
    list_total_cents: int
    cost_total_cents: int
    provisional_net_total_cents: int
    final_net_total_cents: int
    volume_rebate_cents: int
    payment_terms_uplift_cents: int
    provisional_blended_discount_pct: float
    final_blended_discount_pct: float
    provisional_margin_pct: float
    final_margin_pct: float
    required_approval_level: int
    terms_risk_score_aggregate: float
    terms_risk_score_dominant: float
    arrangement_type: str
    policy_revalidation_required: bool
    pinned_policy_version: Optional[int]
    renegotiated_from_quote_id: Optional[str]
    revision_count: int
    renegotiation_count: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    booked_at: Optional[str]
    expires_at: str
    booked_arr_cents: int
    booked_tcv_cents: int
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict):
    id: str
    quote_id: str
    product_id: str
    quantity: int
    requested_discount_pct: float
    unit_list_price_cents: int
    unit_cost_cents: int
    rev_rec_category: str
    extended_list_cents: int
    extended_cost_cents: int
    volume_tier_level_applied: int
    bundle_discount_applied_pct: float
    effective_stack_discount_pct: float
    provisional_net_cents: int
    final_net_cents: int
    created_at: str
    updated_at: str
    version: int


class NonStandardTerm(TypedDict):
    id: str
    quote_id: str
    term_category: str
    requested_numeric_value: float
    requested_text: Optional[str]
    hold_product_id: Optional[str]
    hold_start_date: Optional[str]
    hold_end_date: Optional[str]
    severity_factor: float
    risk_contribution: float
    requires_cfo_cosign: bool
    review_state: str
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]
    reviewer_note: Optional[str]
    cfo_cosigned_at: Optional[str]
    cfo_cosigned_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompetitiveException(TypedDict):
    id: str
    quote_id: str
    competitor_name: str
    competitor_quoted_total_cents: int
    evidence_reference: str
    justification: str
    status: str
    documented_by_user_id: str
    allowance_consumed_cents: int
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevRecAssessment(TypedDict):
    id: str
    quote_id: str
    arrangement_type: str
    usage_excluded_cents: int
    allocable_amount_cents: int
    allocation_residual_cents: int
    allocation_lines: List[dict]
    status: str
    snapshot_quote_version: int
    assessed_by_user_id: Optional[str]
    assessed_at: Optional[str]
    assessment_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovalRequest(TypedDict):
    id: str
    quote_id: str
    status: str
    required_level: int
    current_level: int
    discount_track_state: str
    terms_track_state: str
    requires_cfo_cosign: bool
    escalation_count: int
    at_backstop: bool
    sla_state: str
    submitted_at: str
    decided_at: Optional[str]
    total_turnaround_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ApprovalStep(TypedDict):
    id: str
    approval_request_id: str
    level: int
    assigned_role: str
    decision: str
    escalated_from_step_level: Optional[int]
    in_surge_window: bool
    sla_hours_effective: float
    sla_due_at: str
    delegation_grant_id: Optional[str]
    acting_user_id: Optional[str]
    decided_at: Optional[str]
    turnaround_hours: Optional[float]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DelegationGrant(TypedDict):
    id: str
    grantor_user_id: str
    grantee_user_id: str
    tier_level: int
    max_discount_pct: float
    starts_at: str
    ends_at: str
    status: str
    used_step_count: int
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderForm(TypedDict):
    id: str
    quote_id: str
    signer_name: str
    signer_email: str
    status: str
    generated_from_quote_version: int
    sent_at: Optional[str]
    signed_at: Optional[str]
    signed_by_name: Optional[str]
    declined_at: Optional[str]
    booked_at: Optional[str]
    booked_arr_cents: int
    booked_tcv_cents: int
    voided_at: Optional[str]
    void_reason: Optional[str]
    reversal_reason: Optional[str]
    booking_reversed_at: Optional[str]
    booking_reversal_count: int
    created_at: str
    updated_at: str
    version: int
