"""Domain types for the Liquor License Brokerage & Transfer Escrow API.

Status enums, role enum and entity TypedDicts as described in the PRD.
Every resource carries a UUID ``id`` and a three-fractional-digit ``created_at``;
all resources except the escrow ledger row additionally carry ``updated_at`` and
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BROKER = "Broker"
    BUYER = "Buyer"
    SELLER = "Seller"
    REGULATOR_ANALYST = "RegulatorAnalyst"
    ESCROW_OFFICER = "EscrowOfficer"


# ─── Reference-data enumerations ──────────────────────────────────────────────

class ValuationBasis(str, Enum):
    COMPARABLE_SALES = "COMPARABLE_SALES"
    INCOME_MULTIPLE = "INCOME_MULTIPLE"


class TaxClearanceStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DELINQUENT = "DELINQUENT"


class EntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    LLC = "LLC"
    CORP = "CORP"


class DualAgencyPolicy(str, Enum):
    PROHIBITED = "PROHIBITED"
    ALLOWED_WITH_DISCLOSURE = "ALLOWED_WITH_DISCLOSURE"


class LicenseClass(str, Enum):
    CLASS_47_ONSALE_GENERAL = "CLASS_47_ONSALE_GENERAL"
    CLASS_21_OFFSALE_GENERAL = "CLASS_21_OFFSALE_GENERAL"
    CLASS_41_ONSALE_BEER_WINE = "CLASS_41_ONSALE_BEER_WINE"


# ─── Buyer qualification ──────────────────────────────────────────────────────

class QualificationStatus(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    QUALIFIED = "QUALIFIED"
    PROVISIONALLY_QUALIFIED = "PROVISIONALLY_QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class ReviewMode(str, Enum):
    PRE_CHECK = "PRE_CHECK"
    FINAL_REVIEW = "FINAL_REVIEW"


# ─── Premises ─────────────────────────────────────────────────────────────────

class SuitabilityStatus(str, Enum):
    SUITABLE = "SUITABLE"
    CONDITIONAL = "CONDITIONAL"
    UNSUITABLE = "UNSUITABLE"


class SuitabilityReasonCode(str, Enum):
    NONE = "NONE"
    SCHOOL_DISTANCE = "SCHOOL_DISTANCE"
    CHURCH_DISTANCE = "CHURCH_DISTANCE"
    CUP_DENIED = "CUP_DENIED"
    ZONING_NOT_PERMITTED = "ZONING_NOT_PERMITTED"
    LANDLORD_REFUSED = "LANDLORD_REFUSED"
    CUP_OUTSTANDING = "CUP_OUTSTANDING"
    UNDUE_CONCENTRATION = "UNDUE_CONCENTRATION"
    LANDLORD_PENDING = "LANDLORD_PENDING"


class ConditionalUsePermitStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED_NOT_FILED = "REQUIRED_NOT_FILED"
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class LandlordConsentStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REFUSED = "REFUSED"


# ─── State machines ───────────────────────────────────────────────────────────

class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IN_ESCROW = "IN_ESCROW"
    SAFEKEEPING = "SAFEKEEPING"
    TRANSFERRED = "TRANSFERRED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    WITHDRAWN = "WITHDRAWN"
    SOLD = "SOLD"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class EscrowStatus(str, Enum):
    AWAITING_DEPOSIT = "AWAITING_DEPOSIT"
    HELD = "HELD"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class DisclosureStatus(str, Enum):
    PENDING_ACKS = "PENDING_ACKS"
    FULLY_ACKED = "FULLY_ACKED"
    VOID = "VOID"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DEFICIENT = "DEFICIENT"
    POSTED = "POSTED"
    PROTESTED = "PROTESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ProtestStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"


class FilingStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


# ─── Action-payload enumerations ──────────────────────────────────────────────

class CommissionMode(str, Enum):
    SINGLE_AGENCY = "SINGLE_AGENCY"
    DUAL_AGENCY = "DUAL_AGENCY"


class EntryType(str, Enum):
    DEPOSIT = "DEPOSIT"
    RELEASE_COUNTY_FEE = "RELEASE_COUNTY_FEE"
    RELEASE_COMMISSION = "RELEASE_COMMISSION"
    RELEASE_SELLER = "RELEASE_SELLER"
    REFUND_BUYER = "REFUND_BUYER"
    FORFEIT_SELLER = "FORFEIT_SELLER"


class Disposition(str, Enum):
    RELEASE = "RELEASE"
    REFUND = "REFUND"
    FORFEIT = "FORFEIT"


class TransferDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class FilingType(str, Enum):
    INITIAL = "INITIAL"
    EXTENSION = "EXTENSION"


class SafekeepingDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class ProtestGrounds(str, Enum):
    UNDUE_CONCENTRATION = "UNDUE_CONCENTRATION"
    DISTANCE_RESTRICTION = "DISTANCE_RESTRICTION"
    PUBLIC_WELFARE = "PUBLIC_WELFARE"
    ZONING = "ZONING"


class AckParty(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"


class TerminationReason(str, Enum):
    ESCROW_REFUNDED = "ESCROW_REFUNDED"
    ESCROW_FORFEITED = "ESCROW_FORFEITED"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Every resource carries id + created_at + updated_at + version, except the
# escrow ledger row, which is immutable and carries id + created_at only.

class County(TypedDict):
    id: str
    county_code: str
    name: str
    state_code: str
    quota_licenses_total: int
    permitted_zoning_codes: List[str]
    distance_min_feet_school: int
    distance_min_feet_church: int
    posting_period_days: int
    protest_window_days: int
    transfer_fee_bps: int
    default_valuation_basis: str
    quota_licenses_counted: int
    quota_available: int
    quota_utilization_bps: int
    escrow_committed_count: int
    created_at: str
    updated_at: str
    version: int


class SellerProfile(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    tax_clearance_status: str
    created_at: str
    updated_at: str
    version: int


class BuyerProfile(TypedDict):
    id: str
    legal_name: str
    entity_type: str
    residency_state: str
    felony_disclosure: bool
    prior_revocation_count: int
    citizenship_verified: bool
    qualification_status: str
    qualification_score: Optional[int]
    qualification_mode: Optional[str]
    qualification_reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Brokerage(TypedDict):
    id: str
    firm_name: str
    state_broker_license_no: str
    commission_rate_bps: int
    dual_agency_policy: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    county_id: str
    owner_seller_id: str
    license_number: str
    license_class: str
    annual_gross_receipts_cents: int
    last_active_date: str
    last_transfer_price_cents: Optional[int]
    counts_against_quota: bool
    status: str
    transferred_to_buyer_id: Optional[str]
    safekeeping_expires_at: Optional[str]
    safekeeping_extensions_count: int
    safekeeping_filing_pending: bool
    created_at: str
    updated_at: str
    version: int


class Premises(TypedDict):
    id: str
    buyer_id: str
    county_id: str
    address_line: str
    zoning_code: str
    distance_to_nearest_school_feet: int
    distance_to_nearest_church_feet: int
    census_tract_undue_concentration: bool
    conditional_use_permit_status: str
    landlord_consent_status: str
    consent_document_ref: Optional[str]
    suitability_status: str
    suitability_reason_code: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    license_id: str
    brokerage_id: str
    ask_price_cents: int
    status: str
    valuation_basis: Optional[str]
    market_price_cents: Optional[int]
    scarcity_bps_at_activation: Optional[int]
    comp_count_at_activation: Optional[int]
    open_offer_count: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseAgreement(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    premises_id: str
    brokerage_id: str
    license_id: str
    seller_id: str
    purchase_price_cents: int
    deposit_pct_bps: int
    required_deposit_cents: int
    closing_window_start: str
    contingency_days: int
    contingency_deadline_at: str
    agreement_status: str
    escrow_status: str
    escrow_balance_cents: int
    commission_mode: Optional[str]
    commission_total_cents: Optional[int]
    county_transfer_fee_cents: Optional[int]
    seller_net_cents: Optional[int]
    executed_at: Optional[str]
    settled_at: Optional[str]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DualAgencyDisclosure(TypedDict):
    id: str
    agreement_id: str
    represents_seller: bool
    represents_buyer: bool
    disclosure_text_ref: Optional[str]
    status: str
    seller_ack_at: Optional[str]
    buyer_ack_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferApplication(TypedDict):
    id: str
    agreement_id: str
    license_id: str
    premises_id: str
    fee_paid_cents: int
    fee_paid_total_cents: int
    filing_fee_cents: int
    applicant_statement_ref: Optional[str]
    status: str
    deficiency_round_count: int
    last_deficiency_codes: Optional[List[str]]
    accepted_by_analyst_id: Optional[str]
    posting_started_at: Optional[str]
    posting_ends_at: Optional[str]
    protest_deadline_at: Optional[str]
    decision: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict):
    id: str
    application_id: str
    protestant_name: str
    grounds: str
    status: str
    filed_at: str
    response_due_at: str
    response_text_ref: Optional[str]
    response_submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafekeepingFiling(TypedDict):
    id: str
    license_id: str
    filing_type: str
    requested_months: int
    granted_months: int
    extension_index: int
    effective_from: str
    expires_at: str
    fee_cents: int
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscrowLedgerEntry(TypedDict):
    """Immutable escrow ledger row: carries id and created_at only —
    no updated_at and no version."""
    id: str
    agreement_id: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    memo: Optional[str]
    occurred_at: str
    created_at: str
