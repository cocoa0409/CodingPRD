"""Domain types: entity TypedDicts, lifecycle enums and the role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BUYER = "Buyer"
    SALES_COUNSELOR = "SalesCounselor"
    MORTGAGE_BANKER = "MortgageBanker"
    CLOSING_OFFICER = "ClosingOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class CommitmentStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class HomeSiteStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    SOLD = "SOLD"


class ConstructionStage(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    FOUNDATION = "FOUNDATION"
    FRAMING = "FRAMING"
    DRYWALL = "DRYWALL"
    FINISH = "FINISH"
    COMPLETE = "COMPLETE"


class BuyerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    QUALIFIED = "QUALIFIED"
    CONTRACTED = "CONTRACTED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    PENDING = "PENDING"
    LOCKED = "LOCKED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    BUYER_DEFAULT = "BUYER_DEFAULT"
    CONSTRUCTION_DELAY = "CONSTRUCTION_DELAY"
    FINANCING_DENIED = "FINANCING_DENIED"
    RATE_SHOCK = "RATE_SHOCK"


class LenderEntityCode(str, Enum):
    AFFILIATED_LENDER = "AFFILIATED_LENDER"
    THIRD_PARTY_LENDER = "THIRD_PARTY_LENDER"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    QUALIFIED = "QUALIFIED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class LockWaiverStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    REFUSED = "REFUSED"


class RateLockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class IncentiveBucket(str, Enum):
    PRICE_REDUCTION = "PRICE_REDUCTION"
    CLOSING_COSTS = "CLOSING_COSTS"
    RATE_BUYDOWN = "RATE_BUYDOWN"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class BuydownRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKED = "BOOKED"
    REVERSED = "REVERSED"


class DisclosureType(str, Enum):
    AFFILIATED_BUSINESS_ARRANGEMENT = "AFFILIATED_BUSINESS_ARRANGEMENT"
    STEERING_PROHIBITION = "STEERING_PROHIBITION"
    RATE_BUYDOWN_TERMS = "RATE_BUYDOWN_TERMS"


class DisclosureStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CURING = "CURING"
    WAIVED = "WAIVED"


class StatuteClass(str, Enum):
    FULL_FORFEITURE = "FULL_FORFEITURE"
    PARTIAL_FORFEITURE = "PARTIAL_FORFEITURE"
    RESTITUTION_REQUIRED = "RESTITUTION_REQUIRED"


class ForfeitureStatus(str, Enum):
    PROPOSED = "PROPOSED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class Community(TypedDict):
    id: str
    name: str
    state_code: str
    incentive_policy_code: str
    capture_rate_target_bps: int
    price_reduction_cap_cents: int
    closing_cost_cap_cents: int
    rate_buydown_cap_cents: int
    affiliated_units: int
    funded_units: int
    capture_rate_bps: int
    incentive_spend_cents: int
    forward_units_committed: int
    program_status: str
    created_at: str
    updated_at: str
    version: int


class ForwardCommitment(TypedDict):
    id: str
    community_id: str
    commitment_code: str
    investor_name: str
    committed_rate_bps: int
    committed_units: int
    units_drawn: int
    units_released: int
    units_available: int
    commitment_start_iso: str
    commitment_end_iso: str
    pair_off_fee_cents: int
    commitment_status: str
    created_at: str
    updated_at: str
    version: int


class HomeSite(TypedDict):
    id: str
    community_id: str
    lot_number: str
    address: str
    base_price_cents: int
    construction_stage: str
    estimated_completion_iso: str
    advertised_rate_bps: int
    advertised_rate_expires_iso: str
    home_site_status: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    full_name: str
    email: str
    state_code: str
    buyer_status: str
    affiliated_lender_selected: bool
    total_incentive_received_cents: int
    steering_protection_flag: bool
    created_at: str
    updated_at: str
    version: int


class HomeSaleContract(TypedDict):
    id: str
    home_site_id: str
    buyer_id: str
    purchase_price_cents: int
    earnest_money_cents: int
    deposit_held_cents: int
    incentive_budget_cents: int
    incentive_allocated_cents: int
    contract_status: str
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict):
    id: str
    contract_id: str
    lender_entity_code: str
    application_number: str
    qualification_score: int
    qualifying_income_cents: int
    monthly_debt_cents: int
    dti_bps: int
    lock_required_days: int
    drift_flag: bool
    application_status: str
    lock_waiver_status: str
    uw_precedence: str
    created_at: str
    updated_at: str
    version: int


class RateLock(TypedDict):
    id: str
    application_id: str
    commitment_id: str
    lock_rate_bps: int
    lock_days: int
    lock_start_iso: str
    lock_expires_iso: str
    relock_fee_cents: int
    relock_count: int
    lock_cost_cents: int
    lock_status: str
    created_at: str
    updated_at: str
    version: int


class BuydownCostRecord(TypedDict):
    id: str
    contract_id: str
    allocation_id: str
    gross_buydown_cents: int
    recapture_credit_cents: int
    allowed_buydown_cost_cents: int
    aba_cure_deadline_iso: Optional[str]
    record_status: str
    created_at: str
    updated_at: str
    version: int


class IncentiveAllocation(TypedDict):
    id: str
    contract_id: str
    bucket: str
    requested_cents: int
    allocation_total_cents: int
    spill_to_bucket: Optional[str]
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


class ABADisclosure(TypedDict):
    id: str
    contract_id: str
    disclosure_type: str
    delivery_iso: str
    cure_deadline_iso: str
    disclosure_status: str
    created_at: str
    updated_at: str
    version: int


class DepositForfeiture(TypedDict):
    id: str
    contract_id: str
    statute_class: str
    forfeited_cents: int
    refunded_cents: int
    retained_incentive_cents: int
    forfeiture_status: str
    created_at: str
    updated_at: str
    version: int