"""Domain types: entity TypedDicts, status enums, role enum.

Every addressable record in this API carries the four system-managed
properties (`id`, `created_at`, `updated_at`, `version`).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class FunderType(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    COUNTY = "COUNTY"
    PRIVATE_FOUNDATION = "PRIVATE_FOUNDATION"
    DIOCESAN = "DIOCESAN"
    PARISH = "PARISH"


class FunderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceDomain(str, Enum):
    HOUSING = "HOUSING"
    FOOD = "FOOD"
    COUNSELING = "COUNSELING"
    IMMIGRATION = "IMMIGRATION"
    REFUGEE = "REFUGEE"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class GrantStatus(str, Enum):
    OPEN = "OPEN"
    THROTTLED = "THROTTLED"
    FROZEN = "FROZEN"


class CostAllocationBasis(str, Enum):
    DIRECT_ONLY = "DIRECT_ONLY"
    HEADCOUNT = "HEADCOUNT"
    TIME_AND_EFFORT = "TIME_AND_EFFORT"
    SQUARE_FOOTAGE = "SQUARE_FOOTAGE"


class RestrictedPurpose(str, Enum):
    HOUSING_ASSISTANCE = "HOUSING_ASSISTANCE"
    FOOD_DISTRIBUTION = "FOOD_DISTRIBUTION"
    CLINICAL_COUNSELING = "CLINICAL_COUNSELING"
    LEGAL_IMMIGRATION = "LEGAL_IMMIGRATION"
    REFUGEE_RESETTLEMENT = "REFUGEE_RESETTLEMENT"
    GENERAL_OPERATING = "GENERAL_OPERATING"


class ImmigrationStatus(str, Enum):
    CITIZEN = "CITIZEN"
    LPR = "LPR"
    REFUGEE = "REFUGEE"
    ASYLEE = "ASYLEE"
    UNDOCUMENTED = "UNDOCUMENTED"
    PENDING_ASYLUM = "PENDING_ASYLUM"


class ConfidentialityTier(str, Enum):
    STANDARD = "STANDARD"
    PROTECTED = "PROTECTED"
    SEALED = "SEALED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ROUTED = "ROUTED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"


class RoutingOutcome(str, Enum):
    PENDING = "PENDING"
    ROUTED = "ROUTED"
    NO_ELIGIBLE_PROGRAM = "NO_ELIGIBLE_PROGRAM"
    WITHDRAWN = "WITHDRAWN"


class ReturnReasonCode(str, Enum):
    INCOMPLETE_INCOME = "INCOMPLETE_INCOME"
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    WRONG_DOMAIN = "WRONG_DOMAIN"


class Determination(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class DenialReasonCode(str, Enum):
    INCOME_OVER_LIMIT = "INCOME_OVER_LIMIT"
    RESIDENCY = "RESIDENCY"
    IMMIGRATION_STATUS = "IMMIGRATION_STATUS"
    PROGRAM_AT_CAPACITY = "PROGRAM_AT_CAPACITY"
    CONFIDENTIALITY_BAR = "CONFIDENTIALITY_BAR"


class VerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"
    DENIED = "DENIED"


class ExitReason(str, Enum):
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    TRANSFERRED = "TRANSFERRED"
    GRANT_TERMINATED = "GRANT_TERMINATED"
    NONCOMPLIANCE = "NONCOMPLIANCE"


class ServiceCode(str, Enum):
    HOUSING_RENT_ASSIST = "HOUSING_RENT_ASSIST"
    FOOD_PANTRY_BOX = "FOOD_PANTRY_BOX"
    CLINICAL_COUNSELING_HOUR = "CLINICAL_COUNSELING_HOUR"
    IMMIGRATION_LEGAL_HOUR = "IMMIGRATION_LEGAL_HOUR"
    REFUGEE_CASE_MGMT_HOUR = "REFUGEE_CASE_MGMT_HOUR"


class AuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class DeliveryStatus(str, Enum):
    DRAFT = "DRAFT"
    DOCUMENTED = "DOCUMENTED"
    BILLED = "BILLED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class DocumentationStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"


class AllocationLineStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    COMMITTED = "COMMITTED"
    REVERSED = "REVERSED"


class AllocationBasis(str, Enum):
    RANKED_PRIORITY = "RANKED_PRIORITY"
    CHRONOLOGICAL_PERIOD = "CHRONOLOGICAL_PERIOD"


class DonorType(str, Enum):
    PARISH = "PARISH"
    VOLUNTEER = "VOLUNTEER"
    CORPORATE = "CORPORATE"


class ValuationMethod(str, Enum):
    IRS_STANDARD_RATE = "IRS_STANDARD_RATE"
    APPRAISAL = "APPRAISAL"
    ACTUAL_COST = "ACTUAL_COST"
    UNVALUED = "UNVALUED"


class InKindStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class MeasureCode(str, Enum):
    HOUSING_PLACEMENTS = "HOUSING_PLACEMENTS"
    FOOD_UNITS_DISTRIBUTED = "FOOD_UNITS_DISTRIBUTED"
    COUNSELING_COMPLETION = "COUNSELING_COMPLETION"
    IMMIGRATION_CASES_CLOSED = "IMMIGRATION_CASES_CLOSED"
    REFUGEE_EMPLOYMENT = "REFUGEE_EMPLOYMENT"


class OutcomeReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class DenominatorBasis(str, Enum):
    ALL_SERVED = "ALL_SERVED"
    COMPLETED_ONLY = "COMPLETED_ONLY"


class UserRole(str, Enum):
    INTAKE_SPECIALIST = "IntakeSpecialist"
    PROGRAM_MANAGER = "ProgramManager"
    FINANCE_OFFICER = "FinanceOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLIENT = "Client"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity TypedDicts (all twelve carry id + created_at + updated_at + version) ---

class Funder(TypedDict):
    id: str
    name: str
    funder_type: str
    allow_faith_based_activity: bool
    requires_time_and_effort_documentation: bool
    max_admin_rate_pct: float
    fiscal_year_start_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    name: str
    service_domain: str
    faith_based_activity_offered: bool
    nondiscrimination_attested: bool
    capacity_slots: int
    enrolled_slots: int
    active_slots: int
    match_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict):
    id: str
    funder_id: str
    program_id: str
    grant_code: str
    total_award_cents: int
    expended_cents: int
    obligated_cents: int
    admin_rate_pct: float
    allocation_rank: int
    max_in_kind_rate_cents: int
    matching_requirement_pct: float
    cost_allocation_basis: str
    restricted_purpose: str
    period_start: str
    period_end: str
    burn_ratio: float
    status: str
    posture_computed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    household_size: int
    immigration_status: str
    county_code: str
    confidentiality_tier: str
    consent_scope: List[str]
    consent_expires_on: Optional[str]
    open_enrollment_count: int
    shareable_domains: List[str]
    created_at: str
    updated_at: str
    version: int


class IntakeAssessment(TypedDict):
    id: str
    client_id: str
    assessment_date: str
    presenting_needs: List[str]
    requested_domains: List[str]
    assessed_by_user_id: str
    routing_outcome: str
    return_reason_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EligibilityScreen(TypedDict):
    id: str
    intake_assessment_id: str
    program_id: str
    grant_id: str
    verified_income_cents: int
    household_size_at_screen: int
    determination: str
    denial_reason_code: Optional[str]
    verification_state: str
    screened_at: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    client_id: str
    program_id: str
    grant_id: str
    enrolled_at: str
    exited_at: Optional[str]
    exit_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceAuthorization(TypedDict):
    id: str
    enrollment_id: str
    grant_id: str
    service_code: str
    authorized_units: int
    unit_rate_cents: int
    units_delivered: int
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceDelivery(TypedDict):
    id: str
    service_authorization_id: str
    grant_id: str
    client_id: str
    service_date: str
    sequence_no: int
    units_delivered: int
    unit_rate_cents: int
    gross_cost_cents: int
    allocated_total_cents: int
    admin_total_cents: int
    alternate_disallowed_cents: int
    documentation_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CostAllocation(TypedDict):
    id: str
    service_delivery_id: str
    grant_id: str
    allocation_rank: int
    allocated_amount_cents: int
    admin_amount_cents: int
    allocation_basis: str
    disallowed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InKindDonation(TypedDict):
    id: str
    grant_id: str
    donor_type: str
    donor_reference: str
    donation_date: str
    hours: float
    valuation_method: str
    rate_cents: int
    value_cents: int
    uncapped_value_cents: int
    match_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeReport(TypedDict):
    id: str
    grant_id: str
    measure_code: str
    reporting_period_start: str
    reporting_period_end: str
    numerator: int
    denominator: int
    denominator_basis: str
    rate_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int
