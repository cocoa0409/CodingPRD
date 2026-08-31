"""Domain types for the HMDA Register API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    INSTITUTION_ADMIN = "InstitutionAdmin"
    LOAN_OFFICER = "LoanOfficer"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    EXAMINER = "Examiner"


# ─── Enumerations ─────────────────────────────────────────────────────────────

class FilingPosture(str, Enum):
    OPEN = "OPEN"
    LOCKED_FOR_FILING = "LOCKED_FOR_FILING"
    FILED_YEAR = "FILED_YEAR"
    CLOSED_YEAR = "CLOSED_YEAR"


class ApplicationStage(str, Enum):
    INTAKE = "INTAKE"
    UNDERWRITING = "UNDERWRITING"
    DECISIONED = "DECISIONED"
    REGISTER_LOCKED = "REGISTER_LOCKED"
    ARCHIVED = "ARCHIVED"


class LarStatus(str, Enum):
    PENDING_FIELDS = "PENDING_FIELDS"
    COMPLETE = "COMPLETE"
    EXCEPTION_FLAGGED = "EXCEPTION_FLAGGED"
    CLEARED = "CLEARED"
    EXCLUDED = "EXCLUDED"


class ExclusionReason(str, Enum):
    NOT_EXCLUDED = "NOT_EXCLUDED"
    BUSINESS_PURPOSE = "BUSINESS_PURPOSE"


class ApplicationChannel(str, Enum):
    FACE_TO_FACE = "FACE_TO_FACE"
    MAIL = "MAIL"
    INTERNET = "INTERNET"
    TELEPHONE = "TELEPHONE"


class LoanType(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    FHA = "FHA"
    VA = "VA"
    RHS_FSA = "RHS_FSA"


class LoanPurpose(str, Enum):
    HOME_PURCHASE = "HOME_PURCHASE"
    HOME_IMPROVEMENT = "HOME_IMPROVEMENT"
    REFINANCING = "REFINANCING"
    CASH_OUT_REFINANCING = "CASH_OUT_REFINANCING"
    OTHER_PURPOSE = "OTHER_PURPOSE"


class OccupancyType(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    SECOND = "SECOND"
    INVESTMENT = "INVESTMENT"


class LienStatus(str, Enum):
    FIRST_LIEN = "FIRST_LIEN"
    SUBORDINATE_LIEN = "SUBORDINATE_LIEN"


class ActionTaken(str, Enum):
    ORIGINATED = "ORIGINATED"
    APPROVED_NOT_ACCEPTED = "APPROVED_NOT_ACCEPTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    FILE_CLOSED_INCOMPLETE = "FILE_CLOSED_INCOMPLETE"
    PURCHASED_LOAN = "PURCHASED_LOAN"
    PREAPPROVAL_DENIED = "PREAPPROVAL_DENIED"
    PREAPPROVAL_APPROVED_NOT_ACCEPTED = "PREAPPROVAL_APPROVED_NOT_ACCEPTED"


class PurchaserType(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    FANNIE_MAE = "FANNIE_MAE"
    FREDDIE_MAC = "FREDDIE_MAC"
    GINNIE_MAE = "GINNIE_MAE"
    PRIVATE_SECURITIZER = "PRIVATE_SECURITIZER"
    OTHER = "OTHER"


class DenialReason(str, Enum):
    DEBT_TO_INCOME = "DEBT_TO_INCOME"
    EMPLOYMENT_HISTORY = "EMPLOYMENT_HISTORY"
    CREDIT_HISTORY = "CREDIT_HISTORY"
    COLLATERAL = "COLLATERAL"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    UNVERIFIABLE_INFO = "UNVERIFIABLE_INFO"
    INCOMPLETE_APPLICATION = "INCOMPLETE_APPLICATION"
    MORTGAGE_INSURANCE_DENIED = "MORTGAGE_INSURANCE_DENIED"
    OTHER = "OTHER"


class ApplicantRole(str, Enum):
    APPLICANT = "APPLICANT"
    CO_APPLICANT = "CO_APPLICANT"


class CollectionMethod(str, Enum):
    PROVIDED_BY_APPLICANT = "PROVIDED_BY_APPLICANT"
    VISUAL_OBSERVATION_OR_SURNAME = "VISUAL_OBSERVATION_OR_SURNAME"
    NOT_PROVIDED_BY_APPLICANT = "NOT_PROVIDED_BY_APPLICANT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ObservationBasis(str, Enum):
    NOT_OBSERVED = "NOT_OBSERVED"
    SURNAME = "SURNAME"
    VISUAL = "VISUAL"


class SexCode(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    BOTH = "BOTH"
    INFO_NOT_PROVIDED = "INFO_NOT_PROVIDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DemographicEntryStatus(str, Enum):
    RECORDED = "RECORDED"
    AMENDED = "AMENDED"


class GeocodeStatus(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_MATCHED = "NOT_MATCHED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class EditRunScope(str, Enum):
    FULL = "FULL"
    INCREMENTAL = "INCREMENTAL"


class EditRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CLEARED_ALL = "CLEARED_ALL"
    INVALIDATED = "INVALIDATED"


class EditSeverity(str, Enum):
    SYNTACTICAL = "SYNTACTICAL"
    VALIDITY = "VALIDITY"
    QUALITY = "QUALITY"
    MACRO = "MACRO"


class EditExceptionStatus(str, Enum):
    OPEN = "OPEN"
    VERIFIED = "VERIFIED"
    STALE = "STALE"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    EDITS_ATTACHED = "EDITS_ATTACHED"
    CERTIFIED = "CERTIFIED"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class StatementType(str, Enum):
    MODIFIED_LAR = "MODIFIED_LAR"
    DISCLOSURE_REPORT = "DISCLOSURE_REPORT"


class SampleMethod(str, Enum):
    SYSTEMATIC_INTERVAL = "SYSTEMATIC_INTERVAL"
    STRATIFIED_BY_ACTION = "STRATIFIED_BY_ACTION"


class SampleStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CLOSED_CLEAN = "CLOSED_CLEAN"
    CLOSED_WITH_FINDINGS = "CLOSED_WITH_FINDINGS"


class DefectRateBasis(str, Enum):
    FIELD_WEIGHTED = "FIELD_WEIGHTED"
    RECORD_WEIGHTED = "RECORD_WEIGHTED"


class FindingSeverity(str, Enum):
    MATERIAL = "MATERIAL"
    NON_MATERIAL = "NON_MATERIAL"


class FindingResolution(str, Enum):
    OPEN = "OPEN"
    ACCEPTED_AS_IS = "ACCEPTED_AS_IS"


class FairLendingBasis(str, Enum):
    RACE = "RACE"
    ETHNICITY = "ETHNICITY"
    SEX = "SEX"


class SignificanceFlag(str, Enum):
    NOT_SIGNIFICANT = "NOT_SIGNIFICANT"
    ELEVATED = "ELEVATED"
    SEVERE = "SEVERE"


class FairLendingStatus(str, Enum):
    COMPUTED = "COMPUTED"
    ESCALATED = "ESCALATED"
    CLEARED = "CLEARED"


# ─── Entity shapes ────────────────────────────────────────────────────────────
# Institution, Application, DemographicEntry, GeocodeAssignment, EditRun,
# EditException, FilingSubmission, AuditSample, AuditFinding and
# FairLendingAnalysis all carry id, created_at, updated_at and version.
# CensusTract and DisclosureStatement carry only id and created_at.


class Institution(TypedDict):
    id: str
    lei: str
    name: str
    activity_year: int
    asset_size_usd_cents: int
    prior_year_closed_end_originations: int
    prior_year_open_end_originations: int
    partial_exemption_eligible: bool
    quarterly_filer: bool
    required_field_count: int
    total_application_count: int
    pending_record_count: int
    reportable_record_count: int
    excluded_record_count: int
    cleared_record_count: int
    open_register_count: int
    filing_posture: str
    filing_deadline_at: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    institution_id: str
    uli: str
    application_date: str
    application_channel: str
    loan_type: str
    loan_purpose: str
    occupancy_type: str
    lien_status: str
    loan_amount_cents: int
    income_thousands: Optional[int]
    rate_spread: Optional[float]
    purchaser_type: Optional[str]
    denial_reason_codes: List[str]
    business_or_commercial_purpose: bool
    open_end_line_of_credit: bool
    action_taken: Optional[str]
    action_taken_date: Optional[str]
    supersedes_application_id: Optional[str]
    is_superseded: bool
    stage: str
    lar_status: str
    captured_field_count: int
    applicable_field_count: int
    exclusion_reason: str
    created_at: str
    updated_at: str
    version: int


class DemographicEntry(TypedDict):
    id: str
    application_id: str
    applicant_role: str
    is_natural_person: bool
    collection_method: str
    ethnicity_codes: List[str]
    race_codes: List[str]
    sex_code: str
    age_years: Optional[int]
    observation_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GeocodeAssignment(TypedDict):
    id: str
    application_id: str
    census_tract_id: Optional[str]
    street_address: str
    city: str
    state_code: str
    zip_code: str
    county_fips: str
    submitted_tract_code: Optional[str]
    candidate_count: int
    msa_md_code: Optional[str]
    override_reason: Optional[str]
    is_current: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CensusTract(TypedDict):
    """Immutable reference data: only id and created_at, no updated_at, no version."""
    id: str
    tract_code: str
    county_fips: str
    state_code: str
    msa_md_code: str
    minority_population_pct: float
    tract_to_msa_income_pct: float
    owner_occupied_units: int
    median_family_income_cents: int
    created_at: str


class EditRun(TypedDict):
    id: str
    institution_id: str
    run_index: int
    scope: str
    window_start: str
    window_end: str
    snapshot_record_count: int
    syntactical_count: int
    validity_count: int
    quality_count: int
    macro_count: int
    total_exception_count: int
    open_exception_count: int
    verified_exception_count: int
    stale_exception_count: int
    cleared_record_count: int
    required_verified_quota: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EditException(TypedDict):
    id: str
    edit_run_id: str
    application_id: Optional[str]
    edit_code: str
    severity: str
    field_name: str
    message: str
    verification_note: Optional[str]
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FilingSubmission(TypedDict):
    id: str
    institution_id: str
    edit_run_id: Optional[str]
    activity_year: int
    submission_index: int
    provisional_record_count: int
    final_record_count: Optional[int]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    attestation_text: Optional[str]
    filed_at: Optional[str]
    deadline_at: str
    is_late: Optional[bool]
    late_by_days: Optional[int]
    rejection_reason: Optional[str]
    resubmission_count: int
    is_superseded: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DisclosureStatement(TypedDict):
    """Append-only publication artifact: only id and created_at."""
    id: str
    submission_id: str
    statement_type: str
    record_count: int
    tract_suppression_count: int
    suppressed_record_count: int
    redacted_field_count: int
    published_at: str
    created_at: str


class AuditSample(TypedDict):
    id: str
    institution_id: str
    sample_index: int
    method: str
    period_start: str
    period_end: str
    fields_reviewed_per_record: int
    population_size: int
    sample_size: int
    selected_application_ids: List[str]
    defect_count: int
    records_with_defect_count: int
    defect_rate_basis: Optional[str]
    defect_rate_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    id: str
    audit_sample_id: str
    application_id: str
    field_name: str
    recorded_value: str
    source_document_value: str
    is_defect: bool
    severity: str
    remediation_start: str
    remediation_end: str
    resolution: str
    created_at: str
    updated_at: str
    version: int


class FairLendingAnalysis(TypedDict):
    id: str
    institution_id: str
    analysis_index: int
    basis: str
    control_group_code: str
    protected_group_code: str
    period_start: str
    period_end: str
    control_total: int
    control_denied: int
    protected_total: int
    protected_denied: int
    control_denial_rate_pct: float
    protected_denial_rate_pct: float
    disparity_index: float
    significance_flag: str
    status: str
    created_at: str
    updated_at: str
    version: int
