"""Domain types for the Member Benefit Bundling API: status enums and entity shapes."""
from enum import Enum
from typing import List, TypedDict


# --- Status enums ---------------------------------------------------------

class MemberStatus(str, Enum):
    PROSPECT = "PROSPECT"
    MEMBER_ACTIVE = "MEMBER_ACTIVE"
    MEMBER_AT_RISK = "MEMBER_AT_RISK"
    MEMBER_LAPSED = "MEMBER_LAPSED"


class MemberTier(str, Enum):
    NONE = "NONE"
    BASE = "BASE"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class EntitlementState(str, Enum):
    NONE = "NONE"
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    SUSPENDED = "SUSPENDED"


class ProductLine(str, Enum):
    LENDING = "LENDING"
    BANKING = "BANKING"
    INVESTING = "INVESTING"
    CAREER = "CAREER"


class AdoptionStatus(str, Enum):
    PENDING = "PENDING"
    ADOPTED = "ADOPTED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class LoanType(str, Enum):
    PERSONAL = "PERSONAL"
    STUDENT = "STUDENT"
    AUTO = "AUTO"
    REFINANCE = "REFINANCE"


class AutopayStatus(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"


class PricingStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    STEPPED_DOWN = "STEPPED_DOWN"


class EnrollmentStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    LAPSED = "LAPSED"


class BenefitCode(str, Enum):
    LOAN_RATE_DISCOUNT = "LOAN_RATE_DISCOUNT"
    DIRECT_DEPOSIT = "DIRECT_DEPOSIT"
    CAREER_COACHING_CREDIT = "CAREER_COACHING_CREDIT"
    INVESTING_FEE_WAIVER = "INVESTING_FEE_WAIVER"
    REWARDS_MULTIPLIER = "REWARDS_MULTIPLIER"


class EntitlementStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    PENDING_REQUALIFICATION = "PENDING_REQUALIFICATION"
    STEPPED_DOWN = "STEPPED_DOWN"
    REVOKED = "REVOKED"


class DiscountKind(str, Enum):
    MEMBER_TIER = "MEMBER_TIER"
    DIRECT_DEPOSIT = "DIRECT_DEPOSIT"
    AUTOPAY = "AUTOPAY"
    PROMOTIONAL = "PROMOTIONAL"
    CAREER_SERVICES = "CAREER_SERVICES"


class StackingClass(str, Enum):
    BASE = "BASE"
    ADDITIVE = "ADDITIVE"
    CAP_CONTRIBUTING = "CAP_CONTRIBUTING"


class RuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ApplicationState(str, Enum):
    APPLIED = "APPLIED"
    PREEMPTED = "PREEMPTED"
    ROLLED_BACK = "ROLLED_BACK"


class LedgerEntryType(str, Enum):
    EARN = "EARN"
    REDEEM_PRINCIPAL = "REDEEM_PRINCIPAL"
    REVERSE = "REVERSE"
    ADJUST = "ADJUST"


class LedgerEntryStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REMEDIATION = "REMEDIATION"
    CLOSED = "CLOSED"


class NoticeType(str, Enum):
    RATE_STEP_DOWN = "RATE_STEP_DOWN"
    RATE_STEP_UP = "RATE_STEP_UP"
    REQUALIFICATION_REMINDER = "REQUALIFICATION_REMINDER"
    BENEFIT_REVOCATION = "BENEFIT_REVOCATION"


class NoticeStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    VOIDED = "VOIDED"


class SessionKind(str, Enum):
    CAREER_COACHING = "CAREER_COACHING"
    MEMBER_EVENT = "MEMBER_EVENT"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CrossSellStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"
    REUSE_PROHIBITED = "REUSE_PROHIBITED"


class UserRole(str, Enum):
    MEMBER = "Member"
    UNDERWRITER = "Underwriter"
    BENEFITS_ADMIN = "BenefitsAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


# --- Entity shapes --------------------------------------------------------
# Every persisted resource carries id, created_at, updated_at and version.

class Member(TypedDict):
    id: str
    member_number: str
    full_name: str
    email: str
    member_status: str
    member_since_at: str | None
    product_adoption_count: int
    product_line_set: List[str]
    member_tier: str
    qualifying_deposit_balance_cents: int
    benefit_entitlement_state: str
    rewards_points_balance: int
    churn_risk_score: int
    last_qualifying_deposit_at: str | None
    created_at: str
    updated_at: str
    version: int


class ProductHolding(TypedDict):
    id: str
    member_id: str
    product_line: str
    adoption_status: str
    adopted_at: str | None
    closed_at: str | None
    balance_cents: int
    deposit_rate_eligible: bool
    cross_sell_eligible: bool
    reunderwriting_permitted: bool
    created_at: str
    updated_at: str
    version: int


class LoanAccount(TypedDict):
    id: str
    member_id: str
    holding_id: str
    loan_type: str
    principal_cents: int
    base_apr_bps: int
    autopay_status: str
    pricing_status: str
    discount_stack_bps: int
    effective_apr_bps: int
    last_priced_at: str
    created_at: str
    updated_at: str
    version: int


class DirectDepositEnrollment(TypedDict):
    id: str
    member_id: str
    required_monthly_amount_cents: int
    status: str
    qualified_at: str | None
    last_deposit_at: str | None
    consecutive_qualifying_months: int
    requalification_due_at: str | None
    grace_deadline_at: str | None
    missed_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class BenefitEntitlement(TypedDict):
    id: str
    member_id: str
    source_holding_id: str
    benefit_code: str
    entitlement_status: str
    value_bps: int
    governing_rule_id: str | None
    granted_at: str | None
    stepped_down_at: str | None
    reconciliation_state: str
    override_requested_by: str | None
    override_approved_by: str | None
    created_at: str
    updated_at: str
    version: int


class RateDiscountRule(TypedDict):
    id: str
    rule_code: str
    discount_kind: str
    stacking_class: str
    discount_bps: int
    stacks_on_rule_id: str | None
    requires_direct_deposit: bool
    min_member_tier: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DiscountApplication(TypedDict):
    id: str
    loan_account_id: str
    rule_id: str
    applied_bps: int
    application_state: str
    applied_at: str
    window_from: str
    window_to: str
    preempted_by_application_id: str | None
    created_at: str
    updated_at: str
    version: int


class RewardsLedgerEntry(TypedDict):
    id: str
    member_id: str
    loan_account_id: str | None
    entry_type: str
    points_delta: int
    principal_reduction_cents: int
    entry_status: str
    source_event_code: str
    reversed_by_entry_id: str | None
    created_at: str
    updated_at: str
    version: int


class RequalificationCycle(TypedDict):
    id: str
    member_id: str
    cycle_index: int
    opened_at: str
    due_at: str
    evaluated_at: str | None
    status: str
    qualifying_month_count: int
    qualifying_deposit_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ChurnNotice(TypedDict):
    id: str
    member_id: str
    notice_type: str
    status: str
    issued_at: str
    effective_at: str
    related_entitlement_id: str | None
    reason_code: str | None
    created_at: str
    updated_at: str
    version: int


class CoachingSession(TypedDict):
    id: str
    member_id: str
    coach_ref: str
    session_kind: str
    starts_at: str
    ends_at: str
    status: str
    capacity_total: int
    seats_reserved: int
    created_at: str
    updated_at: str
    version: int


class CrossSellCheck(TypedDict):
    id: str
    member_id: str
    target_product_line: str
    consent_recorded: bool
    underwriting_reuse_permitted: bool
    conditioning_blocked: bool
    status: str
    decided_at: str | None
    decided_by: str | None
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "MemberStatus", "MemberTier", "EntitlementState", "ProductLine",
    "AdoptionStatus", "LoanType", "AutopayStatus", "PricingStatus",
    "EnrollmentStatus", "BenefitCode", "EntitlementStatus", "DiscountKind",
    "StackingClass", "RuleStatus", "ApplicationState", "LedgerEntryType",
    "LedgerEntryStatus", "CycleStatus", "NoticeType", "NoticeStatus",
    "SessionKind", "SessionStatus", "CrossSellStatus", "UserRole",
    "Member", "ProductHolding", "LoanAccount", "DirectDepositEnrollment",
    "BenefitEntitlement", "RateDiscountRule", "DiscountApplication",
    "RewardsLedgerEntry", "RequalificationCycle", "ChurnNotice",
    "CoachingSession", "CrossSellCheck",
]