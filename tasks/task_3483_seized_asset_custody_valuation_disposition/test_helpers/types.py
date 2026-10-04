"""Domain types: entity TypedDicts, status enums, role enum.

All nine resource types share the same system-managed properties (PRD §2.5):
``id``, ``created_at``, ``updated_at`` and ``version`` (version starts at 1 and
increments by exactly one on every mutation, including cascade side effects).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CASE_AGENT = "CaseAgent"
    COURT_OFFICIAL = "CourtOfficial"
    ASSET_CUSTODIAN = "AssetCustodian"
    APPRAISER = "Appraiser"
    ASSET_MANAGER = "AssetManager"
    AUCTION_COORDINATOR = "AuctionCoordinator"
    FUND_ADMINISTRATOR = "FundAdministrator"
    CLAIMANT = "Claimant"
    SYSTEM_OPERATOR = "SystemOperator"


# ─── Enumerations (PRD §3) ───────────────────────────────────────────────────

class ForfeitureType(str, Enum):
    CIVIL = "CIVIL"
    CRIMINAL = "CRIMINAL"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    FORFEITURE_PENDING = "FORFEITURE_PENDING"
    FORFEITED = "FORFEITED"
    DISMISSED = "DISMISSED"


class AssetType(str, Enum):
    REAL_PROPERTY = "REAL_PROPERTY"
    BUSINESS = "BUSINESS"
    VEHICLE = "VEHICLE"
    VESSEL = "VESSEL"
    AIRCRAFT = "AIRCRAFT"
    PERSONAL_PROPERTY = "PERSONAL_PROPERTY"
    FINANCIAL_INSTRUMENT = "FINANCIAL_INSTRUMENT"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    SALVAGE = "SALVAGE"


class CustodyState(str, Enum):
    INTAKE = "INTAKE"
    SECURED = "SECURED"
    IN_STORAGE = "IN_STORAGE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    RELEASED_FOR_SALE = "RELEASED_FOR_SALE"
    RELEASED_FOR_RETURN = "RELEASED_FOR_RETURN"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class LegalState(str, Enum):
    SEIZED = "SEIZED"
    VALUATION_PENDING = "VALUATION_PENDING"
    VALUED = "VALUED"
    DISPOSITION_REVIEW = "DISPOSITION_REVIEW"
    RETAINED = "RETAINED"
    SALE_AUTHORIZED = "SALE_AUTHORIZED"
    SOLD = "SOLD"
    RETURN_PENDING = "RETURN_PENDING"
    RETURNED = "RETURNED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class RetentionDecision(str, Enum):
    PENDING = "PENDING"
    RETAIN = "RETAIN"
    SELL = "SELL"


class LocationKind(str, Enum):
    STORAGE = "STORAGE"
    MAINTENANCE_SHOP = "MAINTENANCE_SHOP"
    CLAIMANT_PREMISES = "CLAIMANT_PREMISES"
    OTHER = "OTHER"


class TransferStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ValuationMethod(str, Enum):
    CERTIFIED_APPRAISAL = "CERTIFIED_APPRAISAL"
    MARKET_COMPARABLE = "MARKET_COMPARABLE"
    BLUE_BOOK = "BLUE_BOOK"
    INCOME_APPROACH = "INCOME_APPROACH"


class ValuationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class EntryKind(str, Enum):
    COST = "COST"
    REVENUE_OFFSET = "REVENUE_OFFSET"
    REVERSAL = "REVERSAL"


class ExpenseType(str, Enum):
    STORAGE = "STORAGE"
    MAINTENANCE = "MAINTENANCE"
    MANAGEMENT_FEE = "MANAGEMENT_FEE"
    INSURANCE = "INSURANCE"
    SECURITY = "SECURITY"
    UTILITIES = "UTILITIES"
    STORAGE_ACCRUAL = "STORAGE_ACCRUAL"  # reserved for system postings


class ExpenseSource(str, Enum):
    MANUAL = "MANUAL"
    SYSTEM_ACCRUAL = "SYSTEM_ACCRUAL"


class IsrStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class InterestKind(str, Enum):
    LIEN_MORTGAGE = "LIEN_MORTGAGE"
    LIEN_TAX = "LIEN_TAX"
    LIEN_JUDGMENT = "LIEN_JUDGMENT"
    LIEN_MECHANIC = "LIEN_MECHANIC"
    INNOCENT_OWNER = "INNOCENT_OWNER"


class InterestStatus(str, Enum):
    FILED = "FILED"
    VERIFIED = "VERIFIED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    SATISFIED = "SATISFIED"


class SaleMethod(str, Enum):
    PUBLIC_AUCTION = "PUBLIC_AUCTION"
    CONTRACTED_SELLER = "CONTRACTED_SELLER"


class SaleStatus(str, Enum):
    OPEN_FOR_BIDS = "OPEN_FOR_BIDS"
    CLOSED_PENDING_SETTLEMENT = "CLOSED_PENDING_SETTLEMENT"
    SETTLED = "SETTLED"
    NO_SALE = "NO_SALE"
    CANCELLED = "CANCELLED"


class DistributionKind(str, Enum):
    EQUITABLE_SHARE = "EQUITABLE_SHARE"
    LIEN_PAYMENT = "LIEN_PAYMENT"
    COST_REIMBURSEMENT = "COST_REIMBURSEMENT"


class UsageRestriction(str, Enum):
    OVERTIME = "OVERTIME"
    TRAINING = "TRAINING"
    EQUIPMENT = "EQUIPMENT"
    COMMUNITY_PROGRAM = "COMMUNITY_PROGRAM"


class DistributionStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    VOIDED = "VOIDED"


# ─── Entity bodies (PRD §2.5 + §3) ──────────────────────────────────────────

class SeizureCase(TypedDict, total=False):
    id: str
    case_number: str
    judicial_district: str
    forfeiture_type: str
    lead_agency_code: str
    status: str
    forfeited_at: Optional[str]
    gross_proceeds_cents: int
    auction_fees_cents: int
    lien_payments_cents: int
    cost_reimbursements_cents: int
    sharing_pool_gross_basis_cents: int
    sharing_pool_net_basis_cents: int
    equitable_shares_paid_cents: int
    available_proceeds_cents: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    seizure_case_id: str
    asset_type: str
    description: str
    seized_on: str
    seizure_condition_grade: str
    current_condition_grade: str
    appraised_value_cents: Optional[int]
    appraised_at: Optional[str]
    accumulated_net_holding_cost_cents: int
    custody_state: str
    legal_state: str
    retention_decision: str
    provisional_net_retention_value_cents: Optional[int]
    final_net_retention_value_cents: Optional[int]
    returned_at: Optional[str]
    computed_depreciation_cents: Optional[int]
    dispute_claimed_depreciation_cents: Optional[int]
    final_depreciation_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CustodyTransfer(TypedDict, total=False):
    id: str
    asset_id: str
    from_location_ref: str
    to_location_ref: str
    to_location_kind: str
    window_start: str
    window_end: str
    status: str
    condition_on_arrival: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Valuation(TypedDict, total=False):
    id: str
    asset_id: str
    method: str
    raw_value_cents: Optional[int]
    assessed_condition_grade: Optional[str]
    annual_net_revenues_cents: Optional[List[int]]
    adjusted_value_cents: int
    status: str
    submitted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ExpenseEntry(TypedDict, total=False):
    id: str
    asset_id: str
    entry_kind: str
    expense_type: str
    amount_cents: int
    incurred_on: str
    source: str
    posted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class InterlocutorySaleRequest(TypedDict, total=False):
    id: str
    asset_id: str
    justification: str
    requested_by_user_id: str
    status: str
    adjudicated_by_user_id: Optional[str]
    accumulated_costs_snapshot_cents: int
    projected_burden_cents: int
    appraised_value_snapshot_cents: int
    created_at: str
    updated_at: str
    version: int


class ThirdPartyInterest(TypedDict, total=False):
    id: str
    asset_id: str
    kind: str
    petitioner_ref: str
    lienholder_name: Optional[str]
    amount_cents: Optional[int]
    priority_position: Optional[int]
    status: str
    appeal_count: int
    satisfied_amount_cents: Optional[int]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SaleEvent(TypedDict, total=False):
    id: str
    asset_id: str
    sale_method: str
    auctioneer_ref: str
    slot_start: str
    slot_end: str
    reserve_price_cents: int
    winning_bid_cents: Optional[int]
    gross_proceeds_cents: Optional[int]
    auction_fee_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict, total=False):
    id: str
    seizure_case_id: str
    distribution_kind: str
    payee_ref: str
    amount_cents: int
    usage_restriction: Optional[str]
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "ForfeitureType",
    "CaseStatus",
    "AssetType",
    "ConditionGrade",
    "CustodyState",
    "LegalState",
    "RetentionDecision",
    "LocationKind",
    "TransferStatus",
    "ValuationMethod",
    "ValuationStatus",
    "EntryKind",
    "ExpenseType",
    "ExpenseSource",
    "IsrStatus",
    "InterestKind",
    "InterestStatus",
    "SaleMethod",
    "SaleStatus",
    "DistributionKind",
    "UsageRestriction",
    "DistributionStatus",
    "SeizureCase",
    "Asset",
    "CustodyTransfer",
    "Valuation",
    "ExpenseEntry",
    "InterlocutorySaleRequest",
    "ThirdPartyInterest",
    "SaleEvent",
    "Distribution",
]
