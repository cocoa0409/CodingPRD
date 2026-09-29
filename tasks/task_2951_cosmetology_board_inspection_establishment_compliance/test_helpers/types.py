"""Domain types for the Cosmetology Board Compliance API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    BOARD_ADMIN = "BoardAdmin"
    INSPECTOR = "Inspector"
    HEARING_OFFICER = "HearingOfficer"
    ESTABLISHMENT_OWNER = "EstablishmentOwner"
    PRACTITIONER = "Practitioner"
    SCHOOL_REGISTRAR = "SchoolRegistrar"
    HEALTH_AUTHORITY_LIAISON = "HealthAuthorityLiaison"


class EstablishmentLicenseStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    CLOSED_IMMINENT_HAZARD = "CLOSED_IMMINENT_HAZARD"
    REVOKED = "REVOKED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class EstablishmentType(str, Enum):
    SALON = "SALON"
    BARBERSHOP = "BARBERSHOP"
    NAIL_SALON = "NAIL_SALON"
    ESTHETICS_SPA = "ESTHETICS_SPA"
    SCHOOL_CLINIC = "SCHOOL_CLINIC"


class PractitionerLicenseStatus(str, Enum):
    STUDENT = "STUDENT"
    EXAM_ELIGIBLE = "EXAM_ELIGIBLE"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class LicenseType(str, Enum):
    COSMETOLOGIST = "COSMETOLOGIST"
    BARBER = "BARBER"
    NAIL_TECHNICIAN = "NAIL_TECHNICIAN"
    ESTHETICIAN = "ESTHETICIAN"
    INSTRUCTOR = "INSTRUCTOR"
    APPRENTICE = "APPRENTICE"


class LicenseAction(str, Enum):
    GRANT_EXAM_ELIGIBILITY = "GRANT_EXAM_ELIGIBILITY"
    ISSUE_LICENSE = "ISSUE_LICENSE"
    PLACE_ON_PROBATION = "PLACE_ON_PROBATION"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    REVOKE = "REVOKE"


class AccreditationStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    PROBATIONARY = "PROBATIONARY"
    WITHDRAWN = "WITHDRAWN"


class CreditType(str, Enum):
    SCHOOL_CLOCK_HOUR = "SCHOOL_CLOCK_HOUR"
    APPRENTICE_HOUR = "APPRENTICE_HOUR"


class Discipline(str, Enum):
    THEORY = "THEORY"
    PRACTICAL = "PRACTICAL"
    SANITATION = "SANITATION"
    DISINFECTION = "DISINFECTION"
    BUSINESS_LAW = "BUSINESS_LAW"


class StationType(str, Enum):
    STYLING_CHAIR = "STYLING_CHAIR"
    NAIL_TABLE = "NAIL_TABLE"
    FOOT_SPA = "FOOT_SPA"
    FACIAL_ROOM = "FACIAL_ROOM"


class PostingStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    STALE_POSTING = "STALE_POSTING"
    MISSING_POSTING = "MISSING_POSTING"


class RentalType(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    BOOTH_RENTER_INDEPENDENT_CONTRACTOR = "BOOTH_RENTER_INDEPENDENT_CONTRACTOR"


class BoothRentalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    VOIDED = "VOIDED"


class InspectionType(str, Enum):
    ROUTINE = "ROUTINE"
    COMPLAINT_DRIVEN = "COMPLAINT_DRIVEN"
    REINSPECTION = "REINSPECTION"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_REVIEW = "PENDING_REVIEW"
    FINALIZED = "FINALIZED"


class HazardState(str, Enum):
    NONE = "NONE"
    HAZARD_DECLARED = "HAZARD_DECLARED"
    HAZARD_CLEARED = "HAZARD_CLEARED"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"
    IMMEDIATE_CLOSURE = "IMMEDIATE_CLOSURE"


class ViolationCategory(str, Enum):
    SANITATION = "SANITATION"
    DISINFECTION = "DISINFECTION"
    IMPLEMENT_HANDLING = "IMPLEMENT_HANDLING"
    FOOT_SPA = "FOOT_SPA"
    LICENSING_POSTING = "LICENSING_POSTING"
    FACILITY = "FACILITY"
    EQUIPMENT = "EQUIPMENT"
    RECORDKEEPING = "RECORDKEEPING"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"
    IMMINENT_HAZARD = "IMMINENT_HAZARD"


class CitationSubjectType(str, Enum):
    ESTABLISHMENT = "ESTABLISHMENT"
    PRACTITIONER = "PRACTITIONER"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    AFFIRMED = "AFFIRMED"
    AMENDED = "AMENDED"
    DELINQUENT = "DELINQUENT"
    DISMISSED = "DISMISSED"
    SETTLED = "SETTLED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DECIDED = "DECIDED"


class HearingDecision(str, Enum):
    AFFIRMED = "AFFIRMED"
    AMENDED = "AMENDED"
    DISMISSED = "DISMISSED"


class SanitationLogType(str, Enum):
    IMPLEMENT_DISINFECTION = "IMPLEMENT_DISINFECTION"
    FOOT_SPA_AFTER_CLIENT = "FOOT_SPA_AFTER_CLIENT"
    FOOT_SPA_END_OF_DAY = "FOOT_SPA_END_OF_DAY"
    FOOT_SPA_WEEKLY_BIOFILM = "FOOT_SPA_WEEKLY_BIOFILM"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    ESCALATED_OVERDUE = "ESCALATED_OVERDUE"
    NOTIFIED = "NOTIFIED"
    RESOLVED_SUBSTANTIATED = "RESOLVED_SUBSTANTIATED"
    RESOLVED_UNSUBSTANTIATED = "RESOLVED_UNSUBSTANTIATED"


class IncidentResolution(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class LedgerType(str, Enum):
    FINE_CENTS = "FINE_CENTS"
    DEMERIT_POINTS = "DEMERIT_POINTS"
    SANCTION_POINTS = "SANCTION_POINTS"


class EntryReason(str, Enum):
    CITATION_ASSESSMENT = "CITATION_ASSESSMENT"
    CITATION_PAYMENT = "CITATION_PAYMENT"
    CITATION_LATE_PENALTY = "CITATION_LATE_PENALTY"
    CITATION_AMENDMENT_ADJUSTMENT = "CITATION_AMENDMENT_ADJUSTMENT"
    CITATION_DISMISSAL_REVERSAL = "CITATION_DISMISSAL_REVERSAL"
    INSPECTION_DEMERIT_ASSESSMENT = "INSPECTION_DEMERIT_ASSESSMENT"
    INSPECTION_DEMERIT_REVERSAL = "INSPECTION_DEMERIT_REVERSAL"
    INFECTION_SANCTION_ASSESSMENT = "INFECTION_SANCTION_ASSESSMENT"
    REINSTATEMENT_SANCTION_REVERSAL = "REINSTATEMENT_SANCTION_REVERSAL"


# --- Entity shapes -------------------------------------------------------
# Establishment, Practitioner, School, Workstation, BoothRental, Inspection,
# ViolationFinding, Citation and Hearing carry id, created_at, updated_at and
# version.  TrainingRecord, ViolationCode, SanitationLog and LedgerEntry are
# immutable by design and carry only id and created_at.


class Establishment(TypedDict):
    id: str
    legal_name: str
    establishment_type: str
    county_code: str
    station_capacity: int
    station_count: int
    license_status: str
    compliance_posture: str
    demerit_balance: float
    open_critical_citation_count: int
    outstanding_fine_total_cents: int
    delinquent_fine_total_cents: int
    foot_spa_biofilm_current: bool
    last_finalized_inspection_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Practitioner(TypedDict):
    id: str
    full_name: str
    license_type: str
    school_id: Optional[str]
    license_status: str
    license_expires_on: Optional[str]
    credited_hours_school: float
    credited_hours_apprentice: float
    credited_hours_total: float
    required_clock_hours_effective: float
    exam_eligible: bool
    sanction_points: float
    suspension_cause_points: Optional[float]
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    name: str
    county_code: str
    required_clock_hours: float
    accreditation_status: str
    apprenticeship_program_approved: bool
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict):
    id: str
    practitioner_id: str
    credit_type: str
    hours: float
    performed_on: str
    discipline: str
    school_id: Optional[str]
    sponsor_practitioner_id: Optional[str]
    created_at: str


class Workstation(TypedDict):
    id: str
    establishment_id: str
    station_number: int
    station_type: str
    posted_practitioner_id: Optional[str]
    posting_status: str
    last_biofilm_cycle_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoothRental(TypedDict):
    id: str
    workstation_id: str
    practitioner_id: str
    rental_type: str
    term_start_at: str
    term_end_at: Optional[str]
    monthly_rent_cents: int
    status: str
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    establishment_id: str
    inspection_type: str
    reinspection_of_id: Optional[str]
    inspector_user_id: str
    complaint_reference: Optional[str]
    window_start_at: str
    window_end_at: str
    status: str
    hazard_state: str
    started_at: Optional[str]
    submitted_at: Optional[str]
    finalized_at: Optional[str]
    finding_count: int
    provisional_adjusted_score: Optional[float]
    final_adjusted_score: Optional[float]
    provisional_outcome: Optional[str]
    final_outcome: Optional[str]
    demerit_balance_before_finalize: Optional[float]
    citation_count: int
    created_at: str
    updated_at: str
    version: int


class ViolationCode(TypedDict):
    id: str
    code: str
    category: str
    severity: str
    base_points: float
    fine_cents_base: int
    created_at: str


class ViolationFinding(TypedDict):
    id: str
    inspection_id: str
    violation_code_id: str
    attributed_practitioner_id: Optional[str]
    workstation_id: Optional[str]
    observed_count: int
    corrected_on_site: bool
    severity: str
    repeat_factor_provisional: Optional[float]
    repeat_factor_final: Optional[float]
    provisional_points: Optional[float]
    final_points: Optional[float]
    declared_hazard: bool
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    inspection_id: str
    subject_type: str
    subject_practitioner_id: Optional[str]
    citation_number: str
    max_finding_severity: Optional[str]
    demerit_tier_multiplier: float
    assessed_fine_cents: int
    administrative_fee_cents: int
    total_due_cents: int
    outstanding_fine_cents: int
    status: str
    issued_at: str
    due_at: str
    contest_deadline_at: str
    hearing_round_count: int
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    citation_id: str
    presiding_officer_user_id: str
    scheduled_at: str
    status: str
    decision: Optional[str]
    amended_fine_cents: Optional[int]
    rationale: Optional[str]
    round_index: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SanitationLog(TypedDict):
    id: str
    workstation_id: str
    log_type: str
    performed_at: str
    contact_minutes: float
    disinfectant_epa_reg_number: str
    implement_batch_count: Optional[int]
    occupancy_end_at: str
    created_at: str


class InfectionIncident(TypedDict):
    id: str
    establishment_id: str
    suspected_practitioner_id: Optional[str]
    case_count: int
    onset_date: str
    narrative: str
    status: str
    reported_at: str
    notification_deadline_at: str
    notified_at: Optional[str]
    health_authority_reference: Optional[str]
    findings_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    id: str
    ledger_type: str
    entry_reason: str
    delta_cents: Optional[int]
    delta_points: Optional[float]
    citation_id: Optional[str]
    establishment_id: Optional[str]
    practitioner_id: Optional[str]
    inspection_id: Optional[str]
    occurred_at: str
    created_at: str
