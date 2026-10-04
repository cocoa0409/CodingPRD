"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the full common field set
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    HR_RECRUITER = "HRRecruiter"
    CORPORATE_CONTROLLER = "CorporateController"
    MANAGING_PARTNER = "ManagingPartner"
    MARKET_PARTNER = "MarketPartner"
    OPERATIONS_AUDITOR = "OperationsAuditor"


class PartnerStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    IN_TRAINING = "IN_TRAINING"
    TRAINING_EXTENDED = "TRAINING_EXTENDED"
    CERTIFIED = "CERTIFIED"
    PLACED = "PLACED"
    WITHDRAWN = "WITHDRAWN"


class RoleInProgram(str, Enum):
    MANAGING_PARTNER = "MANAGING_PARTNER"
    MARKET_PARTNER = "MARKET_PARTNER"


class MarketGroupStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"


class RestaurantStatus(str, Enum):
    PRE_OPENING = "PRE_OPENING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_FUNDING = "PENDING_FUNDING"
    ACTIVE = "ACTIVE"
    RENEWAL_OFFERED = "RENEWAL_OFFERED"
    BUYOUT_PENDING = "BUYOUT_PENDING"
    SETTLED = "SETTLED"
    TRANSFERRED = "TRANSFERRED"
    LAPSED = "LAPSED"
    EXPIRED = "EXPIRED"


class BuyInPaymentStatus(str, Enum):
    POSTED = "POSTED"
    REFUNDED = "REFUNDED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AgreementBasis(str, Enum):
    NET_GROUP_BASIS = "NET_GROUP_BASIS"
    PER_RESTAURANT_POSITIVE = "PER_RESTAURANT_POSITIVE"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    COMPUTED = "COMPUTED"
    FINALIZED = "FINALIZED"
    REOPENED = "REOPENED"
    LOCKED = "LOCKED"


class LineItemCategory(str, Enum):
    REVENUE = "REVENUE"
    COST_OF_GOODS = "COST_OF_GOODS"
    LABOR = "LABOR"
    CORPORATE_ADMIN_FEE = "CORPORATE_ADMIN_FEE"
    CORPORATE_MARKETING_FEE = "CORPORATE_MARKETING_FEE"
    MEAT_WASTE_CHARGE = "MEAT_WASTE_CHARGE"
    ADJUSTMENT = "ADJUSTMENT"


class EntryStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"


class PartnerBasis(str, Enum):
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"


class BatchStatus(str, Enum):
    RECORDED = "RECORDED"
    AUDITED_CONFORMING = "AUDITED_CONFORMING"
    VARIANCE_CONFIRMED = "VARIANCE_CONFIRMED"
    VARIANCE_WAIVED = "VARIANCE_WAIVED"


class ProgramType(str, Enum):
    CONFERENCE = "CONFERENCE"
    STOCK_GRANT = "STOCK_GRANT"


class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class GrantStatus(str, Enum):
    EARNED = "EARNED"
    VESTING = "VESTING"
    VESTED = "VESTED"
    FORFEITED = "FORFEITED"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class BuyoutOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"


class Partner(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    role_in_program: str
    status: str
    training_started_at: Optional[str]
    training_weeks_accrued: int
    certified_at: Optional[str]
    placed_restaurant_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketGroup(TypedDict, total=False):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Restaurant(TypedDict, total=False):
    id: str
    name: str
    city: str
    state_code: str
    market_group_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ManagingPartnerContract(TypedDict, total=False):
    id: str
    partner_id: str
    restaurant_id: str
    term_start_date: str
    term_end_date: str
    buy_in_required_cents: int
    buy_in_escrow_cents: int
    capital_account_cents: int
    submitted_at: Optional[str]
    renewed_count: int
    departure_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BuyInPayment(TypedDict, total=False):
    id: str
    contract_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketPartnerAgreement(TypedDict, total=False):
    id: str
    partner_id: str
    market_group_id: str
    coverage_start_date: str
    coverage_end_date: str
    override_pct: float
    basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProfitPeriod(TypedDict, total=False):
    id: str
    restaurant_id: str
    period_start_date: str
    period_end_date: str
    status: str
    provisional_profit_cents: Optional[int]
    final_distributable_profit_cents: Optional[int]
    partner_share_cents: Optional[int]
    market_override_cents: Optional[int]
    corporate_retained_cents: Optional[int]
    partner_share_paid: bool
    finalized_at: Optional[str]
    dispute_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProfitStatementLineItem(TypedDict, total=False):
    id: str
    period_id: str
    category: str
    amount_cents: int
    entry_status: str
    actual_amount_cents: int
    partner_basis: str
    created_at: str
    updated_at: str
    version: int


class YieldStandard(TypedDict, total=False):
    id: str
    cut_code: str
    expected_yield_pct: float
    waste_tolerance_pct: float
    standard_cost_per_lb_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class MeatCutBatch(TypedDict, total=False):
    id: str
    restaurant_id: str
    profit_period_id: str
    cut_code: str
    sub_primal_weight_lbs: float
    actual_yield_lbs: Optional[float]
    actual_waste_lbs: Optional[float]
    excess_waste_lbs: Optional[float]
    waste_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AwardProgram(TypedDict, total=False):
    id: str
    name: str
    program_type: str
    performance_period_start_date: str
    performance_period_end_date: str
    eligibility_threshold_score: float
    stock_units_pool: Optional[int]
    units_reserved: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AwardGrant(TypedDict, total=False):
    id: str
    program_id: str
    partner_id: str
    source_period_id: str
    eligibility_score: float
    units_awarded: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisputeCase(TypedDict, total=False):
    id: str
    period_id: str
    filed_by_partner_id: str
    claim_text: str
    filed_at: str
    adjustment_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BuyoutOrder(TypedDict, total=False):
    id: str
    contract_id: str
    capital_return_cents: int
    accrued_share_cents: int
    offset_cents: int
    total_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
