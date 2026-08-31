"""Domain types for the 403(b) & 457 plan administration API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    SYSTEM_OPERATOR = "SystemOperator"
    PLAN_SPONSOR_ADMIN = "PlanSponsorAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    VENDOR_REPRESENTATIVE = "VendorRepresentative"
    PARTICIPANT = "Participant"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

class EntityType(str, Enum):
    PUBLIC_SCHOOL = "PUBLIC_SCHOOL"
    TAX_EXEMPT_501C3 = "TAX_EXEMPT_501C3"
    GOVERNMENTAL_NON_SCHOOL = "GOVERNMENTAL_NON_SCHOOL"
    CHURCH = "CHURCH"


class OrganizationSubtype(str, Enum):
    SCHOOL = "SCHOOL"
    HOSPITAL = "HOSPITAL"
    HOME_HEALTH_AGENCY = "HOME_HEALTH_AGENCY"
    HEALTH_AND_WELFARE_AGENCY = "HEALTH_AND_WELFARE_AGENCY"
    CHURCH_ORG = "CHURCH_ORG"
    OTHER = "OTHER"


class PlanType(str, Enum):
    PLAN_403B = "PLAN_403B"
    PLAN_457B = "PLAN_457B"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    TERMINATED = "TERMINATED"


class NondiscriminationRegime(str, Enum):
    UA_ONLY = "UA_ONLY"
    UA_PLUS_410B_401A4 = "UA_PLUS_410B_401A4"
    GOVERNMENTAL_457_ALL_EMPLOYEES = "GOVERNMENTAL_457_ALL_EMPLOYEES"
    TOP_HAT_457 = "TOP_HAT_457"
    CHURCH_EXEMPT = "CHURCH_EXEMPT"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    UNDER_CORRECTION = "UNDER_CORRECTION"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class LoanEligibilityFlag(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


class DeliveryMethod(str, Enum):
    EMAIL = "EMAIL"
    PAPER_MAIL = "PAPER_MAIL"
    INTRANET_POSTING = "INTRANET_POSTING"
    HAND_DELIVERY = "HAND_DELIVERY"


class AssertedExclusion(str, Enum):
    NONE = "NONE"
    STUDENT = "STUDENT"
    LESS_THAN_20_HOURS = "LESS_THAN_20_HOURS"
    NONRESIDENT_ALIEN = "NONRESIDENT_ALIEN"
    NOT_TOP_HAT_GROUP = "NOT_TOP_HAT_GROUP"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED_STUDENT = "EXCLUDED_STUDENT"
    EXCLUDED_LESS_THAN_20_HOURS = "EXCLUDED_LESS_THAN_20_HOURS"
    EXCLUDED_NONRESIDENT_ALIEN = "EXCLUDED_NONRESIDENT_ALIEN"
    EXCLUDED_NOT_TOP_HAT_GROUP = "EXCLUDED_NOT_TOP_HAT_GROUP"
    INELIGIBLE_PLAN_NOT_ACTIVE = "INELIGIBLE_PLAN_NOT_ACTIVE"


class NoticeStatus(str, Enum):
    CURRENT = "CURRENT"
    INVALID = "INVALID"
    MISSING = "MISSING"


class VendorAccountStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CatchupElection(str, Enum):
    NONE = "NONE"
    AGE_50 = "AGE_50"
    SERVICE_15_YEAR = "SERVICE_15_YEAR"
    FINAL_3_YEAR = "FINAL_3_YEAR"
    AGE_50_AND_SERVICE_15_YEAR = "AGE_50_AND_SERVICE_15_YEAR"


class ElectionState(str, Enum):
    SUBMITTED = "SUBMITTED"
    EFFECTIVE = "EFFECTIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class DepositState(str, Enum):
    WITHHELD = "WITHHELD"
    DEPOSITED = "DEPOSITED"
    REVERSED = "REVERSED"


class ComplianceState(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    TIMELY = "TIMELY"
    LATE = "LATE"
    CORRECTION_PENDING = "CORRECTION_PENDING"
    CORRECTED = "CORRECTED"


class CorrectionState(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class RequestType(str, Enum):
    LOAN = "LOAN"
    HARDSHIP = "HARDSHIP"
    UNFORESEEABLE_EMERGENCY = "UNFORESEEABLE_EMERGENCY"


class SafeHarborReason(str, Enum):
    NONE = "NONE"
    MEDICAL_EXPENSES = "MEDICAL_EXPENSES"
    PURCHASE_PRINCIPAL_RESIDENCE = "PURCHASE_PRINCIPAL_RESIDENCE"
    TUITION = "TUITION"
    PREVENT_EVICTION = "PREVENT_EVICTION"
    FUNERAL = "FUNERAL"
    CASUALTY_REPAIR = "CASUALTY_REPAIR"
    DISASTER = "DISASTER"


class EmergencyReason(str, Enum):
    NONE = "NONE"
    ILLNESS_OF_PARTICIPANT_OR_DEPENDENT = "ILLNESS_OF_PARTICIPANT_OR_DEPENDENT"
    LOSS_OF_PROPERTY_CASUALTY = "LOSS_OF_PROPERTY_CASUALTY"
    IMMINENT_FORECLOSURE_OR_EVICTION = "IMMINENT_FORECLOSURE_OR_EVICTION"
    FUNERAL_EXPENSES = "FUNERAL_EXPENSES"
    EXTRAORDINARY_MEDICAL = "EXTRAORDINARY_MEDICAL"
    COLLEGE_TUITION = "COLLEGE_TUITION"
    PURCHASE_OF_HOME = "PURCHASE_OF_HOME"


class ParticipantRequestState(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISBURSED = "DISBURSED"
    PAID = "PAID"


class RequestKind(str, Enum):
    CONTRACT_EXCHANGE = "CONTRACT_EXCHANGE"
    PLAN_TO_PLAN_TRANSFER = "PLAN_TO_PLAN_TRANSFER"


class TransferExchangeState(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED_BY_VENDOR = "ACCEPTED_BY_VENDOR"
    REJECTED_BY_VENDOR = "REJECTED_BY_VENDOR"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTED = "EXECUTED"
    REVERSED = "REVERSED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------

class Employer(TypedDict):
    id: str
    legal_name: str
    ein: str
    entity_type: str
    organization_subtype: str
    total_employee_count: int
    is_governmental: bool
    is_qualified_organization: bool
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    employer_id: str
    plan_name: str
    plan_type: str
    plan_year: int
    reported_participant_count: int
    status: str
    is_small_plan: bool
    is_governmental_457: bool
    nondiscrimination_regime: str
    permits_loans: bool
    permits_hardship: bool
    permits_unforeseeable_emergency: bool
    permits_contract_exchanges: bool
    permits_incoming_transfers: bool
    permits_outgoing_transfers: bool
    open_correction_count: int
    compliance_posture: str
    projected_excess_participant_count: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    legal_name: str
    vendor_code: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class InformationSharingAgreement(TypedDict):
    id: str
    plan_id: str
    vendor_id: str
    status: str
    effective_from: str
    effective_through: str
    shares_loan_data: bool
    shares_hardship_data: bool
    shares_contribution_data: bool
    data_current_through_date: Optional[str]
    data_stale: bool
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    employer_id: str
    full_name: str
    date_of_birth: str
    hire_date: str
    employment_status: str
    termination_date: Optional[str]
    scheduled_hours_per_week: float
    prior_year_hours_worked: int
    is_student_performing_services: bool
    is_nonresident_alien_no_us_income: bool
    is_select_management_or_hce: bool
    includible_compensation_cents: int
    years_of_service: float
    prior_employer_elective_deferrals_cents: int
    underutilized_prior_limit_cents: int
    cumulative_special_catchup_used_cents: int
    attained_age_at_year_end: int
    lifetime_elective_deferrals_cents: int
    total_accumulated_benefit_cents: int
    total_vested_balance_cents: int
    total_outstanding_loan_balance_cents: int
    highest_outstanding_loan_12mo_cents: int
    loan_eligibility_flag: str
    projected_annual_deferral_cents: int
    created_at: str
    updated_at: str
    version: int


class UniversalAvailabilityNotice(TypedDict):
    # An immutable compliance record: id and created_at only, no updated_at
    # and no version.
    id: str
    plan_id: str
    plan_year: int
    issued_date: str
    delivery_method: str
    recipient_count: int
    describes_effective_opportunity: bool
    is_valid: bool
    created_at: str


class EligibilityDetermination(TypedDict):
    id: str
    plan_id: str
    participant_id: str
    asserted_exclusion: str
    determined_at: str
    determined_by_user_id: str
    status: str
    exclusion_basis: Optional[str]
    notice_status: str
    universal_availability_applies: bool
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class VendorAccount(TypedDict):
    id: str
    participant_id: str
    plan_id: str
    vendor_id: str
    contract_number: str
    accumulated_benefit_cents: int
    vested_percentage_bps: int
    vested_balance_cents: int
    outstanding_loan_balance_cents: int
    highest_outstanding_loan_12mo_cents: int
    ytd_elective_deferrals_cents: int
    ytd_employer_contributions_cents: int
    prior_years_elective_deferrals_cents: int
    pending_lost_earnings_cents: int
    last_balance_report_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContributionElection(TypedDict):
    id: str
    participant_id: str
    plan_id: str
    vendor_account_id: str
    supersedes_election_id: Optional[str]
    annual_deferral_amount_cents: int
    effective_from: str
    effective_through: str
    catchup_election: str
    state: str
    basic_deferral_attributed_cents: int
    service_catchup_attributed_cents: int
    age50_catchup_attributed_cents: int
    final3yr_catchup_attributed_cents: int
    submitted_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemittanceBatch(TypedDict):
    id: str
    plan_id: str
    pay_period_start: str
    pay_period_end: str
    withholding_date: str
    total_elective_deferral_cents: int
    line_items: List[dict]
    segregation_feasible_date: Optional[str]
    deposit_state: str
    compliance_state: str
    deposit_date: Optional[str]
    deadline_date: Optional[str]
    calendar_days_late: int
    business_days_late: int
    created_at: str
    updated_at: str
    version: int


class RemittanceCorrection(TypedDict):
    id: str
    remittance_batch_id: str
    lost_earnings_total_cents: int
    excise_tax_cents: int
    line_breakdown: List[dict]
    state: str
    settlement_reference: Optional[str]
    settled_at: Optional[str]
    settled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParticipantRequest(TypedDict):
    id: str
    participant_id: str
    plan_id: str
    vendor_account_id: str
    request_type: str
    requested_amount_cents: int
    stated_need_cents: int
    estimated_taxes_cents: int
    safe_harbor_reason: str
    emergency_reason: str
    insurance_reimbursement_available_cents: int
    liquidatable_assets_cents: int
    deferral_cessation_relief_cents: int
    loan_term_months: Optional[int]
    state: str
    max_approvable_cents: Optional[int]
    approved_amount_cents: Optional[int]
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    resubmission_count: int
    denial_reason: Optional[str]
    fulfillment_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferExchangeRequest(TypedDict):
    id: str
    participant_id: str
    request_kind: str
    source_plan_id: str
    destination_plan_id: str
    source_vendor_account_id: str
    destination_vendor_account_id: str
    amount_cents: int
    state: str
    vendor_rejection_reason: Optional[str]
    denial_reason: Optional[str]
    pre_move_source_benefit_cents: Optional[int]
    pre_move_destination_benefit_cents: Optional[int]
    executed_at: Optional[str]
    resubmit_count: int
    created_at: str
    updated_at: str
    version: int
