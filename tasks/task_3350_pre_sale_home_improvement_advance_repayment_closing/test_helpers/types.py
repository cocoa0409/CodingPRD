"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this program carries the common fields
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Optional, TypedDict


class ConciergeCaseStatus(str, Enum):
    ELIGIBILITY_REVIEW = "ELIGIBILITY_REVIEW"
    SCOPE_PLANNING = "SCOPE_PLANNING"
    PLAN_APPROVED = "PLAN_APPROVED"
    FUNDED = "FUNDED"
    IN_PROGRESS = "IN_PROGRESS"
    READY_TO_LIST = "READY_TO_LIST"
    LISTED = "LISTED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED_SOLD = "CLOSED_SOLD"
    CLOSED_UNSOLD = "CLOSED_UNSOLD"
    CANCELLED = "CANCELLED"


class CasePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class UpfrontPaymentTrack(str, Enum):
    NO_UPFRONT = "NO_UPFRONT"
    CONTRIBUTION = "CONTRIBUTION"


class ImprovementProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_WORK = "IN_WORK"
    COMPLETE = "COMPLETE"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class VendorTrade(str, Enum):
    GENERAL = "GENERAL"
    ELECTRIC = "ELECTRIC"
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    PAINT = "PAINT"
    LANDSCAPE = "LANDSCAPE"


class VendorEngagementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_WORK = "IN_WORK"
    COMPLETE_ON_TIME = "COMPLETE_ON_TIME"
    COMPLETE_LATE = "COMPLETE_LATE"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class DisbursementKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    PROGRESS = "PROGRESS"
    FINAL = "FINAL"
    CHANGE_ORDER = "CHANGE_ORDER"


class ChangeOrderStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeOrderReason(str, Enum):
    SCOPE_CREEP = "SCOPE_CREEP"
    HIDDEN_DAMAGE = "HIDDEN_DAMAGE"
    MATERIAL_PRICE = "MATERIAL_PRICE"
    CODE_UPGRADE = "CODE_UPGRADE"
    OTHER = "OTHER"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED_VENDOR_FAULT = "RESOLVED_VENDOR_FAULT"
    RESOLVED_HOMEOWNER_FAULT = "RESOLVED_HOMEOWNER_FAULT"
    WITHDRAWN = "WITHDRAWN"


class DisputeKind(str, Enum):
    WORKMANSHIP = "WORKMANSHIP"
    COST_OVERRUN = "COST_OVERRUN"
    SCHEDULE_DELAY = "SCHEDULE_DELAY"


class DisputeResolution(str, Enum):
    RESOLVED_VENDOR_FAULT = "RESOLVED_VENDOR_FAULT"
    RESOLVED_HOMEOWNER_FAULT = "RESOLVED_HOMEOWNER_FAULT"


class ClosingStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class PayoffBasis(str, Enum):
    LISTED_WITHIN_WINDOW = "LISTED_WITHIN_WINDOW"
    NOT_LISTED_WITHIN_WINDOW = "NOT_LISTED_WITHIN_WINDOW"
    SOLD_WITHIN_WINDOW = "SOLD_WITHIN_WINDOW"
    SOLD_AFTER_WINDOW = "SOLD_AFTER_WINDOW"


class ListingEventKind(str, Enum):
    LISTED = "LISTED"
    PRICE_REDUCED = "PRICE_REDUCED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    CLOSED_SOLD = "CLOSED_SOLD"
    CLOSED_UNSOLD = "CLOSED_UNSOLD"
    DELISTED = "DELISTED"


class CapacityWindowStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LISTING_AGENT = "ListingAgent"
    HOMEOWNER = "Homeowner"
    VENDOR = "Vendor"
    PROGRAM_UNDERWRITER = "ProgramUnderwriter"
    ANY = "Any"


class Agent(TypedDict, total=False):
    id: str
    display_name: str
    license_number: str
    brokerage: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    legal_name: str
    trade: str
    quality_score_bp: int
    on_time_streak: int
    created_at: str
    updated_at: str
    version: int


class VendorCapacityWindow(TypedDict, total=False):
    id: str
    vendor_id: str
    window_start: str
    window_end: str
    capacity_crew_days: int
    reserved_crew_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConciergeCase(TypedDict, total=False):
    id: str
    address_line: str
    estimated_property_value_cents: int
    expected_sale_proceeds_cents: int
    listing_agreement_signed: bool
    listing_agreement_disclosure_ack: bool
    advance_limit_cents: int
    advance_total_cents: int
    homeowner_contribution_cents: int
    upfront_payment_track: str
    listing_price_target_cents: int
    listing_window_days: int
    listed_at: Optional[str]
    closed_at: Optional[str]
    status: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class ImprovementProject(TypedDict, total=False):
    id: str
    concierge_case_id: str
    title: str
    recommended_by_agent: bool
    expected_sale_price_lift_cents: int
    estimated_cost_cents: int
    approved_cost_cents: int
    cost_overrun_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorEngagement(TypedDict, total=False):
    id: str
    improvement_project_id: str
    vendor_id: str
    agreed_price_cents: int
    start_date: str
    end_date: str
    completion_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    concierge_case_id: str
    improvement_project_id: str
    vendor_engagement_id: str
    amount_cents: int
    kind: str
    sequence_in_case: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    improvement_project_id: str
    vendor_engagement_id: str
    delta_cents: int
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    concierge_case_id: str
    improvement_project_id: str
    vendor_engagement_id: str
    dispute_kind: str
    claimed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosingStatement(TypedDict, total=False):
    id: str
    concierge_case_id: str
    gross_sale_price_cents: Optional[int]
    payoff_basis: str
    advance_repayment_cents: int
    program_fee_cents: int
    late_fee_cents: int
    vendor_holdback_cents: int
    net_repayment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ListingEvent(TypedDict, total=False):
    id: str
    concierge_case_id: str
    event_kind: str
    event_at: str
    price_cents: Optional[int]
    market_risk_flag: bool
    created_at: str
    updated_at: str
    version: int
