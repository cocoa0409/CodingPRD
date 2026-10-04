"""Domain types for the fractional collectible securitization platform.

Entity TypedDicts, status enums and the role enum, taken from the PRD's
resource definitions and state machines.

Note on the shared identity block: the primary resources (Artist, Investor,
Artwork, Offering, Subscription, CustodyRecord, HoldingDecision, TransferOrder,
Lot, InsurancePolicy, PlatformAccount) carry `id`, `created_at`, `updated_at`
and `version`. The five append-mostly child record types (ArtworkAssetReport,
Appraisal, OfferingReport, FeeAccrual, Distribution) carry only `id` and
`created_at` -- they expose no `updated_at` and no `version` at all.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ── Role enum ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    INVESTOR = "Investor"
    ISSUER_OPS = "IssuerOps"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRANSFER_AGENT = "TransferAgent"
    PLATFORM_ADMIN = "PlatformAdmin"
    SYSTEM = "System"


# ── Status enums ─────────────────────────────────────────────────────────────

class ArtworkStatus(str, Enum):
    APPRAISED = "APPRAISED"
    AUTHENTICATED = "AUTHENTICATED"
    OFFERING_PENDING = "OFFERING_PENDING"
    UNDER_OFFERING = "UNDER_OFFERING"
    HELD = "HELD"
    SALE_PENDING = "SALE_PENDING"
    SOLD = "SOLD"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    QUALIFICATION_FILED = "QUALIFICATION_FILED"
    ALLOCATED = "ALLOCATED"
    HELD = "HELD"
    SALE_PENDING = "SALE_PENDING"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"
    OFFERING_ABANDONED = "OFFERING_ABANDONED"


class SubscriptionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SUITABILITY_SCREENED = "SUITABILITY_SCREENED"
    SUBSCRIBED = "SUBSCRIBED"
    REALLOCATED = "REALLOCATED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class CustodyRecordStatus(str, Enum):
    PENDING = "PENDING"
    IN_CUSTODY = "IN_CUSTODY"
    RELEASED = "RELEASED"


class HoldingDecisionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class TransferOrderStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    EXECUTED = "EXECUTED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class InsurancePolicyStatus(str, Enum):
    PENDING = "PENDING"
    FORCE = "FORCE"
    LAPSED = "LAPSED"


class InvestorSuitabilityStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DistributionStatus(str, Enum):
    CALCULATED = "CALCULATED"
    PAID = "PAID"


class AccrualType(str, Enum):
    MANAGEMENT = "MANAGEMENT"
    PROFIT_PARTICIPATION = "PROFIT_PARTICIPATION"


class AppraisalMethod(str, Enum):
    AUCTION_COMPARABLE = "AUCTION_COMPARABLE"
    MARKET_INDEX = "MARKET_INDEX"
    PRIVATE_SALE = "PRIVATE_SALE"


class AssetReportType(str, Enum):
    AUTHENTICATION = "AUTHENTICATION"
    PROVENANCE = "PROVENANCE"
    CONDITION_SURVEY = "CONDITION_SURVEY"


class AssetReportOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    PENDING = "PENDING"


class LotType(str, Enum):
    STORAGE = "STORAGE"
    INSURANCE = "INSURANCE"
    CONSERVATION = "CONSERVATION"


# ── Entity TypedDicts ────────────────────────────────────────────────────────

class Artist(TypedDict, total=False):
    id: str
    legal_name: str
    attribution_status: str
    nationality_country_code: str
    birth_year: Optional[int]
    death_year: Optional[int]
    catalogue_raisonne_published: bool
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict, total=False):
    id: str
    email: str
    legal_name: str
    citizenship_country_code: str
    residency_country_code: str
    residency_state_code: Optional[str]
    birth_date: str
    suitability_status: str
    suitability_verified_at: Optional[str]
    suitability_expires_at: Optional[str]
    is_accredited: bool
    annual_income_cents: int
    net_worth_cents: int
    affiliated_with_issuer: bool
    restriction_until: str
    lifetime_invested_cents: int
    created_at: str
    updated_at: str
    version: int


class Artwork(TypedDict, total=False):
    id: str
    title: str
    artist_id: str
    creation_year: int
    medium: str
    condition_grade: str
    acquisition_cost_cents: int
    reserve_price_cents: int
    status: str
    last_appraised_value_cents: int
    last_appraisal_at: Optional[str]
    next_appraisal_due_at: Optional[str]
    artifacts_overview: dict
    created_at: str
    updated_at: str
    version: int


class ArtworkAssetReport(TypedDict, total=False):
    """Append-mostly child: only id and created_at, no updated_at/version."""
    id: str
    artwork_id: str
    report_type: str
    outcome: str
    firm_name: str
    condition_grade: Optional[str]
    filed_at: str
    created_at: str


class Appraisal(TypedDict, total=False):
    """Append-mostly child: only id and created_at, no updated_at/version."""
    id: str
    artwork_id: str
    appraised_value_cents: int
    appraiser_firm: str
    appraisal_method: str
    filed_at: str
    is_selected: bool
    created_at: str


class Offering(TypedDict, total=False):
    id: str
    artwork_id: str
    total_shares: int
    price_per_share_cents: int
    gross_proceeds_cents: int
    exemption_type: str
    registration_cap_pct: int
    liquidity_ratio_bps: int
    hold_period_days: int
    holding_clock_started_at: Optional[str]
    holding_period_end_at: Optional[str]
    management_fee_bps: int
    profit_participation_bps: int
    cost_pass_through_bps: int
    preferred_return_bps: int
    status: str
    circular_filed_at: Optional[str]
    qualification_deadline_at: Optional[str]
    accepted_shares: int
    unsubscribed_shares: int
    reserved_shares: int
    cash_ledger_cents: int
    custody_cost_ledger_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    offering_id: str
    investor_id: str
    requested_shares: int
    accepted_shares: int
    amount_due_cents: int
    collected_subscription_cents: int
    refunded_cents: int
    waitlist_rank: Optional[int]
    status: str
    created_at_seq: int
    created_at: str
    updated_at: str
    version: int


class CustodyRecord(TypedDict, total=False):
    id: str
    offering_id: str
    custodian_name: str
    facility_code: str
    is_freeport: bool
    custodian_dea_registered: bool
    status: str
    custody_started_at: Optional[str]
    custody_ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HoldingDecision(TypedDict, total=False):
    id: str
    offering_id: str
    decision_type: str
    status: str
    proposed_gross_cents: Optional[int]
    executed_gross_cents: Optional[int]
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferOrder(TypedDict, total=False):
    id: str
    offering_id: str
    seller_id: str
    shares: int
    limit_price_cents: int
    bid_price_cents: Optional[int]
    buyer_id: Optional[str]
    execution_price_cents: Optional[int]
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    offering_id: str
    lot_type: str
    cost_amount_cents: int
    incurred_on: str
    pass_through_allowed: bool
    pass_through_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    offering_id: str
    carrier_name: str
    coverage_cents: int
    annual_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OfferingReport(TypedDict, total=False):
    """Append-mostly child: only id and created_at, no updated_at/version."""
    id: str
    offering_id: str
    report_kind: str
    as_of_date: str
    filed_at: str
    shareholder_count: int
    value_per_share_cents: Optional[int]
    is_quarter_marker: bool
    created_at: str


class FeeAccrual(TypedDict, total=False):
    """Append-mostly child: only id and created_at, no updated_at/version."""
    id: str
    offering_id: str
    accrual_type: str
    basis_value_cents: int
    amount_cents: int
    accrued_at: str
    created_at: str


class Distribution(TypedDict, total=False):
    """Append-mostly child: only id and created_at, no updated_at/version."""
    id: str
    offering_id: str
    sale_gross_cents: int
    distributable_cents: int
    distributed_cost_cents: int
    management_fee_cents: int
    profit_participation_cents: int
    investor_residual_cents: int
    per_share_cents: int
    status: str
    created_at: str


class PlatformAccount(TypedDict, total=False):
    id: str
    account_name: str
    balance_cents: int
    investor_funds_held_cents: int
    total_paid_out_cents: int
    created_at: str
    updated_at: str
    version: int