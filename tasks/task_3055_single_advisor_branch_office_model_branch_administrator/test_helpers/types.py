"""Domain types: entity TypedDicts, status enums, role enum.

Field shapes mirror the PRD: most top-level resources carry id,
created_at, updated_at and version; DoorKnockContact, MilestoneEvaluation
and ProductShelfEntry carry only id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    HOME_OFFICE_ADMIN = "HomeOfficeAdmin"
    ADVISOR = "Advisor"
    BRANCH_ADMINISTRATOR = "BranchAdministrator"
    COMPLIANCE_PRINCIPAL = "CompliancePrincipal"


class AdvisorStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    TRAINEE = "TRAINEE"
    VALIDATED = "VALIDATED"
    PRACTICING = "PRACTICING"
    RETIRING = "RETIRING"
    RETIRED = "RETIRED"
    TERMINATED = "TERMINATED"


class TerritoryStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    RETIRED = "RETIRED"


class BranchOperatingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SITE_APPROVED = "SITE_APPROVED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BranchStaffingStatus(str, Enum):
    UNSTAFFED = "UNSTAFFED"
    ADVISOR_ASSIGNED = "ADVISOR_ASSIGNED"
    FULLY_STAFFED = "FULLY_STAFFED"
    SUCCESSION_PENDING = "SUCCESSION_PENDING"


class ServiceTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class BoaStatus(str, Enum):
    HIRED = "HIRED"
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    RELEASED = "RELEASED"


class TrainingProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MILESTONE_PENDING = "MILESTONE_PENDING"
    REMEDIATION = "REMEDIATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MilestoneOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FINALIZED = "FINALIZED"


class ChargeType(str, Enum):
    LEASE_RENT = "LEASE_RENT"
    BOA_PAYROLL = "BOA_PAYROLL"
    EQUIPMENT = "EQUIPMENT"
    DEFICIT_CARRYOVER = "DEFICIT_CARRYOVER"


class PostingStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ValuationMode(str, Enum):
    INTERNAL_SUCCESSION = "INTERNAL_SUCCESSION"
    OPEN_MARKET = "OPEN_MARKET"


class TransferStatus(str, Enum):
    OFFERED = "OFFERED"
    NEGOTIATING = "NEGOTIATING"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ShelfStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class SolicitationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


# --- Entities with the full common property set (id/created_at/updated_at/version) ---

class Advisor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    status: str
    hire_date: str
    branch_id: Optional[str]
    predecessor_advisor_id: Optional[str]
    cumulative_commissions_cents: int
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict, total=False):
    id: str
    community_name: str
    household_capacity: int
    assigned_advisor_id: Optional[str]
    assignment_start: Optional[str]
    assignment_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Branch(TypedDict, total=False):
    id: str
    community_name: str
    site_address: str
    territory_id: str
    operating_status: str
    staffing_status: str
    household_count: int
    assets_under_care_dollars: int
    service_tier: str
    tier_score: int
    created_at: str
    updated_at: str
    version: int


class BranchOfficeAdministrator(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    monthly_salary_cents: int
    branch_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingProgram(TypedDict, total=False):
    id: str
    advisor_id: str
    goal_cents: int
    start_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseAgreement(TypedDict, total=False):
    id: str
    branch_id: str
    monthly_rent_cents: int
    term_start: str
    term_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BranchFinancialPeriod(TypedDict, total=False):
    id: str
    branch_id: str
    period_start: str
    period_end: str
    status: str
    gross_revenue_cents: int
    total_charges_cents: int
    net_profit_cents: int
    advisor_share_cents: int
    deficit_carryforward_cents: int
    created_at: str
    updated_at: str
    version: int


class BranchCharge(TypedDict, total=False):
    id: str
    branch_id: str
    period_id: str
    charge_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GoodwillTransfer(TypedDict, total=False):
    id: str
    branch_id: str
    retiring_advisor_id: str
    successor_advisor_id: str
    valuation_mode: str
    trailing_revenue_cents: int
    offer_price_cents: int
    escrow_deposit_cents: int
    negotiation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SolicitationRequest(TypedDict, total=False):
    id: str
    advisor_id: str
    product_code: str
    client_household_id: str
    status: str
    decided_by_role: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Lean resources (id + created_at only; no updated_at, no version) ---

class DoorKnockContact(TypedDict, total=False):
    id: str
    territory_id: str
    household_address: str
    contact_outcome: str
    contacted_at: str
    archived: bool
    created_at: str


class MilestoneEvaluation(TypedDict, total=False):
    id: str
    training_program_id: str
    window_end: str
    production_cents: int
    outcome: str
    created_at: str


class ProductShelfEntry(TypedDict, total=False):
    id: str
    product_code: str
    asset_class: str
    complexity_level: str
    status: str
    created_at: str


class ProductionRecord(TypedDict, total=False):
    id: str
    advisor_id: str
    gross_commission_cents: int
    payout_rate: float
    commissions_cents: int
    posted_at: str
    status: str
    created_at: str
