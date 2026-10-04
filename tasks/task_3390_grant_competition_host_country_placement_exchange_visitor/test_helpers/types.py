"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD entity descriptions. Entities with the standard
system-managed field set carry id + created_at + updated_at + version.
ReviewScore is the documented exception (PRD §2.5): it carries only id and
created_at; updated_at and version are absent.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROGRAM_OFFICER = "ProgramOfficer"
    HOST_COMMISSION = "HostCommission"
    NATIONAL_REVIEWER = "NationalReviewer"
    CAMPUS_REVIEWER = "CampusReviewer"
    APPLICANT = "Applicant"
    ANONYMOUS = "Anonymous"


class CycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SCREENING = "SCREENING"
    AWARDS_FINALIZED = "AWARDS_FINALIZED"
    COMPLETED = "COMPLETED"


class ApplicantType(str, Enum):
    ENROLLED_STUDENT = "ENROLLED_STUDENT"
    INDEPENDENT = "INDEPENDENT"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    CAMPUS_REVIEW = "CAMPUS_REVIEW"
    NATIONAL_SCREENING = "NATIONAL_SCREENING"
    HOST_REVIEW = "HOST_REVIEW"
    SELECTED = "SELECTED"
    ALTERNATE = "ALTERNATE"
    PLACEMENT = "PLACEMENT"
    GRANT_PENDING = "GRANT_PENDING"
    AWARDED = "AWARDED"
    NOT_SELECTED = "NOT_SELECTED"
    WITHDRAWN = "WITHDRAWN"
    DECLINED = "DECLINED"
    PLACEMENT_FAILED = "PLACEMENT_FAILED"


class ScoreStage(str, Enum):
    CAMPUS = "CAMPUS"
    NATIONAL = "NATIONAL"


class LanguageRequirement(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    PROFICIENT = "PROFICIENT"


class InstitutionBand(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class PlacementRoundStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class GrantStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    TERMINATED_EARLY = "TERMINATED_EARLY"


class VisaSponsorshipStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ENDED_EARLY = "ENDED_EARLY"


class ResidencyLedgerStatus(str, Enum):
    PENDING = "PENDING"
    ACCRUING = "ACCRUING"
    WAIVER_PENDING = "WAIVER_PENDING"
    FULFILLED = "FULFILLED"
    WAIVED = "WAIVED"
    NOT_REQUIRED = "NOT_REQUIRED"


class ReportType(str, Enum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    NEEDS_REVISION = "NEEDS_REVISION"


class IncidentCategory(str, Enum):
    MEDICAL = "MEDICAL"
    SECURITY = "SECURITY"
    NATURAL_DISASTER = "NATURAL_DISASTER"
    CIVIL_UNREST = "CIVIL_UNREST"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class IncidentOutcome(str, Enum):
    RESUME = "RESUME"
    TERMINATE = "TERMINATE"


class FollowOnEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class CompetitionCycle(TypedDict, total=False):
    id: str
    academic_year: str
    application_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CountryProgram(TypedDict, total=False):
    id: str
    cycle_id: str
    country_code: str
    slot_quota: int
    min_duration_months: int
    max_duration_months: int
    monthly_stipend_standard_cents: int
    monthly_stipend_high_cents: int
    dependent_allowance_monthly_cents: int
    travel_allowance_cents: int
    health_benefit_monthly_cents: int
    language_requirement: str
    slots_remaining: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    applicant_type: str
    home_institution_name: str
    citizenship_country_code: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    cycle_id: str
    country_program_id: str
    project_title: str
    project_summary: str
    proposed_duration_months: int
    dependents_count: int
    is_follow_on: bool
    status: str
    submitted_at: str
    recommend_seq: int
    national_weighted_score: float
    placement_rounds_used: int
    created_at: str
    updated_at: str
    version: int


class ReviewScore(TypedDict, total=False):
    # Immutable append-only record: ONLY id + created_at are system-managed.
    # updated_at and version are intentionally absent (PRD §2.5).
    id: str
    application_id: str
    stage: str
    reviewer_id: str
    feasibility_score: float
    country_fit_score: float
    language_score: float
    comment: str
    created_at: str


class PlacementRound(TypedDict, total=False):
    id: str
    application_id: str
    round_number: int
    institution_name: str
    institution_band: str
    response_deadline: str
    status: str
    responded_at: str
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict, total=False):
    id: str
    application_id: str
    status: str
    awarded_band: str
    provisional_monthly_stipend_cents: int
    provisional_total_cents: int
    final_monthly_stipend_cents: int
    final_total_cents: int
    duration_months: int
    start_date: str
    end_date: str
    orientation_completed_at: str
    interim_report_due_date: str
    final_report_due_date: str
    suspension_days_total: int
    compliance_strikes: int
    earned_cents: int
    repayment_cents: int
    reconciliation_adjustment_cents: int
    termination_reason: str
    created_at: str
    updated_at: str
    version: int


class VisaSponsorship(TypedDict, total=False):
    id: str
    grant_id: str
    sponsor_program_number: str
    subject_to_home_residency: bool
    orientation_completed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ResidencyStay(TypedDict, total=False):
    start_date: str
    end_date: str
    day_count: int


class ResidencyLedger(TypedDict, total=False):
    id: str
    visa_sponsorship_id: str
    status: str
    required_days: int
    accrued_days: int
    accrual_start_date: str
    stays: List[ResidencyStay]
    waiver_reason: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    grant_id: str
    report_type: str
    content: str
    status: str
    submitted_at: str
    late: bool
    revision_note: str
    created_at: str
    updated_at: str
    version: int


class EmergencyIncident(TypedDict, total=False):
    id: str
    grant_id: str
    category: str
    description: str
    status: str
    opened_at: str
    resolved_at: str
    outcome: str
    suspension_days: int
    created_at: str
    updated_at: str
    version: int


class AlumniProfile(TypedDict, total=False):
    id: str
    applicant_id: str
    grant_id: str
    terminated_early: bool
    compliance_strikes: int
    engagement_index_provisional: int
    engagement_index_certified: int
    residency_status: str
    follow_on_eligible: str
    created_at: str
    updated_at: str
    version: int
