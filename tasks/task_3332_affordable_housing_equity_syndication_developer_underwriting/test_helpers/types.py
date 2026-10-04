"""Domain types: entity TypedDicts, status enums and the role enum.

Every one of the ten resources in this API carries the four system-managed
properties described in PRD §2.6 — ``id``, ``created_at``, ``updated_at`` and
``version`` — so every TypedDict below declares all four.

Enums subclass ``str`` so a member compares equal to its wire value:
``DeveloperStatus.ELIGIBLE == "ELIGIBLE"`` is true, which lets tests mix
literals and members freely.
"""

from enum import Enum
from typing import List, Optional, TypedDict

__all__ = [
    # role enum
    "UserRole",
    # status / dimension enums
    "DeveloperStatus",
    "DeveloperType",
    "InvestorStatus",
    "InvestorType",
    "RiskTier",
    "FundStatus",
    "FundPosture",
    "SubscriptionStatus",
    "ProjectStatus",
    "UnderwritingStage",
    "AllocationStatus",
    "CapitalCallMilestone",
    "CapitalCallStatus",
    "GuaranteeType",
    "GuaranteeStatus",
    "ReviewStatus",
    "ReviewOutcome",
    "ExitEventStatus",
    "ExitAction",
    "CapitalCallAction",
    "AllocationAction",
    "UnderwritingAction",
    "AllocationEditAction",
    # short aliases
    "Posture",
    "CallStatus",
    "ExitStatus",
    # typed dicts
    "PayinScheduleEntry",
    "Developer",
    "Investor",
    "SyndicationFund",
    "FundSubscription",
    "Project",
    "Allocation",
    "CapitalCall",
    "Guarantee",
    "PortfolioReview",
    "ExitEvent",
]


# =============================================================================
# Roles — PRD §2.1 names exactly seven, no others.
# =============================================================================

class UserRole(str, Enum):
    """The seven recognised ``X-User-Role`` values.

    ``Developer`` and ``Investor`` are entity-backed: ``X-User-ID`` must carry
    that entity's ``id``. The other five are opaque operator identifiers.
    ``Anonymous`` is a sentinel that is never permitted on any endpoint.
    """

    DEVELOPER = "Developer"
    INVESTOR = "Investor"
    UNDERWRITER = "Underwriter"
    ASSET_MANAGER = "AssetManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"


# =============================================================================
# Entity dimension enums
# =============================================================================

class DeveloperStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class DeveloperType(str, Enum):
    NONPROFIT = "NONPROFIT"
    FOR_PROFIT = "FOR_PROFIT"
    JOINT_VENTURE = "JOINT_VENTURE"


class InvestorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InvestorType(str, Enum):
    BANK = "BANK"
    INSURANCE = "INSURANCE"
    CORPORATE = "CORPORATE"
    FOUNDATION = "FOUNDATION"
    PENSION = "PENSION"


class RiskTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class FundStatus(str, Enum):
    FORMING = "FORMING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    DEPLOYING = "DEPLOYING"
    WOUND_DOWN = "WOUND_DOWN"
    TERMINATED = "TERMINATED"


class FundPosture(str, Enum):
    OPEN = "OPEN"
    WATCH = "WATCH"
    FROZEN = "FROZEN"


class SubscriptionStatus(str, Enum):
    PLEDGED = "PLEDGED"
    SUBSCRIBED = "SUBSCRIBED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FULLY_FUNDED = "FULLY_FUNDED"
    DEFAULTED = "DEFAULTED"


class ProjectStatus(str, Enum):
    UNDERWRITING = "UNDERWRITING"
    COMMITTED = "COMMITTED"
    CONSTRUCTION = "CONSTRUCTION"
    LEASE_UP = "LEASE_UP"
    STABILIZED = "STABILIZED"
    COMPLIANCE_PERIOD = "COMPLIANCE_PERIOD"
    EXIT_ELIGIBLE = "EXIT_ELIGIBLE"
    EXITED = "EXITED"
    DISTRESSED = "DISTRESSED"


