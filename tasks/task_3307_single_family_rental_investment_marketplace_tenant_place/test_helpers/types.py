"""Domain types: entity TypedDicts, status enums, and the role enum.

Every resource carries ``id`` (server-minted UUID, no type prefix) and
``created_at``. All resources except PaymentRecord also carry ``updated_at``
and ``version``; PaymentRecord is append-only and omits both.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SELLER = "Seller"
    BUYER = "Buyer"
    CERTIFICATION_REVIEWER = "CertificationReviewer"
    ESCROW_OFFICER = "EscrowOfficer"
    PROPERTY_MANAGER = "PropertyManager"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CERTIFIED = "CERTIFIED"
    LISTED = "LISTED"
    OFFER_PENDING = "OFFER_PENDING"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"


class ListingKind(str, Enum):
    SINGLE = "SINGLE"
    PORTFOLIO = "PORTFOLIO"


class InspectionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class LeaseTenancyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ASSIGNED = "ASSIGNED"
    TERMINATED = "TERMINATED"


class LeaseDisclosureStatus(str, Enum):
    PENDING = "PENDING"
    DISCLOSED = "DISCLOSED"
    REDACTED = "REDACTED"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class FinancingType(str, Enum):
    CASH = "CASH"
    CONVENTIONAL = "CONVENTIONAL"
    HARD_MONEY = "HARD_MONEY"


class EscrowStatus(str, Enum):
    OPENED = "OPENED"
    DOCS_SENT = "DOCS_SENT"
    SIGNED = "SIGNED"
    FUNDED = "FUNDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    ACCEPTED = "ACCEPTED"
    ONBOARDED = "ONBOARDED"
    DECLINED = "DECLINED"


class GuaranteeStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    CLAIMED = "CLAIMED"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class GuaranteeKind(str, Enum):
    VACANCY = "VACANCY"
    LEASE_UP = "LEASE_UP"


class DisputeStatus(str, Enum):
    OPENED = "OPENED"
    EVIDENCE = "EVIDENCE"
    RESOLVED_BUYER = "RESOLVED_BUYER"
    RESOLVED_SELLER = "RESOLVED_SELLER"
    WITHDRAWN = "WITHDRAWN"


class Seller(TypedDict, total=False):
    id: str
    legal_name: str
    seller_state: str
    seller_type: str
    listed_count: int
    bulk_discount_bps: int
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict, total=False):
    id: str
    legal_name: str
    buyer_state: str
    entity_type: str
    proof_of_funds_cents: int
    accredited: bool
    created_at: str
    updated_at: str
    version: int


class CertificationProgram(TypedDict, total=False):
    id: str
    name: str
    min_inspection_score: int
    min_title_grade: str
    requires_lease_disclosure: bool
    guarantee_months_cap: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    seller_id: str
    address_line: str
    listing_state: str
    asking_price_cents: int
    status: str
    listing_kind: str
    bulk_price_cents: Optional[int]
    certification_program_id: Optional[str]
    certified_at: Optional[str]
    seller_asks_confidential: bool
    created_at: str
    updated_at: str
    version: int


class InspectionReport(TypedDict, total=False):
    id: str
    listing_id: str
    inspector_name: str
    inspection_date: str
    overall_score: int
    roof_score: int
    systems_score: int
    disclosed_defects: List[dict]
    title_grade: str
    submitted_by_seller_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    listing_id: str
    tenant_alias: str
    monthly_rent_cents: int
    lease_start: str
    lease_end: str
    deposit_cents: int
    disclosure_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentRecord(TypedDict, total=False):
    # Append-only ledger: id + created_at only — NO updated_at, NO version.
    id: str
    lease_id: str
    due_date: str
    paid_date: Optional[str]
    amount_cents: int
    late: bool
    created_at: str


class UnderwritingReport(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_id: str
    rent_estimate_cents: int
    vacancy_rate_bps: int
    opex_rate_bps: int
    projected_noi_cents: int
    projected_yield_bps: int
    disclosure_limited: bool
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_id: str
    amount_cents: int
    earnest_money_cents: int
    financing_type: str
    status: str
    round_number: int
    is_out_of_state: bool
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Escrow(TypedDict, total=False):
    id: str
    offer_id: str
    escrow_officer_name: Optional[str]
    status: str
    remote_signing_required: bool
    signed_at: Optional[str]
    funded_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PropertyManager(TypedDict, total=False):
    id: str
    company_name: str
    markets: List[str]
    onboarding_fee_bps: int
    monthly_fee_bps: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class ManagementReferral(TypedDict, total=False):
    id: str
    listing_id: str
    property_manager_id: str
    status: str
    onboarding_fee_cents: Optional[int]
    lease_continuity_confirmed: bool
    created_at: str
    updated_at: str
    version: int


class Guarantee(TypedDict, total=False):
    id: str
    listing_id: str
    guarantee_kind: str
    coverage_months: int
    status: str
    claim_amount_cents: Optional[int]
    claimed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    listing_id: str
    opened_by: str
    opener_user_id: str
    condition_code: str
    status: str
    remedy_cents: int
    created_at: str
    updated_at: str
    version: int
