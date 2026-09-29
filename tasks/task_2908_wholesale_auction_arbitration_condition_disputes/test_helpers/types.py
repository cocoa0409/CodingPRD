"""Domain types for the Wholesale Auction Arbitration API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    AUCTION_ADMIN = "AuctionAdmin"
    BLOCK_CLERK = "BlockClerk"
    ARBITRATOR = "Arbitrator"
    INSPECTOR = "Inspector"
    BUYER_REP = "BuyerRep"
    SELLER_REP = "SellerRep"


class DefectClass(str, Enum):
    FRAME_DAMAGE = "FRAME_DAMAGE"
    MECHANICAL = "MECHANICAL"
    MILEAGE_DISCREPANCY = "MILEAGE_DISCREPANCY"
    TITLE_BRANDED = "TITLE_BRANDED"
    TITLE_MISSING = "TITLE_MISSING"


class SellerPolicyTier(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    PROBATION = "PROBATION"
    BLOCKED = "BLOCKED"


class BuyerClaimPrivilegeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FEE_HOLD = "FEE_HOLD"
    SUSPENDED = "SUSPENDED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ArbitrationStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class LightChannel(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class TitleStatus(str, Enum):
    CLEAN = "CLEAN"
    BRANDED_SALVAGE = "BRANDED_SALVAGE"
    MISSING = "MISSING"


class ProgramTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class InspectionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class CaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEGOTIATION = "NEGOTIATION"
    COUNTERED = "COUNTERED"
    ARBITRATOR_REVIEW = "ARBITRATOR_REVIEW"
    RESOLVED_ALLOWANCE = "RESOLVED_ALLOWANCE"
    UNWOUND = "UNWOUND"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


NON_TERMINAL_CASE_STATUSES = [
    "SUBMITTED",
    "UNDER_REVIEW",
    "NEGOTIATION",
    "COUNTERED",
    "ARBITRATOR_REVIEW",
]

TERMINAL_CASE_STATUSES = [
    "RESOLVED_ALLOWANCE",
    "UNWOUND",
    "DENIED",
    "WITHDRAWN",
    "EXPIRED",
]


class EvidenceType(str, Enum):
    INSPECTION_REPORT = "INSPECTION_REPORT"
    DIAGNOSTIC_SCAN = "DIAGNOSTIC_SCAN"
    THIRD_PARTY_VERIFICATION = "THIRD_PARTY_VERIFICATION"
    PHOTO_SET = "PHOTO_SET"
    TITLE_DOCUMENT = "TITLE_DOCUMENT"


VERIFIED_EVIDENCE_TYPES = ["INSPECTION_REPORT", "THIRD_PARTY_VERIFICATION"]
UNVERIFIED_EVIDENCE_TYPES = ["DIAGNOSTIC_SCAN", "PHOTO_SET", "TITLE_DOCUMENT"]


class ResponseType(str, Enum):
    OFFER_REPAIR_ALLOWANCE = "OFFER_REPAIR_ALLOWANCE"
    DISPUTE = "DISPUTE"
    ACCEPT_UNWIND = "ACCEPT_UNWIND"
    TIMEOUT = "TIMEOUT"


class RoundStatus(str, Enum):
    OPEN = "OPEN"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class LegType(str, Enum):
    INBOUND_TO_AUCTION = "INBOUND_TO_AUCTION"
    RETURN_TO_SELLER = "RETURN_TO_SELLER"
    TO_BUYER_REDELIVERY = "TO_BUYER_REDELIVERY"


class DecisionOutcome(str, Enum):
    UNWIND = "UNWIND"
    REPAIR_ALLOWANCE = "REPAIR_ALLOWANCE"
    CLAIM_DENIED = "CLAIM_DENIED"
    FRIVOLOUS_DENIED = "FRIVOLOUS_DENIED"


class AllowanceVariant(str, Enum):
    NEGOTIATED_ACCEPT = "NEGOTIATED_ACCEPT"
    ARBITRATOR_AWARD = "ARBITRATOR_AWARD"
    NONE = "NONE"


class FaultParty(str, Enum):
    SELLER = "SELLER"
    BUYER = "BUYER"
    NONE = "NONE"


class LedgerParty(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    AUCTION = "AUCTION"


class LedgerEntryType(str, Enum):
    SALE_PROCEEDS = "SALE_PROCEEDS"
    SALE_PROCEEDS_REVERSAL = "SALE_PROCEEDS_REVERSAL"
    REPAIR_ALLOWANCE = "REPAIR_ALLOWANCE"
    TRANSPORT_ALLOCATION = "TRANSPORT_ALLOCATION"
    FRIVOLOUS_FEE_ASSESSED = "FRIVOLOUS_FEE_ASSESSED"
    FRIVOLOUS_FEE_OFFSET = "FRIVOLOUS_FEE_OFFSET"


class PolicyActionType(str, Enum):
    WATCH_LIST = "WATCH_LIST"
    PROBATION = "PROBATION"
    BLOCK = "BLOCK"
    REINSTATE = "REINSTATE"


# --- Mutable resources: id + created_at + updated_at + version -----------------


class Seller(TypedDict):
    id: str
    name: str
    dealer_license_no: str
    policy_tier: str
    rolling_arbitration_rate_bps: int
    lifetime_arbitration_rate_bps: int
    rolling_window_sales_count: int
    rolling_window_upheld_count: int
    lifetime_sales_count: int
    lifetime_upheld_count: int
    open_claim_count: int
    blocked_at_utc: Optional[str]
    reinstated_count: int
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    name: str
    dealer_license_no: str
    claim_privilege_status: str
    frivolous_claim_count: int
    frivolous_fee_balance_cents: int
    open_claim_count: int
    lifetime_claim_count: int
    created_at: str
    updated_at: str
    version: int


class ArbitrationPolicy(TypedDict):
    id: str
    defect_class: str
    window_hours: Optional[int]
    mileage_limit: Optional[int]
    min_claim_amount_cents: int
    requires_third_party_verification: bool
    max_allowance_bps: int
    psi_extension_hours: int
    psi_clean_waives_rights: bool
    seller_response_hours: int
    created_at: str
    updated_at: str
    version: int


class AuctionSale(TypedDict):
    id: str
    vin: str
    seller_id: str
    buyer_id: str
    sale_price_cents: int
    hammer_time_utc: str
    announced_odometer_miles: int
    light_channel: str
    title_status: str
    settlement_status: str
    settled_at_utc: Optional[str]
    arbitration_status: str
    open_case_count: int
    settlement_hold: bool
    created_at: str
    updated_at: str
    version: int


class PostSaleInspection(TypedDict):
    id: str
    sale_id: str
    program_tier: str
    requested_at_utc: str
    window_end_utc: str
    completed_at_utc: Optional[str]
    findings: List[str]
    status: str
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ArbitrationCase(TypedDict):
    id: str
    sale_id: str
    claimant_buyer_id: str
    policy_id: str
    policy_version_at_intake: int
    superseded_case_id: Optional[str]
    defect_class: str
    claim_amount_cents: int
    odometer_at_claim: int
    complaint_text: str
    claimed_at_utc: str
    hours_elapsed_at_claim: float
    miles_driven_at_claim: int
    psi_extension_applied_hours: int
    effective_window_hours: Optional[int]
    window_eligible: bool
    status: str
    review_opened_at_utc: Optional[str]
    intake_arbitrator_user_id: Optional[str]
    seller_conceded: bool
    seller_response_timed_out: bool
    fault_party: str
    current_round_index: int
    latest_verified_estimate_cents: int
    verified_true_mileage: Optional[int]
    created_at: str
    updated_at: str
    version: int


class NegotiationRound(TypedDict):
    id: str
    case_id: str
    round_index: int
    response_type: str
    seller_offer_cents: int
    buyer_demand_cents: Optional[int]
    response_note: str
    counter_note: Optional[str]
    opened_at_utc: str
    response_deadline_utc: str
    countered_at_utc: Optional[str]
    cooldown_until_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only resources: id + created_at only (no updated_at, no version) ---


class SaleAnnouncement(TypedDict):
    id: str
    sale_id: str
    defect_class: str
    disclosure_text: str
    announced_at_utc: str
    created_at: str


class ClaimEvidence(TypedDict):
    id: str
    case_id: str
    evidence_type: str
    provider_name: str
    document_reference: str
    repair_estimate_cents: Optional[int]
    odometer_reading: Optional[int]
    submitted_by_role: str
    submitted_by_user_id: str
    verified: bool
    recorded_at_utc: str
    case_version_after: int
    created_at: str


class TransportLeg(TypedDict):
    id: str
    case_id: str
    leg_type: str
    miles: int
    carrier_name: str
    cost_cents: int
    recorded_at_utc: str
    case_version_after: int
    created_at: str


class ArbitrationDecision(TypedDict):
    id: str
    case_id: str
    outcome: str
    allowance_variant: str
    computed_award_cents: int
    requested_allowance_cents: Optional[int]
    allowance_cents: int
    fault_party: str
    transport_total_cents: int
    transport_buyer_share_cents: int
    transport_seller_share_cents: int
    transport_auction_share_cents: int
    sale_price_refund_cents: int
    fee_offset_applied_cents: int
    frivolous_fee_cents: int
    total_buyer_payout_cents: int
    rationale: str
    decided_by_arbitrator_user_id: str
    decided_at_utc: str
    created_at: str


class SettlementLedgerEntry(TypedDict):
    id: str
    sale_id: str
    case_id: Optional[str]
    party: str
    entry_type: str
    amount_signed_cents: int
    posted_at_utc: str
    created_at: str


class FrivolousFeeAssessment(TypedDict):
    id: str
    case_id: str
    buyer_id: str
    prior_frivolous_count: int
    fee_cents: int
    reason: str
    assessed_at_utc: str
    created_at: str


class SellerPolicyAction(TypedDict):
    id: str
    seller_id: str
    triggered_by_case_id: Optional[str]
    action_type: str
    from_tier: str
    to_tier: str
    rolling_rate_bps_at_action: int
    note: Optional[str]
    effective_at_utc: str
    created_at: str
