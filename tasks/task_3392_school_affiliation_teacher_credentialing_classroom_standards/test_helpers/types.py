"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4).

Common-field rule (PRD section 2.4): most resources carry ``id``,
``created_at``, ``updated_at`` and ``version``; ``ClassroomAudit`` and
``CECreditEntry`` are deliberately leaner and carry only ``id`` and
``created_at`` — their TypedDicts omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    SOCIETY_ADMIN = "SocietyAdmin"
    SCHOOL_ADMIN = "SchoolAdmin"
    PROGRAM_DIRECTOR = "ProgramDirector"
    ADULT_LEARNER = "AdultLearner"
    CONSULTANT = "Consultant"
    ACCREDITATION_REVIEWER = "AccreditationReviewer"
    REGISTRAR = "Registrar"


class AgeLevel(str, Enum):
    INFANT_TODDLER = "INFANT_TODDLER"
    EARLY_CHILDHOOD = "EARLY_CHILDHOOD"
    ELEMENTARY_I = "ELEMENTARY_I"
    ELEMENTARY_II = "ELEMENTARY_II"
    SECONDARY = "SECONDARY"


class CatalogStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MembershipLevel(str, Enum):
    APPLICANT = "APPLICANT"
    AFFILIATE = "AFFILIATE"
    MEMBER = "MEMBER"
    ACCREDITED = "ACCREDITED"


class Standing(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ComplianceOverride(str, Enum):
    NONE = "NONE"
    NONCOMPLIANT_LEAD = "NONCOMPLIANT_LEAD"


class AuditVerdict(str, Enum):
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"


class FailedCheck(str, Enum):
    RATIO = "RATIO"
    WORK_PERIOD = "WORK_PERIOD"
    MATERIALS = "MATERIALS"
    MULTI_AGE = "MULTI_AGE"


class ProgramStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACCREDITED = "ACCREDITED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class LearnerStatus(str, Enum):
    ENROLLED = "ENROLLED"
    IN_PRACTICUM = "IN_PRACTICUM"
    PRACTICUM_COMPLETE = "PRACTICUM_COMPLETE"
    CREDENTIALED = "CREDENTIALED"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOURS_COMPLETE = "HOURS_COMPLETE"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ApplicationType(str, Enum):
    AFFILIATION = "AFFILIATION"
    MEMBERSHIP = "MEMBERSHIP"
    ACCREDITATION = "ACCREDITATION"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    SUSPENDED = "SUSPENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ApplicationOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RETURNED = "RETURNED"


class SelfStudyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    ACCEPTED = "ACCEPTED"


class SelfStudyOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REPORT_FILED = "REPORT_FILED"
    CANCELLED = "CANCELLED"


class VisitVerdict(str, Enum):
    COMPLIANT = "COMPLIANT"
    IMPROVEMENT_REQUIRED = "IMPROVEMENT_REQUIRED"
    NONCOMPLIANT = "NONCOMPLIANT"


class PlanStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


class PlanOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class PDEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class CEEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true)
# ---------------------------------------------------------------------------
class StandardsCatalog(TypedDict):
    id: str
    version_label: str
    status: str
    effective_from: str
    min_uninterrupted_work_minutes_by_level: Dict[str, int]
    max_students_per_adult_by_level: Dict[str, int]
    materials_pass_threshold: float
    min_multi_age_span_years_by_level: Dict[str, int]
    practicum_min_hours_by_level: Dict[str, int]
    ce_hours_required: float
    credential_validity_months: int
    renewal_window_months: int
    renewal_grace_months: int
    min_membership_months_before_accreditation: int
    consultant_travel_buffer_days: int
    plan_response_days: int
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    name: str
    display_name: str
    uses_method_name: bool
    descriptor: Optional[str]
    contact_email: str
    membership_level: str
    standing: str
    affiliated_since: Optional[str]
    member_since: Optional[str]
    accredited_since: Optional[str]
    dues_paid_through: Optional[str]
    pinned_catalog_id: Optional[str]
    dues_current: bool
    brand_compliant: bool
    directory_visible: bool
    total_enrollment: int
    compliant_classroom_count: int
    annual_dues_cents: int
    created_at: str
    updated_at: str
    version: int


class Classroom(TypedDict):
    id: str
    school_id: str
    name: str
    age_level: str
    declared_age_span_years: int
    enrolled_student_count: int
    assistant_count: int
    lead_credential_id: Optional[str]
    compliance_override: str
    latest_audit_verdict: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeacherEducationProgram(TypedDict):
    id: str
    name: str
    age_levels_offered: List[str]
    course_contact_hours_by_level: Dict[str, int]
    practicum_hours_by_level: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdultLearner(TypedDict):
    id: str
    program_id: str
    full_name: str
    age_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PracticumPlacement(TypedDict):
    id: str
    learner_id: str
    host_school_id: str
    supervisor_credential_id: Optional[str]
    age_level: str
    start_date: str
    end_date: str
    target_hours: int
    hours_logged: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict):
    id: str
    learner_id: str
    age_level: str
    status: str
    issued_at: str
    cycle_start: str
    expires_at: str
    renewed_count: int
    ce_hours_cycle_credited: float
    ce_hours_rolling_credited: float
    created_at: str
    updated_at: str
    version: int


class SchoolApplication(TypedDict):
    id: str
    school_id: str
    type: str
    status: str
    supporting_self_study_id: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelfStudy(TypedDict):
    id: str
    school_id: str
    narrative: str
    status: str
    pinned_catalog_id: str
    pinned_catalog_label: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationVisit(TypedDict):
    id: str
    school_id: str
    self_study_id: str
    consultant_id: str
    window_start: str
    window_end: str
    status: str
    verdict: Optional[str]
    findings: List[str]
    report_filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImprovementPlan(TypedDict):
    id: str
    school_id: str
    visit_id: Optional[str]
    required_actions: List[str]
    due_date: str
    status: str
    response_notes: Optional[str]
    submitted_at: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PDEvent(TypedDict):
    id: str
    title: str
    provider_name: str
    start_at: str
    end_at: str
    ce_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: false — id + created_at ONLY)
# ---------------------------------------------------------------------------
class MaterialsGroup(TypedDict):
    domain: str
    required_count: int
    present_count: int


class ClassroomAudit(TypedDict):
    # PRD section 2.4: an audit carries only id and created_at; both
    # updated_at and version are absent (immutable once filed).
    id: str
    classroom_id: str
    visit_id: Optional[str]
    catalog_id: str
    auditor_consultant_id: str
    observed_at: str
    students_present: int
    adults_present: int
    observed_uninterrupted_minutes: int
    materials_groups: List[Dict[str, Any]]
    ratio_students_per_adult: float
    ratio_pass: bool
    work_period_pass: bool
    materials_score: float
    materials_pass: bool
    multi_age_pass: bool
    verdict: str
    failed_checks: List[str]
    created_at: str


class CECreditEntry(TypedDict):
    # PRD section 2.4: a credit entry carries only id and created_at; both
    # updated_at and version are absent (void is the only transition).
    id: str
    credential_id: str
    pd_event_id: str
    hours: float
    earned_at: str
    status: str
    created_at: str
