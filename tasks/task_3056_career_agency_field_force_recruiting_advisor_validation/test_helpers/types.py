"""Domain types: entity dictionaries, status enums and the role enum.

Every entity in this system carries the full common field set (both timestamp
and version), so each TypedDict below declares id / created_at / updated_at /
version alongside its entity-specific fields.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MANAGING_DIRECTOR = "ManagingDirector"
    DISTRICT_DIRECTOR = "DistrictDirector"
    FINANCIAL_REP = "FinancialRep"
    RECRUITING_OFFICER = "RecruitingOfficer"
    LICENSING_COORDINATOR = "LicensingCoordinator"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class OfficeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AdvisorRank(str, Enum):
    REP = "REP"
    DISTRICT_DIRECTOR = "DISTRICT_DIRECTOR"
    MANAGING_DIRECTOR = "MANAGING_DIRECTOR"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    NOT_CONTRACTED = "NOT_CONTRACTED"
    ACTIVE_TRAINING = "ACTIVE_TRAINING"
    VALIDATING = "VALIDATING"
    AT_RISK = "AT_RISK"
    VALIDATED = "VALIDATED"
    TERMINATED = "TERMINATED"


class ValidationPosture(str, Enum):
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    AT_RISK = "AT_RISK"
    FAILED_POSTURE = "FAILED_POSTURE"


class InsuranceLicenseStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class SecuritiesRegistrationStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AppointmentStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    TERMINATED = "TERMINATED"


class ProductLine(str, Enum):
    LIFE = "LIFE"
    ANNUITY = "ANNUITY"
    DISABILITY = "DISABILITY"
    LONG_TERM_CARE = "LONG_TERM_CARE"


class SourceChannel(str, Enum):
    CAMPUS = "CAMPUS"
    CAREER_CHANGER = "CAREER_CHANGER"
    REFERRAL = "REFERRAL"
    INTERNAL = "INTERNAL"


class CandidateStage(str, Enum):
    SOURCED = "SOURCED"
    SCREENED = "SCREENED"
    ASSESSMENT_PENDING = "ASSESSMENT_PENDING"
    ASSESSED = "ASSESSED"
    INTERVIEW_READY = "INTERVIEW_READY"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_DECLINED = "OFFER_DECLINED"
    REENGAGED = "REENGAGED"
    REJECTED = "REJECTED"
    CONTRACTED = "CONTRACTED"


class AssessmentVersion(str, Enum):
    V1 = "V1"
    V2 = "V2"


class AssessmentOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class AssessmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SCORED = "SCORED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class EmploymentContractType(str, Enum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    INTERN = "INTERN"


class TrainingAllowanceMode(str, Enum):
    FLAT_MONTHLY = "FLAT_MONTHLY"
    PRODUCTION_DRAW = "PRODUCTION_DRAW"


class ValidationPeriodStatus(str, Enum):
    OPEN = "OPEN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXTENDED = "EXTENDED"


class ProductLicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class RegistrationType(str, Enum):
    SERIES_6 = "SERIES_6"
    SERIES_7 = "SERIES_7"
    SERIES_63 = "SERIES_63"
    SERIES_65 = "SERIES_65"
    SERIES_66 = "SERIES_66"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AppointmentLifecycle(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


class PolicyStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    SURRENDERED = "SURRENDERED"
    TERMINATED = "TERMINATED"


class JointWorkCaseStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class CreditType(str, Enum):
    PRIMARY = "PRIMARY"
    SPLIT_LEAD = "SPLIT_LEAD"
    SPLIT_SUPPORT = "SPLIT_SUPPORT"
    OVERRIDE_DO = "OVERRIDE_DO"
    OVERRIDE_MD = "OVERRIDE_MD"
    TRAINING_ALLOWANCE = "TRAINING_ALLOWANCE"
    RENEWAL = "RENEWAL"


class CreditStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    CHARGED_BACK = "CHARGED_BACK"
    RECOVERED = "RECOVERED"
    VOIDED = "VOIDED"


class ChargebackReason(str, Enum):
    LAPSE_WITHIN_12MO = "LAPSE_WITHIN_12MO"
    SURRENDER = "SURRENDER"
    REPLACEMENT = "REPLACEMENT"
    TERMINATION = "TERMINATION"


class PersistencyTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    INELIGIBLE = "INELIGIBLE"


class PersistencyStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"


class OrphanAssignmentStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    REJECTED = "REJECTED"


class OrphanAssignmentMethod(str, Enum):
    ROUND_ROBIN = "ROUND_ROBIN"
    SENIORITY = "SENIORITY"
    MANUAL = "MANUAL"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class DistrictOffice(TypedDict, total=False):
    id: str
    office_code: str
    name: str
    region_code: str
    state_code: str
    override_rate_pct: float
    override_cap_cents: int
    override_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Advisor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    district_office_id: str
    sponsoring_advisor_id: Optional[str]
    rank: str
    contract_status: str
    validation_posture: str
    insurance_license_status: str
    securities_registration_status: str
    appointment_status: str
    licensing_locked: bool
    team_production_cents: int
    override_income_cents: int
    chargeback_balance_cents: int
    renewal_commission_cents: int
    orphan_pool_access: bool
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecruitingCandidate(TypedDict, total=False):
    id: str
    full_name: str
    source_channel: str
    campus_name: Optional[str]
    district_office_id: str
    prior_candidate_id: Optional[str]
    stage: str
    reengagement_count: int
    entered_stage_at: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelectionAssessment(TypedDict, total=False):
    id: str
    candidate_id: str
    assessment_version: str
    scheduled_date: str
    scored_date: Optional[str]
    raw_score: Optional[int]
    competency_scores: Optional[Dict[str, int]]
    weighted_score: Optional[float]
    outcome: Optional[str]
    locked_weights: Optional[Dict[str, float]]
    status: str
    created_at: str
    updated_at: str
    version: int


class EmploymentContract(TypedDict, total=False):
    id: str
    advisor_id: str
    candidate_id: str
    contract_type: str
    start_date: str
    end_date: Optional[str]
    training_allowance_total_cents: int
    training_allowance_paid_cents: int
    validation_requirement_cents: int
    training_allowance_mode: str
    contract_status: str
    created_at: str
    updated_at: str
    version: int


class ValidationPeriod(TypedDict, total=False):
    id: str
    contract_id: str
    advisor_id: str
    period_number: int
    start_date: str
    end_date: str
    required_production_cents: int
    achieved_production_cents: int
    extension_count: int
    extended_end_date: Optional[str]
    evaluated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductLicense(TypedDict, total=False):
    id: str
    advisor_id: str
    product_line: str
    license_number: str
    effective_date: str
    expires_at: str
    appointment_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SecuritiesRegistration(TypedDict, total=False):
    id: str
    advisor_id: str
    registration_type: str
    crd_number: str
    effective_date: str
    expires_at: str
    prerequisite_registration_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarrierAppointment(TypedDict, total=False):
    id: str
    advisor_id: str
    requires_license_id: str
    carrier_name: str
    state_code: str
    requested_date: str
    appointment_date: Optional[str]
    appointment_status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    policy_number: str
    writing_advisor_id: str
    carrier_name: str
    product_line: str
    annual_premium_cents: int
    issue_date: str
    lapse_date: Optional[str]
    reinstatement_date: Optional[str]
    is_advanced_commission: bool
    months_inforce: int
    orphaned: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class JointWorkCase(TypedDict, total=False):
    id: str
    policy_id: str
    lead_advisor_id: str
    support_advisor_id: str
    split_pct_lead: float
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionCredit(TypedDict, total=False):
    id: str
    policy_id: str
    advisor_id: str
    credit_type: str
    credit_pct: float
    gross_commission_cents: int
    net_commission_cents: int
    advanced_paid_cents: int
    case_gross_commission_cents: int
    chargeback_assessed_cents: int
    recovered_cents: int
    chargeback_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PersistencyRecord(TypedDict, total=False):
    id: str
    advisor_id: str
    measurement_period: str
    measurement_start: str
    measurement_end: str
    policies_issued: int
    policies_persisted: int
    persistency_pct: Optional[float]
    persistency_tier: Optional[str]
    renewal_rate_pct: Optional[float]
    renewal_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrphanPolicyAssignment(TypedDict, total=False):
    id: str
    policy_id: str
    from_advisor_id: str
    to_advisor_id: Optional[str]
    assignment_method: str
    assigned_at: Optional[str]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


ENTITY_MODEL: Dict[str, Any] = {
    "DistrictOffice": DistrictOffice,
    "Advisor": Advisor,
    "RecruitingCandidate": RecruitingCandidate,
    "SelectionAssessment": SelectionAssessment,
    "EmploymentContract": EmploymentContract,
    "ValidationPeriod": ValidationPeriod,
    "ProductLicense": ProductLicense,
    "SecuritiesRegistration": SecuritiesRegistration,
    "CarrierAppointment": CarrierAppointment,
    "Policy": Policy,
    "JointWorkCase": JointWorkCase,
    "CommissionCredit": CommissionCredit,
    "PersistencyRecord": PersistencyRecord,
    "OrphanPolicyAssignment": OrphanPolicyAssignment,
}