"""Domain types for the Incentive Travel Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    SOURCING_MANAGER = "SourcingManager"
    CONTRACT_APPROVER = "ContractApprover"
    SALES_OPS_ANALYST = "SalesOpsAnalyst"
    TRAVEL_DESK = "TravelDesk"
    TAX_COMPLIANCE_OFFICER = "TaxComplianceOfficer"
    PARTICIPANT = "Participant"


ALL_ROLES = [r.value for r in UserRole]
OPERATOR_ROLES = [
    UserRole.PROGRAM_DIRECTOR.value,
    UserRole.SOURCING_MANAGER.value,
    UserRole.CONTRACT_APPROVER.value,
    UserRole.SALES_OPS_ANALYST.value,
    UserRole.TRAVEL_DESK.value,
    UserRole.TAX_COMPLIANCE_OFFICER.value,
]


# ─── Program (PRD §3.1) ──────────────────────────────────────────────────────

class ProgramStatus(str, Enum):
    DESIGN = "DESIGN"
    SOURCING = "SOURCING"
    CONTRACTED = "CONTRACTED"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    ONSITE = "ONSITE"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class QualificationMetric(str, Enum):
    NET_REVENUE_CENTS = "NET_REVENUE_CENTS"
    UNITS_SOLD = "UNITS_SOLD"
    MARGIN_CENTS = "MARGIN_CENTS"


class GrossUpPolicy(str, Enum):
    NONE = "NONE"
    FLAT_SUPPLEMENTAL = "FLAT_SUPPLEMENTAL"
    FULL_GROSS_UP = "FULL_GROSS_UP"


class BudgetPosture(str, Enum):
    OK = "OK"
    WATCH = "WATCH"
    OVERCOMMITTED = "OVERCOMMITTED"


class Program(TypedDict):
    id: str
    name: str
    fiscal_year: int
    qualification_metric: str
    sales_period_start: str
    sales_period_end: str
    budget_total_cents: int
    status: str
    gross_up_policy: str
    gross_up_policy_locked: bool
    per_person_cost_basis_cents: int
    committed_budget_cents: int
    budget_headroom_cents: int
    budget_posture: str
    cancellation_exposure_cents: int
    reported_award_total_cents: int
    sales_lift_pct: Optional[float]
    satisfaction_index: Optional[float]
    qualified_count: int
    travelled_count: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── AwardTier (PRD §3.1) ────────────────────────────────────────────────────

class AirCabinClass(str, Enum):
    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"


class AwardTier(TypedDict):
    """A tier is immutable: it carries only id and created_at (PRD §2.4)."""
    id: str
    program_id: str
    tier_code: str
    tier_rank: int
    qualification_threshold: int
    budget_per_qualifier_cents: int
    guest_allowance: int
    air_cabin_class: str
    upgrade_allowance_cents: int
    service_load_bp: int
    created_at: str


# ─── Qualifier (PRD §3.2) ────────────────────────────────────────────────────

class QualifierAwardStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    NOTIFIED = "NOTIFIED"
    REGISTERED = "REGISTERED"
    TRAVELLED = "TRAVELLED"
    WITHDRAWN = "WITHDRAWN"


class QualifierTaxStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_REPORT = "PENDING_REPORT"
    REPORTED = "REPORTED"
    VOIDED = "VOIDED"


class Qualifier(TypedDict):
    id: str
    program_id: str
    employee_code: str
    full_name: str
    baseline_metric: int
    actual_metric: int
    guest_count: int
    award_status: str
    tax_status: str
    assigned_tier_id: Optional[str]
    committed_cost_cents: int
    taxable_award_cents: int
    notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Destination (PRD §3.3) ──────────────────────────────────────────────────

class DestinationStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    SHORTLISTED = "SHORTLISTED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class InspectionStatus(str, Enum):
    NOT_INSPECTED = "NOT_INSPECTED"
    INSPECTED = "INSPECTED"


class Destination(TypedDict):
    id: str
    program_id: str
    city: str
    country_code: str
    per_person_cost_cents: int
    risk_score: int
    air_gateway_code: str
    status: str
    inspection_status: str
    inspection_score: Optional[int]
    inspected_by_user_id: Optional[str]
    inspected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── SupplierContract (PRD §3.4) ─────────────────────────────────────────────

class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"


class SupplierKind(str, Enum):
    HOTEL = "HOTEL"
    DMC = "DMC"
    AIR_CONSOLIDATOR = "AIR_CONSOLIDATOR"


class ForceMajeureClause(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    EXPANDED = "EXPANDED"


class ExposureBasis(str, Enum):
    ATTRITION_BASIS = "ATTRITION_BASIS"
    DEPOSIT_FORFEITURE_BASIS = "DEPOSIT_FORFEITURE_BASIS"


class AttritionPosture(str, Enum):
    CLEAR = "CLEAR"
    AT_RISK = "AT_RISK"


class NegotiationAction(str, Enum):
    PROPOSE = "PROPOSE"
    COUNTER = "COUNTER"


class SupplierContract(TypedDict):
    id: str
    program_id: str
    destination_id: str
    supplier_name: str
    supplier_kind: str
    status: str
    round_count: int
    room_block_count: int
    contracted_nights: int
    stay_start_at: str
    stay_end_at: str
    nightly_rate_cents: int
    attrition_allowance_bp: int
    force_majeure_clause: str
    exposure_basis: str
    room_nights_blocked: int
    room_nights_confirmed: int
    room_nights_available: int
    attrition_posture: str
    last_proposed_by_user_id: Optional[str]
    last_countered_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]
    executed_at: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── DepositMilestone (PRD §3.5) ─────────────────────────────────────────────

class MilestoneStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class DepositMilestone(TypedDict):
    id: str
    contract_id: str
    sequence: int
    due_at: str
    amount_cents: int
    refundable_bp: int
    status: str
    requires_finance_review: bool
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Registration (PRD §3.6, §3.7) ───────────────────────────────────────────

class RegistrationKind(str, Enum):
    WINNER = "WINNER"
    GUEST = "GUEST"


class AttendanceStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    TRAVELLED = "TRAVELLED"


class AirStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    REQUESTED = "REQUESTED"
    TICKETED = "TICKETED"
    CHANGE_PENDING = "CHANGE_PENDING"
    VOIDED = "VOIDED"


class AirAction(str, Enum):
    REQUEST = "REQUEST"
    TICKET = "TICKET"
    CHANGE = "CHANGE"


class InvitationResponse(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class Registration(TypedDict):
    id: str
    program_id: str
    qualifier_id: str
    registration_kind: str
    guest_of_registration_id: Optional[str]
    attendance_status: str
    arrival_date: str
    departure_date: str
    rooms: int
    room_nights: int
    waiver_on_file: bool
    air_status: str
    air_cabin_class: Optional[str]
    air_deviation_pre_days: int
    air_deviation_post_days: int
    air_base_fare_cents: int
    air_upgrade_cost_cents: int
    air_deviation_fee_cents: int
    air_change_count: int
    air_change_fee_total_cents: int
    cost_cents: int
    satisfaction_score: Optional[int]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── OnsiteActivity / ActivitySignup (PRD §3.8) ──────────────────────────────

class ActivityStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OnsiteActivity(TypedDict):
    id: str
    program_id: str
    name: str
    start_at: str
    end_at: str
    capacity: int
    risk_level: str
    status: str
    booked_count: int
    waitlist_count: int
    created_at: str
    updated_at: str
    version: int


class SignupStatus(str, Enum):
    BOOKED = "BOOKED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class ActivitySignup(TypedDict):
    id: str
    activity_id: str
    registration_id: str
    status: str
    promoted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── TaxAwardReport (PRD §3.9) ───────────────────────────────────────────────

class TaxReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    VOIDED = "VOIDED"


class TaxAwardReport(TypedDict):
    id: str
    qualifier_id: str
    tax_year: int
    award_value_cents: int
    gross_up_method: str
    combined_rate_bp: int
    gross_up_cents: int
    reported_value_cents: int
    status: str
    filed_by_user_id: Optional[str]
    filed_at: Optional[str]
    voided_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole", "ALL_ROLES", "OPERATOR_ROLES",
    "ProgramStatus", "QualificationMetric", "GrossUpPolicy", "BudgetPosture", "Program",
    "AirCabinClass", "AwardTier",
    "QualifierAwardStatus", "QualifierTaxStatus", "Qualifier",
    "DestinationStatus", "InspectionStatus", "Destination",
    "ContractStatus", "SupplierKind", "ForceMajeureClause", "ExposureBasis",
    "AttritionPosture", "NegotiationAction", "SupplierContract",
    "MilestoneStatus", "DepositMilestone",
    "RegistrationKind", "AttendanceStatus", "AirStatus", "AirAction",
    "InvitationResponse", "Registration",
    "ActivityStatus", "RiskLevel", "OnsiteActivity",
    "SignupStatus", "ActivitySignup",
    "TaxReportStatus", "TaxAwardReport",
    "List", "Optional",
]
