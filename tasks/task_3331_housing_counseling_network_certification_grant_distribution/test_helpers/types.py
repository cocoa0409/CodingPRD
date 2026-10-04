"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    NETWORK_DIRECTOR = "NetworkDirector"
    ASSESSOR = "Assessor"
    TRAINING_REGISTRAR = "TrainingRegistrar"
    GRANT_OFFICER = "GrantOfficer"
    MEMBER_ADMIN = "MemberAdmin"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    AUDITOR = "Auditor"


class CharterStatus(str, Enum):
    APPLICANT = "APPLICANT"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    PROVISIONAL = "PROVISIONAL"
    CHARTERED = "CHARTERED"
    PROBATION = "PROBATION"
    REVOKED = "REVOKED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"
    ADJUDICATED = "ADJUDICATED"
    WITHDRAWN = "WITHDRAWN"


class Rating(str, Enum):
    STRONG = "STRONG"
    ADEQUATE = "ADEQUATE"
    MARGINAL = "MARGINAL"
    DEFICIENT = "DEFICIENT"


class CounselorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SEPARATED = "SEPARATED"


class CourseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    CONCLUDED = "CONCLUDED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"


class CertificationStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    FORMULA_LOCKED = "FORMULA_LOCKED"
    COMPETITIVE_REVIEW = "COMPETITIVE_REVIEW"
    AWARDED = "AWARDED"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWARDED = "AWARDED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class AwardStatus(str, Enum):
    DISBURSING = "DISBURSING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class DisbursementStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class FileStatus(str, Enum):
    OPEN = "OPEN"
    COUNSELING = "COUNSELING"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    CLOSED = "CLOSED"


class OutcomeCode(str, Enum):
    PURCHASED_HOME = "PURCHASED_HOME"
    MORTGAGE_READY = "MORTGAGE_READY"
    RENTAL_STABILIZED = "RENTAL_STABILIZED"
    FORECLOSURE_AVERTED = "FORECLOSURE_AVERTED"
    BUDGET_PLAN_ADOPTED = "BUDGET_PLAN_ADOPTED"
    NO_OUTCOME = "NO_OUTCOME"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REMEDIATED = "REMEDIATED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    FLAGGED = "FLAGGED"
    AUDITED = "AUDITED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class PerformanceReviewStatus(str, Enum):
    OPEN = "OPEN"
    SCORED = "SCORED"
    SATISFACTORY = "SATISFACTORY"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class ProgramArea(str, Enum):
    HOMEOWNERSHIP = "HOMEOWNERSHIP"
    RENTAL = "RENTAL"
    COMMUNITY_DEVELOPMENT = "COMMUNITY_DEVELOPMENT"
    FINANCIAL_CAPABILITY = "FINANCIAL_CAPABILITY"
    FORECLOSURE_PREVENTION = "FORECLOSURE_PREVENTION"


# All resources carry the full common set: id, created_at, updated_at, version.


class NetworkMember(TypedDict):
    id: str
    legal_name: str
    ein: str
    state_code: str
    charter_status: str
    compliance_posture: str
    service_regions: List[str]
    chartered_at: Optional[str]
    revocation_reason: Optional[str]
    open_finding_count: int
    failed_review_flag: bool
    created_at: str
    updated_at: str
    version: int


class OrganizationalAssessment(TypedDict):
    id: str
    member_id: str
    governance_score: Optional[int]
    finance_score: Optional[int]
    program_capacity_score: Optional[int]
    composite_score: Optional[float]
    provisional_rating: Optional[str]
    final_rating: Optional[str]
    assessment_status: str
    assessor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Counselor(TypedDict):
    id: str
    member_id: str
    full_name: str
    email: str
    counselor_status: str
    ce_credits_accumulated: int
    ce_window_end: str
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    course_code: str
    title: str
    program_area: str
    capacity: int
    ce_eligible: bool
    ce_credits: int
    delivery_start: str
    delivery_end: str
    prerequisite_course_id: Optional[str]
    course_status: str
    seats_taken: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    course_id: str
    counselor_id: str
    enrollment_status: str
    score: Optional[int]
    pass_threshold: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    counselor_id: str
    program_area: str
    certification_status: str
    certified_at: Optional[str]
    lapse_deadline: Optional[str]
    continuing_requirement_met: bool
    created_at: str
    updated_at: str
    version: int


class GrantCycle(TypedDict):
    id: str
    fiscal_year: int
    formula_pool_cents: int
    competitive_pool_cents: int
    cycle_status: str
    formula_committed_cents: int
    competitive_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class GrantApplication(TypedDict):
    id: str
    cycle_id: str
    member_id: str
    program_area: str
    requested_formula_cents: int
    requested_competitive_cents: int
    pledged_match_cents: int
    application_status: str
    review_score: Optional[int]
    reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantAward(TypedDict):
    id: str
    application_id: str
    cycle_id: str
    member_id: str
    formula_component_cents: int
    competitive_component_cents: int
    required_match_cents: int
    verified_match_cents: int
    award_status: str
    disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    award_id: str
    tranche_index: int
    amount_cents: int
    disbursement_status: str
    created_at: str
    updated_at: str
    version: int


class ClientFile(TypedDict):
    id: str
    member_id: str
    counselor_id: str
    program_area: str
    household_size: int
    opened_on: str
    file_status: str
    outcome_code: Optional[str]
    counseling_hours: float
    created_at: str
    updated_at: str
    version: int


class FileReview(TypedDict):
    id: str
    client_file_id: str
    reviewer_id: str
    review_status: str
    deficiency_codes: List[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpenditureReport(TypedDict):
    id: str
    award_id: str
    period_start: str
    period_end: str
    reported_spent_cents: int
    report_status: str
    cumulative_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict):
    id: str
    award_id: str
    auditor_id: Optional[str]
    audit_status: str
    disallowance_cents: int
    parent_audit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceReview(TypedDict):
    id: str
    member_id: str
    review_period: str
    households_served: int
    review_score: Optional[int]
    review_status: str
    corrective_plan_due: Optional[str]
    created_at: str
    updated_at: str
    version: int
