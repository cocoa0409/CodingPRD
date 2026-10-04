"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource descriptions (sections 2.4 and 3.1-3.10).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class Bureau(TypedDict, total=False):
    id: str
    code: str
    name: str
    eligibility_threshold_cents: int
    split_point_cents: int
    credibility_ballast_bp: int
    credibility_excess_divisor_bp: int
    underwriting_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    naic_number: str
    legal_name: str
    assigned_risk_quota_cents: int
    assigned_risk_current_load_cents: int
    status: str  # ACTIVE | SUSPENDED
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict, total=False):
    id: str
    fein: str
    legal_name: str
    state_code: str
    status: str  # ACTIVE | UNDER_REVIEW | INACTIVE
    created_at: str
    updated_at: str
    version: int


# ClassCode is the single exception to common resource properties (PRD section
# 2.4): it carries id and created_at only - no updated_at, no version.
class ClassCode(TypedDict, total=False):
    id: str
    code: str
    description: str
    state_code: str
    status: str  # ACTIVE | RETIRED
    created_at: str


class RatingTableValue(TypedDict):
    class_code: str
    rate_per_100_payroll_cents: int
    elr_per_100_payroll_cents: int
    d_ratio_bp: int


class RatingTable(TypedDict, total=False):
    id: str
    state_code: str
    effective_date: str
    status: str  # DRAFT | PROMULGATED | SUPERSEDED
    values: List[RatingTableValue]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PolicyClassLine(TypedDict):
    class_code: str
    payroll_dollars: int


class Policy(TypedDict, total=False):
    id: str
    employer_id: str
    carrier_id: str
    policy_number: str
    effective_date: str
    expiration_date: str
    manual_premium_cents: int
    status: str  # ACTIVE | CANCELLED | EXPIRED
    class_codes: List[PolicyClassLine]
    unit_stat_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollLine(TypedDict):
    class_code: str
    payroll_dollars: int


class ClaimLine(TypedDict):
    claim_number: str
    claim_type: str  # INDEMNITY | MEDICAL
    incurred_cents: int
    paid_cents: int
    claim_status: str  # OPEN | CLOSED
    state_code: str


class UnitStatReport(TypedDict, total=False):
    id: str
    policy_id: str
    payroll_lines: List[PayrollLine]
    claim_lines: List[ClaimLine]
    status: str  # SUBMITTED | VALIDATED | LOCKED | CORRECTED
    submission_number: int
    correction_of_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClassAssignment(TypedDict, total=False):
    id: str
    employer_id: str
    class_code_id: str
    effective_date: str
    status: str  # PENDING_INSPECTION | ASSIGNED | DISPUTED | CONFIRMED | REASSIGNED | WITHDRAWN
    inspection_id: Optional[str]
    dispute_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    class_assignment_id: str
    inspector_id: str
    scheduled_date: str
    status: str  # SCHEDULED | COMPLETED | WAIVED
    findings: str
    created_at: str
    updated_at: str
    version: int


class ClassAssignmentDispute(TypedDict, total=False):
    id: str
    class_assignment_id: str
    employer_id: str
    reason: str  # WRONG_CLASS | PAYROLL_MISMATCH | OTHER
    status: str  # OPEN | IN_REVIEW | RESOLVED | WITHDRAWN
    resolution: Optional[str]  # CONFIRMED | REASSIGNED | null
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExperienceModSheet(TypedDict, total=False):
    id: str
    employer_id: str
    rating_effective_date: str
    status: str  # DRAFT | PROMULGATED | REVISED | CONTESTED | FINAL
    mod_factor: str
    expected_losses_cents: int
    actual_primary_cents: int
    actual_excess_cents: int
    ballast_cents: int
    weight_w: str
    expected_primary_cents: int
    expected_excess_cents: int
    provisional_mod_factor: str
    retroactive_premium_adjustment_cents: Optional[int]
    revision_of_sheet_id: Optional[str]
    revision_reason: Optional[str]  # CLAIM_VALUE_CHANGE | CLASS_CODE_CHANGE | RATE_REVISION | null
    created_at: str
    updated_at: str
    version: int


class ModAppeal(TypedDict, total=False):
    id: str
    mod_sheet_id: str
    employer_id: str
    reason: str
    status: str  # FILED | UNDER_REVIEW | UPHELD | REVERSED | WITHDRAWN
    filed_at: str
    decided_at: Optional[str]
    decision: Optional[str]  # UPHELD | REVERSED | null
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OwnershipChange(TypedDict, total=False):
    id: str
    employer_id: str
    change_type: str  # SALE | MERGER | FORMATION_OF_NEW_ENTITY | OTHER
    effective_date: str
    status: str  # PENDING | COMBINED | NOT_COMBINED | REVERSED
    combinability_group_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CombinabilityGroup(TypedDict, total=False):
    id: str
    member_employer_ids: List[str]
    status: str  # ACTIVE | DISSOLVED
    created_from_change_id: str
    combined_mod_sheet_id: str
    created_at: str
    updated_at: str
    version: int


class AssignedRiskEnrollment(TypedDict, total=False):
    id: str
    employer_id: str
    state_code: str
    effective_date: str
    expiration_date: str
    estimated_annual_premium_cents: int
    status: str  # PENDING | ACTIVE | EXITED | CANCELLED
    assigned_carrier_id: Optional[str]
    take_out_credit_cents: int
    exit_date: Optional[str]
    exit_reason: Optional[str]  # TAKE_OUT | CANCELLED | EXPIRED | null
    created_at: str
    updated_at: str
    version: int


class AssignedRiskTakeOut(TypedDict, total=False):
    id: str
    enrollment_id: str
    voluntary_carrier_id: str
    exit_date: str
    status: str  # PENDING | APPROVED | REJECTED
    credit_cents: int
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnderwritingReview(TypedDict, total=False):
    id: str
    subject_type: str  # MOD_SHEET | CLASS_ASSIGNMENT | TAKE_OUT
    subject_id: str
    status: str  # PENDING | APPROVED | REJECTED
    reviewer_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UserRole(str, Enum):
    BUREAU_ADMIN = "BureauAdmin"
    CARRIER_DATA_REPORTER = "CarrierDataReporter"
    BUREAU_ANALYST = "BureauAnalyst"
    INSPECTOR = "Inspector"
    EMPLOYER_REPRESENTATIVE = "EmployerRepresentative"
    POOL_ADMINISTRATOR = "PoolAdministrator"
    VOLUNTARY_CARRIER_REPRESENTATIVE = "VoluntaryCarrierRepresentative"
    UNDERWRITER = "Underwriter"
