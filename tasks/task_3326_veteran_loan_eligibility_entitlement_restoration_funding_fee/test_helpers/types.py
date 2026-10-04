"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Entities with the common system-managed
field set carry ``id``, ``created_at``, ``updated_at`` and ``version``; the
append-only AuditEvent carries only ``id`` and ``created_at``.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


class Role(str, Enum):
    VETERAN = "Veteran"
    LOAN_OFFICER = "LoanOfficer"
    UNDERWRITER = "Underwriter"
    APPRAISER = "Appraiser"
    PROGRAM_ADMIN = "ProgramAdmin"


class ServiceCategory(str, Enum):
    REGULAR_MILITARY = "REGULAR_MILITARY"
    RESERVES_NATIONAL_GUARD = "RESERVES_NATIONAL_GUARD"


class DischargeCharacter(str, Enum):
    HONORABLE = "HONORABLE"
    GENERAL = "GENERAL"
    OTHER_THAN_HONORABLE = "OTHER_THAN_HONORABLE"
    BAD_CONDUCT = "BAD_CONDUCT"
    DISHONORABLE = "DISHONORABLE"


class Branch(str, Enum):
    ARMY = "ARMY"
    NAVY = "NAVY"
    AIR_FORCE = "AIR_FORCE"
    MARINES = "MARINES"
    COAST_GUARD = "COAST_GUARD"
    SPACE_FORCE = "SPACE_FORCE"


class EntitlementCode(str, Enum):
    ERA_WWII = "ERA_WWII"
    ERA_KOREA = "ERA_KOREA"
    ERA_VIETNAM = "ERA_VIETNAM"
    ERA_PEACETIME = "ERA_PEACETIME"
    ERA_GULF = "ERA_GULF"
    RESTORED = "RESTORED"
    UNREIMBURSED_SURVIVING_SPOUSE = "UNREIMBURSED_SURVIVING_SPOUSE"


class CoeStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DENIED = "DENIED"
    RECONSIDERATION = "RECONSIDERATION"
    ISSUED = "ISSUED"


class LoanPurpose(str, Enum):
    PURCHASE = "PURCHASE"
    IRRRL = "IRRRL"
    CASH_OUT_REFINANCE = "CASH_OUT_REFINANCE"


class Region(str, Enum):
    NORTHEAST = "NORTHEAST"
    MIDWEST = "MIDWEST"
    SOUTH = "SOUTH"
    WEST = "WEST"


class RateType(str, Enum):
    FIXED = "FIXED"
    ARM = "ARM"


class UnderwritingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClosingStatus(str, Enum):
    NOT_CLOSED = "NOT_CLOSED"
    CLOSED = "CLOSED"
    PAID_IN_FULL = "PAID_IN_FULL"


class LoanUse(str, Enum):
    FIRST_USE = "FIRST_USE"
    SUBSEQUENT_USE = "SUBSEQUENT_USE"


class PayoffType(str, Enum):
    SALE = "SALE"
    REFINANCE_PAYOFF = "REFINANCE_PAYOFF"


class FeeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    COLLECTED = "COLLECTED"
    REFUNDED = "REFUNDED"


class AppraisalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    REPAIRS_REQUIRED = "REPAIRS_REQUIRED"
    VALUE_ISSUED = "VALUE_ISSUED"
    CANCELLED = "CANCELLED"


class RepairStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"


class OccupancyStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    SATISFIED = "SATISFIED"
    EXCEPTED = "EXCEPTED"
    VIOLATED = "VIOLATED"


class ExceptionType(str, Enum):
    NONE = "NONE"
    DEPLOYMENT = "DEPLOYMENT"


class DecisionOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AssumptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class RefinanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RefinanceType(str, Enum):
    IRRRL = "IRRRL"
    CASH_OUT = "CASH_OUT"


class RestorationType(str, Enum):
    SALE_PAYOFF = "SALE_PAYOFF"
    REFINANCE_PAYOFF = "REFINANCE_PAYOFF"
    ONE_TIME_RESTORATION = "ONE_TIME_RESTORATION"


class RestorationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"


# ---------------------------------------------------------------------------
# Entity payloads
# ---------------------------------------------------------------------------


class Veteran(TypedDict, total=False):
    id: str
    full_name: str
    ssn_last4: str
    service_category: str
    character_of_discharge: str
    receives_disability_compensation: bool
    is_surviving_spouse: bool
    total_qualifying_service_days: int
    has_issued_coe: bool
    charged_loan_count: int
    created_at: str
    updated_at: str
    version: int


class ServicePeriod(TypedDict, total=False):
    id: str
    veteran_id: str
    branch: str
    start_date: str
    end_date: str
    discharge_character: str
    qualifying_days: int
    created_at: str
    updated_at: str
    version: int


class CertificateOfEligibility(TypedDict, total=False):
    id: str
    veteran_id: str
    status: str
    entitlement_code: str
    denial_reason: Optional[str]
    reconsideration_count: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EntitlementAccount(TypedDict, total=False):
    id: str
    veteran_id: str
    basic_entitlement_cents: int
    county_limit_cents: int
    total_charged_cents: int
    total_restored_cents: int
    remaining_base_cents: int
    remaining_with_bonus_cents: int
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    veteran_id: str
    coe_id: str
    purpose: str
    property_region: str
    purchase_price_cents: int
    down_payment_cents: int
    loan_amount_cents: int
    interest_rate_percent: float
    rate_type: str
    term_months: int
    originator_user_id: str
    underwriting_status: str
    closing_status: str
    loan_use: str
    entitlement_charged_cents: int
    down_payment_pct: float
    closing_date: Optional[str]
    first_payment_due_date: Optional[str]
    payoff_type: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingFeeAssessment(TypedDict, total=False):
    id: str
    loan_id: str
    exempt: bool
    fee_rate: float
    assessed_fee_cents: int
    collected_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraiser(TypedDict, total=False):
    id: str
    name: str
    region: str
    max_open_assignments: int
    open_assignment_count: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict, total=False):
    id: str
    loan_id: str
    appraiser_id: Optional[str]
    status: str
    appraised_value_cents: Optional[int]
    report_round: int
    created_at: str
    updated_at: str
    version: int


class RepairRequirement(TypedDict, total=False):
    id: str
    appraisal_id: str
    description: str
    required_for_clearance: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class OccupancyCertificate(TypedDict, total=False):
    id: str
    loan_id: str
    certification_date: str
    move_in_deadline: str
    status: str
    exception_type: str
    created_at: str
    updated_at: str
    version: int


class DeploymentException(TypedDict, total=False):
    id: str
    veteran_id: str
    deployment_start: str
    deployment_end: str
    orders_reference: str
    created_at: str
    updated_at: str
    version: int


class UnderwritingDecision(TypedDict, total=False):
    id: str
    loan_id: str
    decided_by_user_id: str
    gross_monthly_income_cents: int
    new_housing_payment_cents: int
    other_obligations_annual_cents: List[int]
    family_size: int
    region: str
    other_obligations_monthly_cents: int
    residual_income_cents: int
    residual_required_cents: int
    dti_percent: float
    dti_only_pass: bool
    outcome: str
    created_at: str
    updated_at: str
    version: int


class AssumptionRequest(TypedDict, total=False):
    id: str
    loan_id: str
    buyer_name: str
    buyer_is_veteran: bool
    buyer_veteran_id: Optional[str]
    substitute_entitlement: bool
    release_of_liability: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RefinanceRequest(TypedDict, total=False):
    id: str
    loan_id: str
    refinance_type: str
    new_rate_percent: float
    new_rate_type: str
    flat_costs_cents: int
    seasoning_days: int
    ntb_rate_satisfied: bool
    recoupment_months: int
    ntb_satisfied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EntitlementRestorationRequest(TypedDict, total=False):
    id: str
    veteran_id: str
    loan_id: str
    restoration_type: str
    restored_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    id: str
    created_at: str
    entity_type: str
    entity_id: str
    action: str
    actor_role: str
    actor_user_id: str
    detail: str