class UnderwritingStage(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"


class AllocationStatus(str, Enum):
    AWARDED = "AWARDED"
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    CLOSED = "CLOSED"
    RESCINDED = "RESCINDED"


class CapitalCallMilestone(str, Enum):
    CONSTRUCTION_START = "CONSTRUCTION_START"
    CONSTRUCTION_50PCT = "CONSTRUCTION_50PCT"
    LEASE_UP_50PCT = "LEASE_UP_50PCT"
    LEASE_UP_STABILIZED = "LEASE_UP_STABILIZED"
    PLACED_IN_SERVICE = "PLACED_IN_SERVICE"


class CapitalCallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DEFICIENT = "DEFICIENT"
    ADJUSTED = "ADJUSTED"


class GuaranteeType(str, Enum):
    OPERATING_DEFICIT = "OPERATING_DEFICIT"
    RECAPTURE = "RECAPTURE"
    COMPLETION = "COMPLETION"


class GuaranteeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DRAWN = "DRAWN"
    DISCHARGED = "DISCHARGED"
    RELEASED = "RELEASED"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    ESCALATED = "ESCALATED"
    NONCOMPLIANT = "NONCOMPLIANT"
    CURED = "CURED"


class ReviewOutcome(str, Enum):
    """Outcomes a caller may name explicitly on the resolve action.

    Omitting ``outcome`` is the "derive from the risk score" path; it is not
    modelled as an enum member because it is the absence of a value.
    """

    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    ESCALATED = "ESCALATED"
    NONCOMPLIANT = "NONCOMPLIANT"
    CURED = "CURED"


class ExitEventStatus(str, Enum):
    PENDING = "PENDING"
    OPTION_NOTICE_ISSUED = "OPTION_NOTICE_ISSUED"
    ROFR_WINDOW = "ROFR_WINDOW"
    EXERCISED = "EXERCISED"
    DECLINED = "DECLINED"
    CLOSED = "CLOSED"


# --- Action vocabularies (request-body values, not resource states) ---------

class ExitAction(str, Enum):
    ISSUE_NOTICE = "ISSUE_NOTICE"
    OPEN_ROFR = "OPEN_ROFR"
    EXERCISE = "EXERCISE"
    DECLINE = "DECLINE"
    CLOSE = "CLOSE"


class CapitalCallAction(str, Enum):
    ISSUE = "ISSUE"
    SETTLE = "SETTLE"
    ADJUST = "ADJUST"
    REISSUE = "REISSUE"


class AllocationAction(str, Enum):
    CREATE = "CREATE"
    CLOSE = "CLOSE"
    RESCIND = "RESCIND"
    RECORD_DELIVERY = "RECORD_DELIVERY"
    DISTRIBUTE = "DISTRIBUTE"


class UnderwritingAction(str, Enum):
    FINALIZE = "FINALIZE"


class AllocationEditAction(str, Enum):
    RESERVE = "RESERVE"
    RELEASE = "RELEASE"


# --- Short aliases -----------------------------------------------------------

Posture = FundPosture
CallStatus = CapitalCallStatus
ExitStatus = ExitEventStatus


# =============================================================================
# Entity TypedDicts
# =============================================================================

class PayinScheduleEntry(TypedDict):
    """One ``{milestone, share_pct}`` element of a subscription's schedule."""

    milestone: str
    share_pct: float


class Developer(TypedDict):
    """A sponsoring developer entity."""

    id: str
    name: str
    developer_type: str
    sponsor_experience_months: int
    projects_completed: int
    net_worth_cents: int
    liquid_assets_cents: int
    guarantee_exposure_cents: int
    active_project_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict):
    """An institutional investor entity."""

    id: str
    name: str
    investor_type: str
    committed_capacity_cents: int
    risk_tier: str
    outstanding_commitment_cents: int
    funded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SyndicationFund(TypedDict):
    """A syndicated equity fund, with both of its parallel valuations."""

    id: str
    fund_name: str
    target_equity_cents: int
    price_per_credit_dollar: float
    target_yield_pct: float
    close_threshold_pct: float
    subscription_open_date: str
    subscription_close_date: str
    status: str
    posture: str
    funded_equity_cents: int
    subscribed_equity_cents: int
    awarded_credits_total_cents: int
    delivered_credits_total_cents: int
    priced_value_cents: int
    realized_value_cents: int
    priced_yield_pct: float
    realized_yield_pct: float
    subscription_count: int
    created_at: str
    updated_at: str
    version: int


class FundSubscription(TypedDict):
    """An investor's equity commitment to one fund."""

    id: str
    fund_id: str
    investor_id: str
    committed_cents: int
    payin_schedule: List[PayinScheduleEntry]
    executed_price_per_credit_dollar: float
    status: str
    paid_in_cents: int
    unfunded_commitment_cents: int
    shortfall_cents: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    """A development project, with its underwriting and compliance figures."""

    id: str
    developer_id: str
    fund_id: str
    project_name: str
    state_code: str
    total_credit_dollars_cents: int
    construction_budget_cents: int
    construction_loan_cents: int
    operating_pro_forma_noi_cents: int
    debt_service_cents: int
    market_study_absorption_score: float
    sponsor_experience_months: int
    placed_in_service_deadline: str
    placed_in_service_at: Optional[str]
    compliance_period_months: int
    status: str
    underwriting_stage: str
    preliminary_equity_cents: int
    final_equity_cents: Optional[int]
    underwritten_equity_cents: int
    dscr: float
    operating_deficit_cents: int
    committed_credit_dollars_cents: int
    delivered_credit_dollars_cents: int
    compliance_failure_count: int
    underwritten_gap_cents: int
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    """A credit award from a housing finance agency, nested under a project."""

    id: str
    project_id: str
    state_agency: str
    awarded_credit_dollars_cents: int
    commitment_fee_pct: float
    awarded_date: str
    placed_in_service_deadline: str
    status: str
    delivered_credit_dollars_cents: int
    delivery_ratio: float
    created_at: str
    updated_at: str
    version: int


class CapitalCall(TypedDict):
    """An equity call against one construction or lease-up milestone."""

    id: str
    project_id: str
    milestone: str
    scheduled_date: str
    due_date: str
    base_call_cents: int
    credit_delivery_adjuster_pct: float
    called_amount_cents: int
    settled_amount_cents: int
    shortfall_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Guarantee(TypedDict):
    """A developer guarantee covering a project."""

    id: str
    project_id: str
    guarantee_type: str
    guaranteed_amount_cents: int
    recapture_pct: float
    coverage_start_date: str
    coverage_end_date: str
    drawn_amount_cents: int
    remaining_capacity_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PortfolioReview(TypedDict):
    """One compliance-period review of a project, with its watch-list score."""

    id: str
    project_id: str
    review_period_index: int
    review_period_end: str
    occupancy_pct: float
    dscr_observed: float
    reserve_balance_cents: int
    corrected_reserve_balance_cents: Optional[int]
    risk_score: int
    status: str
    escalated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExitEvent(TypedDict):
    """A year-fifteen exit plan for a project."""

    id: str
    project_id: str
    exit_year: int
    rofr_notice_date: str
    rofr_window_days: int
    exercise_deadline: str
    option_price_cents: int
    rofr_expires_at: str
    cumulative_distributions_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
