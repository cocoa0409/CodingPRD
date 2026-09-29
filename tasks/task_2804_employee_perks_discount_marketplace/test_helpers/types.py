"""Domain types for the Employee Perks & Discount Marketplace API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PARTNER_MANAGER = "PartnerManager"
    MERCHANT = "Merchant"
    EMPLOYER_ADMIN = "EmployerAdmin"
    EMPLOYEE = "Employee"


# ─── Enumerated domain vocabularies ──────────────────────────────────────────

class PerkCategory(str, Enum):
    DINING = "DINING"
    TRAVEL = "TRAVEL"
    WELLNESS = "WELLNESS"
    ELECTRONICS = "ELECTRONICS"
    CHILDCARE = "CHILDCARE"
    EDUCATION = "EDUCATION"
    HOME_SERVICES = "HOME_SERVICES"


class RegionCode(str, Enum):
    CA = "CA"
    TX = "TX"
    NY = "NY"
    WA = "WA"
    IL = "IL"


CATEGORIES = [c.value for c in PerkCategory]
REGION_CODES = [r.value for r in RegionCode]


# ─── Status enums ────────────────────────────────────────────────────────────

class MerchantStatus(str, Enum):
    PROSPECT = "PROSPECT"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROVIDER_PROPOSED = "PROVIDER_PROPOSED"
    MERCHANT_COUNTERED = "MERCHANT_COUNTERED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    TERMINATED = "TERMINATED"


class ProposerRole(str, Enum):
    PARTNER_MANAGER = "PARTNER_MANAGER"
    MERCHANT = "MERCHANT"


class DecisionValue(str, Enum):
    """The `decision` payload of `POST /perks/agreements/{id}/decide`."""

    ACCEPT = "ACCEPT"
    WITHDRAW = "WITHDRAW"


class ReviewDecision(str, Enum):
    """The `decision` payload of `POST /perks/offers/{id}/review`."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class IntegrationStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    FILE_RECEIVED = "FILE_RECEIVED"
    VALIDATED = "VALIDATED"
    SYNCED = "SYNCED"
    STALE = "STALE"


class StorefrontStatus(str, Enum):
    DRAFT = "DRAFT"
    BRANDED = "BRANDED"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"


class ProgramPosture(str, Enum):
    SETUP = "SETUP"
    LIVE = "LIVE"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class EligibilityFileStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LEAVE = "LEAVE"
    TERMINATED = "TERMINATED"


class MembershipStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DiscountType(str, Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


class PlacementTier(str, Enum):
    STANDARD = "STANDARD"
    FEATURED = "FEATURED"


class SlotStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    VOID = "VOID"


class FulfillmentStatus(str, Enum):
    AWAITING = "AWAITING"
    FULFILLED = "FULFILLED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"


class VoidReason(str, Enum):
    MEMBER_CANCELLED = "MEMBER_CANCELLED"
    PROGRAM_FROZEN = "PROGRAM_FROZEN"
    MEMBERSHIP_INELIGIBLE = "MEMBERSHIP_INELIGIBLE"
    VERIFICATION_TTL_EXPIRED = "VERIFICATION_TTL_EXPIRED"


class ReleaseReason(str, Enum):
    AGREEMENT_TERMINATED = "AGREEMENT_TERMINATED"
    OFFER_PAUSED = "OFFER_PAUSED"


class DisputeReason(str, Enum):
    NOT_HONORED = "NOT_HONORED"
    WRONG_DISCOUNT = "WRONG_DISCOUNT"
    OFFER_EXPIRED = "OFFER_EXPIRED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    OTHER = "OTHER"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    MERCHANT_RESPONDED = "MERCHANT_RESPONDED"
    INFO_REQUESTED = "INFO_REQUESTED"
    RESOLVED_MERCHANT_FAULT = "RESOLVED_MERCHANT_FAULT"
    RESOLVED_NO_FAULT = "RESOLVED_NO_FAULT"


class DisputeOutcome(str, Enum):
    MERCHANT_FAULT = "MERCHANT_FAULT"
    NO_FAULT = "NO_FAULT"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    REOPENED = "REOPENED"
    PAID = "PAID"


class StatementBasis(str, Enum):
    ACCRUAL = "ACCRUAL"
    CASH = "CASH"


class LedgerEntryType(str, Enum):
    COMMISSION_ACCRUAL = "COMMISSION_ACCRUAL"
    EMPLOYER_SHARE = "EMPLOYER_SHARE"
    COMMISSION_REVERSAL = "COMMISSION_REVERSAL"
    EMPLOYER_SHARE_REVERSAL = "EMPLOYER_SHARE_REVERSAL"
    PLACEMENT_FEE = "PLACEMENT_FEE"
    PLACEMENT_FEE_REFUND = "PLACEMENT_FEE_REFUND"
    DISPUTE_CREDIT = "DISPUTE_CREDIT"
    DISPUTE_CREDIT_RECOVERY = "DISPUTE_CREDIT_RECOVERY"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# Merchants, partner agreements, employers, eligibility files, memberships,
# offers, placement slots, redemptions, disputes and revenue share statements
# all carry id / created_at / updated_at / version (PRD §2.5).
# Negotiation rounds and ledger entries are append-only: they carry only
# id and created_at.

class Merchant(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    primary_category: str
    region_codes: List[str]
    status: str
    fault_event_count: int
    fulfillment_failure_score: int
    accrued_commission_payable_cents: int
    active_agreement_count: int
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartnerAgreement(TypedDict):
    id: str
    merchant_id: str
    category: str
    region_code: str
    status: str
    round_count: int
    commission_rate_bps: Optional[int]
    placement_fee_base_cents: Optional[int]
    employer_revenue_share_bps: Optional[int]
    exclusivity_requested: bool
    exclusivity_window_start: Optional[str]
    exclusivity_window_end: Optional[str]
    exclusivity_granted: bool
    accepted_by_role: Optional[str]
    activated_at: Optional[str]
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NegotiationRound(TypedDict):
    # Append-only: no updated_at, no version (PRD §2.5).
    id: str
    agreement_id: str
    round_number: int
    proposer_role: str
    commission_rate_bps: int
    placement_fee_base_cents: int
    employer_revenue_share_bps: int
    exclusivity_window_start: Optional[str]
    exclusivity_window_end: Optional[str]
    note: Optional[str]
    created_at: str


class Employer(TypedDict):
    id: str
    name: str
    region_code: str
    employee_count_declared: int
    revenue_share_enabled: bool
    privacy_min_cohort_size: int
    integration_status: str
    storefront_status: str
    program_posture: str
    brand_color_hex: Optional[str]
    logo_url: Optional[str]
    hero_headline: Optional[str]
    featured_categories: Optional[List[str]]
    eligible_headcount: int
    last_sync_at: Optional[str]
    accrued_share_cents: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityFile(TypedDict):
    id: str
    employer_id: str
    effective_from: str
    checksum: str
    record_count: int
    invalid_record_count: int
    valid_record_count: int
    status: str
    rejection_reason: Optional[str]
    created_membership_count: int
    updated_membership_count: int
    suspended_membership_count: int
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmployeeMembership(TypedDict):
    id: str
    employer_id: str
    source_file_id: str
    external_employee_ref: str
    employment_status: str
    status: str
    region_code: str
    eligibility_valid_from: str
    eligibility_valid_until: str
    redemption_count_7d: int
    redemption_count_30d: int
    last_employment_change_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    agreement_id: str
    merchant_id: str
    title: str
    category: str
    discount_type: str
    discount_value_bps: Optional[int]
    discount_value_cents: Optional[int]
    min_spend_cents: int
    region_codes: List[str]
    window_start: str
    window_end: str
    inventory_limit: Optional[int]
    inventory_reserved: int
    inventory_redeemed: int
    per_member_limit: int
    sold_out: bool
    status: str
    review_note: Optional[str]
    paused_reason: Optional[str]
    expired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlacementSlot(TypedDict):
    id: str
    offer_id: str
    employer_id: str
    placement_tier: str
    slot_window_start: str
    slot_window_end: str
    slot_duration_days: int
    base_fee_cents: int
    reach_surcharge_bps: int
    reach_surcharge_cents: int
    gross_fee_cents: int
    volume_discount_bps: int
    volume_discount_cents: int
    placement_fee_cents: int
    status: str
    confirmed_at: Optional[str]
    released_at: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Redemption(TypedDict):
    id: str
    offer_id: str
    membership_id: str
    employer_id: str
    merchant_id: str
    statement_id: Optional[str]
    intended_gross_amount_cents: int
    gross_amount_cents: Optional[int]
    discount_amount_cents: Optional[int]
    net_charged_cents: Optional[int]
    commission_amount_cents: Optional[int]
    employer_share_cents: Optional[int]
    provider_net_cents: Optional[int]
    verification_expires_at: str
    verification_status: str
    fulfillment_status: str
    screening_risk_score: Optional[int]
    audit_risk_score: Optional[int]
    risk_block_reason: Optional[str]
    verified_at: Optional[str]
    fulfilled_at: Optional[str]
    refunded_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    redemption_id: str
    raised_by_membership_id: str
    merchant_id: str
    reason: str
    description: str
    status: str
    response_note: Optional[str]
    remedy_offered_cents: Optional[int]
    info_request_count: int
    response_deadline_at: str
    outcome_credit_cents: Optional[int]
    default_judged: bool
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevenueShareStatement(TypedDict):
    id: str
    employer_id: str
    period_start: str
    period_end: str
    basis: str
    included_redemption_count: int
    gross_commission_cents: int
    employer_share_cents: int
    provider_retained_cents: int
    reversal_adjustment_cents: int
    status: str
    finalized_at: Optional[str]
    reopened_at: Optional[str]
    reopen_reason: Optional[str]
    paid_at: Optional[str]
    payment_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    # Append-only: no updated_at, no version (PRD §2.5).
    id: str
    redemption_id: Optional[str]
    placement_slot_id: Optional[str]
    statement_id: Optional[str]
    employer_id: Optional[str]
    merchant_id: str
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str
