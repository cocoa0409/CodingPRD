"""Domain types for the Claims Adjudication Engine: entity shapes, status enums, roles."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Status enums ─────────────────────────────────────────────────────────────

class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PENDED = "PENDED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    FINALIZED = "FINALIZED"
    ADJUSTED = "ADJUSTED"
    VOIDED = "VOIDED"
    DUPLICATE_REJECTED = "DUPLICATE_REJECTED"


class ClaimPaymentStatus(str, Enum):
    NOT_REMITTED = "NOT_REMITTED"
    REMITTED = "REMITTED"
    REVERSED = "REVERSED"


class ClaimType(str, Enum):
    ORIGINAL = "ORIGINAL"
    ADJUSTMENT = "ADJUSTMENT"


class ClaimLineStatus(str, Enum):
    PENDING = "PENDING"
    PRICED = "PRICED"
    PENDED = "PENDED"
    DENIED = "DENIED"
    BUNDLED = "BUNDLED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class PricingVariant(str, Enum):
    UNPRICED = "UNPRICED"
    CONTRACT_PRICED = "CONTRACT_PRICED"
    FEE_SCHEDULE_PRICED = "FEE_SCHEDULE_PRICED"
    CASE_RATE_PRICED = "CASE_RATE_PRICED"


class CobRole(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class CobOrder(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    TERTIARY = "TERTIARY"


class CobMethod(str, Enum):
    COME_OUT_WHOLE = "COME_OUT_WHOLE"
    NON_DUPLICATION = "NON_DUPLICATION"


class CoverageTier(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FAMILY = "FAMILY"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class NetworkStatus(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PricingMethod(str, Enum):
    PCT_OF_FEE_SCHEDULE = "PCT_OF_FEE_SCHEDULE"
    CASE_RATE = "CASE_RATE"


class EditType(str, Enum):
    BUNDLING = "BUNDLING"
    MUTUALLY_EXCLUSIVE = "MUTUALLY_EXCLUSIVE"
    UNITS_LIMIT = "UNITS_LIMIT"
    AUTH_REQUIRED = "AUTH_REQUIRED"


class EditSeverity(str, Enum):
    DENY = "DENY"
    PEND = "PEND"
    INFORM = "INFORM"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    EXHAUSTED = "EXHAUSTED"
    REVOKED = "REVOKED"


class RemittanceStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class EventType(str, Enum):
    INTAKE = "INTAKE"
    DUPLICATE_REJECT = "DUPLICATE_REJECT"
    ADJUDICATE = "ADJUDICATE"
    OVERRIDE = "OVERRIDE"
    FINALIZE = "FINALIZE"
    VOID = "VOID"
    ADJUST = "ADJUST"
    COB_POST = "COB_POST"
    ELIG_REPEND = "ELIG_REPEND"


class OverrideDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    NETWORK_MANAGER = "NetworkManager"
    CLAIMS_INTAKE = "ClaimsIntake"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    UTILIZATION_REVIEWER = "UtilizationReviewer"
    MEDICAL_DIRECTOR = "MedicalDirector"
    PROVIDER_REP = "ProviderRep"


ALL_ROLES = [r.value for r in UserRole]

CLAIM_TERMINAL_STATUSES = ["VOIDED", "ADJUSTED", "DUPLICATE_REJECTED"]


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Every entity below carries id / created_at / updated_at / version, except
# AdjudicationEvent, which is append-only and carries only id and created_at.

class BenefitPlan(TypedDict):
    id: str
    plan_code: str
    name: str
    plan_year_start_date: str
    deductible_individual_cents: int
    oop_max_individual_cents: int
    coinsurance_member_pct: float
    copay_office_visit_cents: int
    out_of_network_penalty_pct: float
    timely_filing_days: int
    cob_method: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    member_number: str
    plan_id: str
    first_name: str
    last_name: str
    date_of_birth: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MemberCoverage(TypedDict):
    id: str
    member_id: str
    effective_date: str
    term_date: Optional[str]
    cob_order: str
    other_payer_name: Optional[str]
    coverage_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitAccumulator(TypedDict):
    id: str
    member_id: str
    plan_year: int
    deductible_applied_cents: int
    oop_applied_cents: int
    remitted_claim_count: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    npi: str
    name: str
    network_status: str
    specialty_code: str
    created_at: str
    updated_at: str
    version: int


class ProviderContract(TypedDict):
    id: str
    provider_id: str
    plan_id: str
    effective_date: str
    term_date: str
    pricing_method: str
    contract_pct: Optional[float]
    case_rate_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeScheduleRate(TypedDict):
    id: str
    plan_id: str
    procedure_code: str
    allowed_amount_cents: int
    effective_date: str
    created_at: str
    updated_at: str
    version: int


class EditRule(TypedDict):
    id: str
    rule_code: str
    edit_type: str
    primary_code: str
    secondary_code: Optional[str]
    max_units: Optional[int]
    severity: str
    precedence_rank: int
    reason_code: str
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    member_id: str
    provider_id: str
    procedure_code: str
    authorized_units: int
    units_consumed: int
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    claim_number: str
    member_id: str
    provider_id: str
    coverage_id: Optional[str]
    original_claim_id: Optional[str]
    duplicate_of_claim_id: Optional[str]
    claim_type: str
    statement_from_date: Optional[str]
    statement_to_date: Optional[str]
    received_at: str
    other_payer_paid_cents: Optional[int]
    cob_role: str
    pricing_variant: str
    total_billed_cents: int
    total_allowed_cents: int
    total_deductible_applied_cents: int
    total_member_liability_cents: int
    total_plan_paid_cents: int
    pend_reason_code: Optional[str]
    deny_reason_code: Optional[str]
    adjudication_pass: int
    last_adjudicated_by_user_id: Optional[str]
    status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    id: str
    claim_id: str
    line_number: int
    procedure_code: str
    modifier_code: Optional[str]
    units: int
    billed_amount_cents: int
    service_date: str
    allowed_amount_cents: int
    deductible_applied_cents: int
    copay_cents: int
    coinsurance_cents: int
    member_liability_cents: int
    plan_paid_cents: int
    authorization_id: Optional[str]
    bundled_into_line_number: Optional[int]
    edit_reason_code: Optional[str]
    line_status: str
    created_at: str
    updated_at: str
    version: int


class RemittanceAdvice(TypedDict):
    id: str
    claim_id: str
    remit_number: str
    total_allowed_cents: int
    total_plan_paid_cents: int
    total_member_liability_cents: int
    total_other_payer_paid_cents: int
    issued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdjudicationEvent(TypedDict):
    """Append-only audit record: carries id and created_at only from the common set."""
    id: str
    claim_id: str
    pass_number: int
    event_type: str
    from_status: Optional[str]
    to_status: str
    reason_code: Optional[str]
    actor_role: str
    actor_user_id: Optional[str]
    occurred_at: str
    created_at: str
