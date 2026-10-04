"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ISSUER_OFFICER = "IssuerOfficer"
    LISTING_ANALYST = "ListingAnalyst"
    HEARINGS_OFFICER = "HearingsOfficer"
    LISTINGS_COUNCIL = "ListingsCouncil"
    FINANCE_OFFICER = "FinanceOfficer"


class IssuerStatus(str, Enum):
    PRE_LISTING = "PRE_LISTING"
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class ApplicationKind(str, Enum):
    INITIAL = "INITIAL"
    TRANSFER = "TRANSFER"
    TIER_TRANSFER = "TIER_TRANSFER"
    READMISSION = "READMISSION"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MarketTier(str, Enum):
    GLOBAL_SELECT = "GLOBAL_SELECT"
    GLOBAL = "GLOBAL"
    CAPITAL = "CAPITAL"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class StandardCode(str, Enum):
    BID_PRICE = "BID_PRICE"
    MVPHS = "MVPHS"
    MVLS = "MVLS"
    ROUND_LOT_HOLDERS = "ROUND_LOT_HOLDERS"
    TOTAL_SHAREHOLDERS = "TOTAL_SHAREHOLDERS"
    STOCKHOLDERS_EQUITY = "STOCKHOLDERS_EQUITY"


class DeficiencyStatus(str, Enum):
    OPEN = "OPEN"
    PLAN_SUBMITTED = "PLAN_SUBMITTED"
    REGAINED = "REGAINED"
    STAFF_DELIST_DETERMINED = "STAFF_DELIST_DETERMINED"
    PANEL_REVIEW = "PANEL_REVIEW"
    DELIST_UPHELD = "DELIST_UPHELD"
    DELIST_REVERSED = "DELIST_REVERSED"


class ComplianceMethod(str, Enum):
    NATURAL = "NATURAL"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    TIER_TRANSFER = "TIER_TRANSFER"
    PLAN_APPROVED = "PLAN_APPROVED"


class PlanKind(str, Enum):
    CURE_IN_PLACE = "CURE_IN_PLACE"
    TIER_TRANSFER = "TIER_TRANSFER"


class PlanStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class HearingsReviewStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    PANEL_REVIEWING = "PANEL_REVIEWING"
    PANEL_AFFIRMED = "PANEL_AFFIRMED"
    PANEL_REVERSED = "PANEL_REVERSED"
    COUNCIL_REVIEWING = "COUNCIL_REVIEWING"
    COUNCIL_AFFIRMED = "COUNCIL_AFFIRMED"
    COUNCIL_REVERSED = "COUNCIL_REVERSED"


class FeeKind(str, Enum):
    ENTRY = "ENTRY"
    ANNUAL = "ANNUAL"


class FeeStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class CorporateActionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EFFECTIVE = "EFFECTIVE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Issuer(TypedDict):
    id: str
    legal_name: str
    ticker_symbol: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ListingApplication(TypedDict, total=False):
    id: str
    issuer_id: str
    target_tier: str
    is_transfer_from_exchange: bool
    application_kind: str
    readmission_rejected: bool
    board_directors: list
    audit_committee: list
    compensation_committee: list
    stockholders_equity_cents: int
    market_value_listed_securities_cents: int
    market_value_unrestricted_publicly_held_cents: int
    total_revenue_cents: int
    income_from_continuing_operations_cents: int
    bid_price_cents: int
    publicly_held_shares: int
    unrestricted_publicly_held_shares: int
    round_lot_holders: int
    total_shareholders: int
    market_makers: int
    operating_history_months: int
    evaluated_standards: list
    status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    issuer_id: str
    application_id: str
    tier: str
    status: str
    suspended_at: Optional[str]
    delisted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only observation log: id + created_at only — no updated_at / version
class MarketDataSnapshot(TypedDict):
    id: str
    issuer_id: str
    trade_date: str
    closing_bid_cents: int
    market_value_publicly_held_cents: int
    market_value_listed_securities_cents: int
    round_lot_holders: int
    total_shareholders: int
    created_at: str


class Deficiency(TypedDict, total=False):
    id: str
    issuer_id: str
    standard_code: str
    tier_at_detection: str
    consecutive_days_failed: int
    detected_at: str
    compliance_due_at: str
    staff_determined_at: Optional[str]
    still_open: bool
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event log: id + created_at only — no updated_at / version
class ComplianceRecord(TypedDict):
    id: str
    issuer_id: str
    deficiency_id: str
    regained_at: str
    qualifying_days: int
    method: str
    created_at: str


class CompliancePlan(TypedDict, total=False):
    id: str
    issuer_id: str
    deficiency_id: str
    plan_text: str
    plan_kind: str
    proposed_target_tier: Optional[str]
    status: str
    review_decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HearingsReview(TypedDict):
    id: str
    issuer_id: str
    panel_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    issuer_id: str
    deficiency_id: str
    review_id: str
    filed_at: str
    decided_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    issuer_id: str
    fee_kind: str
    tier: str
    assessment_year: int
    shares_outstanding: int
    amount_cents: int
    delisted_mid_year: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CorporateAction(TypedDict, total=False):
    id: str
    issuer_id: str
    action_type: str
    split_ratio_denominator: int
    announced_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
