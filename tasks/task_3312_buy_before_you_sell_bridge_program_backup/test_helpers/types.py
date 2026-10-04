"""Domain types for the Buy-Before-You-Sell Bridge Program API.

Entities and enumerations as described in PRD.md (see PRD sections 2.8, 3.1-3.11).
Every entity in this API carries the four common properties id / created_at /
updated_at / version (PRD section 2.5), so each TypedDict below includes all four.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ─────────────────────────────────────────────────────────────
# Role enum (PRD section 2.1)
# ─────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    UNDERWRITER = "Underwriter"
    HOMEOWNER = "Homeowner"
    AGENT = "Agent"
    PROGRAM_ADMIN = "ProgramAdmin"


# ─────────────────────────────────────────────────────────────
# Status enums
# ─────────────────────────────────────────────────────────────

class HomeownerProgramStatus(str, Enum):
    NONE = "NONE"
    QUALIFYING = "QUALIFYING"
    ENROLLED = "ENROLLED"
    BRIDGED = "BRIDGED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class PropertyKind(str, Enum):
    DEPARTING = "DEPARTING"
    NEW = "NEW"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ListingStatus(str, Enum):
    UNLISTED = "UNLISTED"
    LISTED = "LISTED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    SOLD_TO_PROGRAM = "SOLD_TO_PROGRAM"
    RESOLD = "RESOLD"


class RepairStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class QualificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class QualificationVariant(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    OPTIMISTIC = "OPTIMISTIC"


class AdvanceStatus(str, Enum):
    PENDING = "PENDING"
    FUNDING = "FUNDING"
    FUNDED = "FUNDED"
    SETTLED = "SETTLED"


class OccupancyStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPYING_NEW = "OCCUPYING_NEW"
    DEPARTING_LISTED = "DEPARTING_LISTED"
    DEPARTING_SOLD = "DEPARTING_SOLD"


class LoanStatus(str, Enum):
    ORIGINATED = "ORIGINATED"
    DRAWN = "DRAWN"
    REPAYING = "REPAYING"
    REPAID = "REPAID"
    DELINQUENT = "DELINQUENT"


class AdvancePurpose(str, Enum):
    DOWN_PAYMENT = "DOWN_PAYMENT"
    CARRYING_COST = "CARRYING_COST"
    REPAIR = "REPAIR"
    FEE = "FEE"
    DISCLOSURE = "DISCLOSURE"


class BridgeAdvanceStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    REPAID = "REPAID"
    REJECTED = "REJECTED"


class CarryingCostKind(str, Enum):
    DEPARTING_TAX = "DEPARTING_TAX"
    DEPARTING_INSURANCE = "DEPARTING_INSURANCE"
    DEPARTING_HOA = "DEPARTING_HOA"
    DEPARTING_UTILITY = "DEPARTING_UTILITY"
    NEW_TAX = "NEW_TAX"
    NEW_INSURANCE = "NEW_INSURANCE"
    NEW_HOA = "NEW_HOA"
    NEW_UTILITY = "NEW_UTILITY"


class CarryingCostRepaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    REPAID = "REPAID"


class RepairAdvanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    SETTLED = "SETTLED"


class EscrowReleaseMode(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    MILESTONE = "MILESTONE"


class BackupOfferStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    EXTENDED = "EXTENDED"
    EXERCISED = "EXERCISED"
    VOIDED = "VOIDED"


class ListingLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class MarketingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"


class AgentQualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"


class RoleScope(str, Enum):
    DEPARTING_SIDE = "DEPARTING_SIDE"
    NEW_SIDE = "NEW_SIDE"
    RESALE_SIDE = "RESALE_SIDE"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class TaskKind(str, Enum):
    PHOTOGRAPHY = "PHOTOGRAPHY"
    INSPECTION = "INSPECTION"
    APPRAISAL = "APPRAISAL"
    REPAIR_BID = "REPAIR_BID"
    CLOSING_PREP = "CLOSING_PREP"
    RESALE_PREP = "RESALE_PREP"


class CoordinationTaskStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DisbursementSourceKind(str, Enum):
    CLOSING_SALE = "CLOSING_SALE"
    RESALE = "RESALE"
    REPAIR_CLAWBACK = "REPAIR_CLAWBACK"


class DisbursementStatus(str, Enum):
    RECORDED = "RECORDED"
    APPLIED = "APPLIED"


# ─────────────────────────────────────────────────────────────
# Entity TypedDicts (common_fields: true -> id + created_at +
# updated_at + version on every entity)
# ─────────────────────────────────────────────────────────────

class Homeowner(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    credit_score: int
    household_income_cents: int
    max_dti_bps: int
    departing_equity_cents: int
    program_status: str
    sealed_flag: bool
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    homeowner_id: str
    address: str
    kind: str
    appraised_value_cents: int
    mortgage_payoff_cents: int
    appraisal_date: str
    purchase_price_cents: int
    condition_grade: str
    listing_status: str
    repair_status: str
    site_visit_count: int
    repair_progress_bps: int
    program_inventory_flag: bool
    created_at: str
    updated_at: str
    version: int


class Qualification(TypedDict, total=False):
    id: str
    homeowner_id: str
    departing_property_id: str
    new_property_id: str
    target_purchase_price_cents: int
    variant_used: str
    capacity_cents: int
    equity_ratio: float
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BridgeProgram(TypedDict, total=False):
    id: str
    homeowner_id: str
    qualification_id: str
    new_property_id: str
    departing_property_id: str
    projected_carry_months: int
    program_fee_basis_points: int
    advance_status: str
    occupancy_status: str
    outstanding_carrying_cost_cents: int
    total_program_charge_cents: int
    active_referral_count: int
    created_at: str
    updated_at: str
    version: int


class InterimLoan(TypedDict, total=False):
    id: str
    bridge_program_id: str
    principal_cents: int
    interest_rate_bps: int
    drawn_cents: int
    outstanding_principal_cents: int
    accrued_interest_cents: int
    status: str
    originated_at: str
    created_at: str
    updated_at: str
    version: int


class BridgeAdvance(TypedDict, total=False):
    id: str
    bridge_program_id: str
    interim_loan_id: str
    purpose: str
    amount_cents: int
    status: str
    advanced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CarryingCost(TypedDict, total=False):
    id: str
    bridge_program_id: str
    kind: str
    amount_cents: int
    due_date: str
    repayment_status: str
    repaid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairAdvance(TypedDict, total=False):
    id: str
    property_id: str
    bridge_program_id: str
    scope: str
    approved_amount_cents: int
    escrow_release_mode: str
    status: str
    repaid_cents: int
    created_at: str
    updated_at: str
    version: int


class BackupOffer(TypedDict, total=False):
    id: str
    departing_property_id: str
    bridge_program_id: str
    offer_price_cents: int
    window_days: int
    window_start: str
    status: str
    expires_at: Optional[str]
    exercised_at: Optional[str]
    price_basis_cents: int
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    departing_property_id: str
    bridge_program_id: str
    list_price_cents: int
    listed_at: Optional[str]
    status: str
    marketing_status: str
    offer_count: int
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    full_name: str
    brokerage_name: str
    license_number: str
    referral_rate_bps: int
    qualification_status: str
    active_referral_count: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    agent_id: str
    bridge_program_id: str
    role_scope: str
    referral_rate_bps: int
    qualifying_volume_cents: int
    status: str
    base_fee_cents: int
    reconciled_fee_cents: int
    fee_variance_cents: int
    created_at: str
    updated_at: str
    version: int


class CoordinationTask(TypedDict, total=False):
    id: str
    bridge_program_id: str
    referral_id: str
    task_kind: str
    due_date: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    bridge_program_id: str
    source_kind: str
    amount_cents: int
    status: str
    applied_to_principal_cents: int
    applied_to_interest_cents: int
    remainder_cents: int
    created_at: str
    updated_at: str
    version: int


class ProgramSummary(TypedDict, total=False):
    outstanding_carrying_cost_cents: int
    true_cost_cents: int
    amortized_cost_cents: int
    variance_cents: int
    total_program_charge_cents: int
    origination_cents: int
    coordination_cents: int
    escalator_cents: int


class DisbursementSummary(TypedDict, total=False):
    total_applied_to_principal_cents: int
    total_applied_to_interest_cents: int
    remainder_cents: int
    entry_count: int