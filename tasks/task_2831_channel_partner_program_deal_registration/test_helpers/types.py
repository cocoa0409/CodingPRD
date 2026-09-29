"""Domain types for the channel partner program API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------- roles


class UserRole(str, Enum):
    PARTNER = "Partner"
    CHANNEL_OPS_ANALYST = "ChannelOpsAnalyst"
    CHANNEL_DIRECTOR = "ChannelDirector"
    DIRECT_SALES_REP = "DirectSalesRep"


# ---------------------------------------------------------------- enums


class PartnerType(str, Enum):
    DISTRIBUTOR = "DISTRIBUTOR"
    RESELLER = "RESELLER"


class PartnerTier(str, Enum):
    REGISTERED = "REGISTERED"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class PartnerTierStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class PortalEntitlementLevel(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ELITE = "ELITE"


class CertificationTrack(str, Enum):
    SALES_PRO = "SALES_PRO"
    TECH_ASSOCIATE = "TECH_ASSOCIATE"
    TECH_EXPERT = "TECH_EXPERT"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class RegionCode(str, Enum):
    NA = "NA"
    EMEA = "EMEA"
    APAC = "APAC"


class CoverageState(str, Enum):
    OPEN_CHANNEL = "OPEN_CHANNEL"
    CHANNEL_PROTECTED = "CHANNEL_PROTECTED"
    NAMED_DIRECT = "NAMED_DIRECT"
    DIRECT_LOCKED = "DIRECT_LOCKED"


class ProductLine(str, Enum):
    PLATFORM_SUITE = "PLATFORM_SUITE"
    ANALYTICS_ADDON = "ANALYTICS_ADDON"
    SUPPORT_SERVICES = "SUPPORT_SERVICES"


class ExclusivityScope(str, Enum):
    FULL = "FULL"
    PRODUCT_LINE = "PRODUCT_LINE"


class MappingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    CONFLICT_HELD = "CONFLICT_HELD"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    CONVERTED = "CONVERTED"


class ConflictType(str, Enum):
    PARTNER_VS_PARTNER = "PARTNER_VS_PARTNER"
    PARTNER_VS_DIRECT = "PARTNER_VS_DIRECT"


class ConflictStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED_TIER1 = "ESCALATED_TIER1"
    ESCALATED_TIER2 = "ESCALATED_TIER2"
    RESOLVED_PARTNER = "RESOLVED_PARTNER"
    RESOLVED_DIRECT = "RESOLVED_DIRECT"
    RESOLVED_SPLIT = "RESOLVED_SPLIT"


class RecommendationLabel(str, Enum):
    GRANT_SUBJECT = "GRANT_SUBJECT"
    GRANT_COUNTER = "GRANT_COUNTER"
    RELEASE_TO_DIRECT = "RELEASE_TO_DIRECT"
    DISMISS = "DISMISS"


class AppliedVariant(str, Enum):
    REGISTRATION_FIRST = "REGISTRATION_FIRST"
    COVERAGE_FIRST = "COVERAGE_FIRST"


class SpecialPricingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class MdfAllocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MdfActivityType(str, Enum):
    EVENT = "EVENT"
    DIGITAL_CAMPAIGN = "DIGITAL_CAMPAIGN"
    CONTENT_SYNDICATION = "CONTENT_SYNDICATION"


class ClaimValidationState(str, Enum):
    SUBMITTED = "SUBMITTED"
    PROOF_REQUESTED = "PROOF_REQUESTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ClaimSettlementState(str, Enum):
    UNPAID = "UNPAID"
    APPROVED_FOR_PAYMENT = "APPROVED_FOR_PAYMENT"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class ProofDocType(str, Enum):
    INVOICE = "INVOICE"
    ATTENDEE_LIST = "ATTENDEE_LIST"
    SCREENSHOT = "SCREENSHOT"
    LEAD_REPORT = "LEAD_REPORT"


class OrderType(str, Enum):
    STOCKING = "STOCKING"
    DROP_SHIP = "DROP_SHIP"


class VolumeBand(str, Enum):
    NONE = "NONE"
    MID = "MID"
    HIGH = "HIGH"


class OrderInvoiceStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    CREDITED = "CREDITED"


class PerformanceReviewStatus(str, Enum):
    PREPARED = "PREPARED"
    FINDINGS_OPEN = "FINDINGS_OPEN"
    REMEDIATED = "REMEDIATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------- entities
# Every resource type carries id, created_at, updated_at and version.


class Partner(TypedDict):
    id: str
    company_name: str
    partner_type: str
    tier: str
    tier_status: str
    marketing_commitment_cents: int
    cert_credit_total: int
    trailing_revenue_cents: int
    marketing_qualified_spend_cents: int
    marketing_attainment_pct: float
    portal_entitlement_level: str
    open_conflict_count: int
    standing_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificationRecord(TypedDict):
    id: str
    partner_id: str
    engineer_name: str
    track: str
    credit_weight: int
    status: str
    issued_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    account_name: str
    region_code: str
    coverage_state: str
    protected_until: Optional[str]
    protected_partner_id: Optional[str]
    protected_product_line: Optional[str]
    direct_pursuit_owner_id: Optional[str]
    direct_pursuit_declared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountMapping(TypedDict):
    id: str
    partner_id: str
    account_id: str
    product_line: str
    exclusivity_scope: str
    effective_from: str
    effective_until: str
    mapping_status: str
    counter_round: int
    activated_at: Optional[str]
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DealRegistration(TypedDict):
    id: str
    partner_id: str
    account_id: str
    product_line: str
    expected_amount_cents: int
    expected_close_date: str
    supersedes_registration_id: Optional[str]
    status: str
    submitted_at: Optional[str]
    approved_at: Optional[str]
    exclusivity_start_at: Optional[str]
    exclusivity_end_at: Optional[str]
    protection_days: Optional[int]
    registration_margin_uplift_pct: float
    revision_round: int
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConflictCase(TypedDict):
    id: str
    account_id: str
    subject_registration_id: str
    counter_registration_id: Optional[str]
    conflict_type: str
    status: str
    detected_at: str
    escalation_level: int
    applied_variant: str
    recommended_resolution: str
    recommended_resolution_registration_first: str
    recommended_resolution_coverage_first: str
    resolution_note: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecialPricingRequest(TypedDict):
    id: str
    registration_id: str
    requested_extra_margin_pct: float
    justification: str
    status: str
    approved_extra_margin_pct: Optional[float]
    expires_at: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MdfAllocation(TypedDict):
    id: str
    partner_id: str
    period_start: str
    period_end: str
    basis_revenue_cents: int
    allocated_cents: int
    committed_cents: int
    paid_cents: int
    expired_cents: int
    available_cents: int
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MdfClaim(TypedDict):
    id: str
    allocation_id: str
    activity_type: str
    requested_cents: int
    validation_state: str
    settlement_state: str
    matched_total_cents: Optional[int]
    approved_cents: Optional[int]
    proof_round: int
    validated_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProofOfPerformance(TypedDict):
    id: str
    claim_id: str
    doc_type: str
    spend_amount_cents: int
    audience_reach: Optional[int]
    verified: bool
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    matched_line_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OrderInvoice(TypedDict):
    id: str
    partner_id: str
    registration_id: Optional[str]
    order_type: str
    list_amount_cents: int
    margin_pct: float
    volume_band: str
    invoice_amount_cents: int
    margin_value_cents: int
    credit_memo_cents: int
    status: str
    invoiced_at: Optional[str]
    credit_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceReview(TypedDict):
    id: str
    partner_id: str
    period_start: str
    period_end: str
    findings_count: int
    remediation_due_at: Optional[str]
    provisional_cert_credit: int
    provisional_revenue_cents: int
    provisional_score: float
    recommended_tier: str
    final_cert_credit: Optional[int]
    final_revenue_cents: Optional[int]
    final_score: Optional[float]
    approved_tier: Optional[str]
    marketing_attainment_pct: float
    status: str
    prepared_by_user_id: str
    decided_by_user_id: Optional[str]
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
