"""Domain types for the Government Surplus Property Disposal API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them. Entities the PRD describes as append-only (ConditionAssessment and
ClearanceCertificate) carry only ``id`` and ``created_at`` — never ``updated_at``
or ``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    AGENCY_OFFICER = "AgencyOfficer"
    SURPLUS_ASSESSOR = "SurplusAssessor"
    DISPOSAL_OFFICER = "DisposalOfficer"
    CLEARANCE_TECHNICIAN = "ClearanceTechnician"
    BIDDER = "Bidder"
    FINANCE_CONTROLLER = "FinanceController"


# ─── Status / enum vocabularies ────────────────────────────────────────────

class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgencyType(str, Enum):
    STATE_AGENCY = "STATE_AGENCY"
    LOCAL_GOVERNMENT = "LOCAL_GOVERNMENT"
    ELIGIBLE_NONPROFIT = "ELIGIBLE_NONPROFIT"


class FederalDoneeStatus(str, Enum):
    NONE = "NONE"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class TurnInStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class AssetCategory(str, Enum):
    VEHICLE = "VEHICLE"
    IT_EQUIPMENT = "IT_EQUIPMENT"
    FURNITURE = "FURNITURE"
    HEAVY_EQUIPMENT = "HEAVY_EQUIPMENT"
    RESTRICTED_MILITARY = "RESTRICTED_MILITARY"


class DemilCode(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    Q = "Q"


class ConditionCode(str, Enum):
    C1 = "C1"
    C2 = "C2"
    C3 = "C3"
    C4 = "C4"
    C5 = "C5"
    C6 = "C6"
    C7 = "C7"


class DispositionStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSED = "ASSESSED"
    SCREENING = "SCREENING"
    AWARDED_TRANSFER = "AWARDED_TRANSFER"
    AUCTION_ELIGIBLE = "AUCTION_ELIGIBLE"
    LISTED = "LISTED"
    SOLD = "SOLD"
    RELEASED = "RELEASED"
    RETAINED = "RETAINED"
    DESTROYED = "DESTROYED"


class ClearanceStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED_PENDING = "REQUIRED_PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class ScreeningTier(str, Enum):
    STATE_AGENCY = "STATE_AGENCY"
    LOCAL_GOVERNMENT = "LOCAL_GOVERNMENT"
    ELIGIBLE_NONPROFIT = "ELIGIBLE_NONPROFIT"
    PUBLIC_SALE = "PUBLIC_SALE"


class ScreeningCycleStatus(str, Enum):
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class ScreeningRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    LOST_AWARD = "LOST_AWARD"
    TRANSFER_VOIDED = "TRANSFER_VOIDED"
    CYCLE_CANCELLED = "CYCLE_CANCELLED"


class TransferOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AuctionLotStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED_MET = "CLOSED_MET"
    CLOSED_NO_SALE = "CLOSED_NO_SALE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ReserveSource(str, Enum):
    COMPUTED = "COMPUTED"
    OFFICER_OVERRIDE = "OFFICER_OVERRIDE"


class BidderStatus(str, Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"
    DEBARRED = "DEBARRED"


class BidderType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"


class BidStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUTBID = "OUTBID"
    WINNING = "WINNING"
    RETRACTED = "RETRACTED"


class SaleInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DEFAULTED = "DEFAULTED"
    VOIDED = "VOIDED"


class CertType(str, Enum):
    DATA_SANITIZATION = "DATA_SANITIZATION"
    DEMILITARIZATION = "DEMILITARIZATION"


class ClearanceMethod(str, Enum):
    NIST_CLEAR = "NIST_CLEAR"
    NIST_PURGE = "NIST_PURGE"
    DEGAUSS = "DEGAUSS"
    MUTILATE = "MUTILATE"
    DESTROY = "DESTROY"


class DistributionBasis(str, Enum):
    ACCRUAL = "ACCRUAL"
    CASH = "CASH"


class DistributionStatus(str, Enum):
    CALCULATED = "CALCULATED"
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"
    REVERSED = "REVERSED"


class TurnInDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


# ─── Entities carrying the full identity/audit set (PRD §2.5) ─────────────
# id, created_at, updated_at, version

class Agency(TypedDict):
    id: str
    name: str
    agency_code: str
    agency_type: str
    status: str
    federal_donee_status: str
    donee_certification_expires_on: Optional[str]
    proceeds_account_balance_cents: int
    posted_distribution_count: int
    created_at: str
    updated_at: str
    version: int


class TurnIn(TypedDict):
    id: str
    turning_in_agency_id: str
    custody_location: str
    remarks: Optional[str]
    status: str
    rejection_reason: Optional[str]
    asset_count: int
    appraised_total_cents: int
    submitted_at: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurplusAsset(TypedDict):
    id: str
    turn_in_id: str
    component_of_asset_id: Optional[str]
    category: str
    description: str
    acquisition_cost_cents: int
    acquisition_date: str
    is_data_bearing: bool
    is_restricted: bool
    demil_code: Optional[str]
    federal_source: bool
    federal_use_period_start_on: Optional[str]
    federal_use_period_end_on: Optional[str]
    vin: Optional[str]
    odometer_reading: Optional[int]
    title_number: Optional[str]
    lien_holder_name: Optional[str]
    odometer_disclosure_reading: Optional[int]
    lien_release_reference: Optional[str]
    title_recipient_name: Optional[str]
    condition_code: Optional[str]
    fair_market_value_cents: Optional[int]
    disposition_status: str
    clearance_status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningCycle(TypedDict):
    id: str
    asset_id: str
    opens_at: str
    tier_window_days: int
    current_tier: str
    tier_opened_at: str
    tier_deadline_at: str
    status: str
    tier_advance_count: int
    awarded_by_user_id: Optional[str]
    awarded_at: Optional[str]
    open_request_count: int
    created_at: str
    updated_at: str
    version: int


class ScreeningRequest(TypedDict):
    id: str
    screening_cycle_id: str
    requesting_agency_id: str
    intended_use: str
    justification: str
    needed_by_date: Optional[str]
    tier_at_submission: str
    status: str
    information_request_note: Optional[str]
    resubmission_count: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferOrder(TypedDict):
    id: str
    asset_id: str
    recipient_agency_id: str
    screening_request_id: str
    base_transfer_cents: int
    handling_fee_cents: int
    transfer_price_cents: int
    status: str
    issued_by_user_id: str
    acknowledged_at: Optional[str]
    use_period_end_on: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SaleVenue(TypedDict):
    id: str
    name: str
    venue_code: str
    concurrent_lot_capacity: int
    buyer_premium_pct: float
    sales_tax_pct: float
    status: str
    active_lot_count: int
    created_at: str
    updated_at: str
    version: int


class AuctionLot(TypedDict):
    id: str
    asset_id: str
    venue_id: str
    lot_number: str
    opens_at: str
    closes_at: str
    reserve_price_cents: int
    reserve_source: str
    required_deposit_cents: int
    status: str
    high_bid_cents: int
    bid_count: int
    closed_by_user_id: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bidder(TypedDict):
    id: str
    legal_name: str
    email: str
    bidder_type: str
    status: str
    end_use_certificate_expires_on: Optional[str]
    deposit_paid_cents: int
    deposit_held_cents: int
    deposit_applied_cents: int
    deposit_forfeited_cents: int
    winning_lot_count: int
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    auction_lot_id: str
    bidder_id: str
    amount_cents: int
    placed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SaleInvoice(TypedDict):
    id: str
    auction_lot_id: str
    bidder_id: str
    hammer_price_cents: int
    buyer_premium_cents: int
    sales_tax_cents: int
    total_due_cents: int
    amount_paid_cents: int
    deposit_applied_cents: int
    balance_due_cents: int
    due_at: str
    status: str
    default_reason: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProceedsDistribution(TypedDict):
    id: str
    auction_lot_id: str
    beneficiary_agency_id: str
    basis: str
    distributable_base_cents: int
    service_fee_cents: int
    cost_recovery_cents: int
    net_to_agency_cents: int
    status: str
    posted_by_user_id: Optional[str]
    posted_at: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entities (PRD §2.5) ──────────────────────────────────────
# "carry only id and created_at" — no updated_at, no version.

class ConditionAssessment(TypedDict):
    id: str
    asset_id: str
    assessor_user_id: str
    condition_code: str
    functional: bool
    repair_cost_estimate_cents: int
    assessed_on: str
    notes: Optional[str]
    superseded: bool
    created_at: str


class ClearanceCertificate(TypedDict):
    id: str
    asset_id: str
    cert_type: str
    method: str
    technician_user_id: str
    serials_verified: bool
    certified_on: str
    notes: Optional[str]
    created_at: str
