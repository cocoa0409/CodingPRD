"""Domain types for the Postdoc Appointment & Visa Administration API.

Entity TypedDicts, status enums and the role enum, all derived from the PRD.
Every persisted record in this system carries ``id``, ``created_at``,
``updated_at`` and ``version`` (PRD section 2.4).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    """The six declared roles; the spelling is exact (PRD section 2.1)."""

    POSTDOC_AFFAIRS_OFFICER = "PostdocAffairsOfficer"
    HR_COMPENSATION_APPROVER = "HRCompensationApprover"
    EXPORT_CONTROL_REVIEWER = "ExportControlReviewer"
    INTERNATIONAL_SCHOLAR_ADVISOR = "InternationalScholarAdvisor"
    FACULTY_MENTOR = "FacultyMentor"
    POSTDOC = "Postdoc"


ALL_ROLES: List[str] = [
    UserRole.POSTDOC_AFFAIRS_OFFICER.value,
    UserRole.HR_COMPENSATION_APPROVER.value,
    UserRole.EXPORT_CONTROL_REVIEWER.value,
    UserRole.INTERNATIONAL_SCHOLAR_ADVISOR.value,
    UserRole.FACULTY_MENTOR.value,
    UserRole.POSTDOC.value,
]


# ─── Status enums ─────────────────────────────────────────────────────────

class PostdocStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    ACTIVE = "ACTIVE"
    SEPARATED = "SEPARATED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"


class LaboratoryStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BiosafetyLevel(str, Enum):
    BSL1 = "BSL1"
    BSL2 = "BSL2"
    BSL3 = "BSL3"


class AppointmentStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFER_ISSUED = "OFFER_ISSUED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    NON_RENEWED = "NON_RENEWED"
    TERMINATED = "TERMINATED"


class ComplianceStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class TitleClassification(str, Enum):
    POSTDOC_FELLOW = "POSTDOC_FELLOW"
    POSTDOC_SCHOLAR_EMPLOYEE = "POSTDOC_SCHOLAR_EMPLOYEE"
    POSTDOC_ASSOCIATE = "POSTDOC_ASSOCIATE"


class EmploymentClass(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    FELLOWSHIP = "FELLOWSHIP"


class FundingType(str, Enum):
    FEDERAL_GRANT = "FEDERAL_GRANT"
    FOUNDATION_GRANT = "FOUNDATION_GRANT"
    EXTERNAL_FELLOWSHIP = "EXTERNAL_FELLOWSHIP"
    INSTITUTIONAL_FELLOWSHIP = "INSTITUTIONAL_FELLOWSHIP"


class SalaryFloorPolicy(str, Enum):
    NIH_SCALE = "NIH_SCALE"
    INSTITUTIONAL_MIN = "INSTITUTIONAL_MIN"


class BenefitsPackage(str, Enum):
    EMPLOYEE_FULL = "EMPLOYEE_FULL"
    EMPLOYEE_LIMITED = "EMPLOYEE_LIMITED"
    FELLOWSHIP_STIPEND_ONLY = "FELLOWSHIP_STIPEND_ONLY"
    FELLOWSHIP_INSTITUTIONAL = "FELLOWSHIP_INSTITUTIONAL"
    NONE = "NONE"


class WithdrawReason(str, Enum):
    VISA_DENIED = "VISA_DENIED"
    VISA_DELAY_TERM_TOO_SHORT = "VISA_DELAY_TERM_TOO_SHORT"
    CANDIDATE_DECLINED = "CANDIDATE_DECLINED"
    FUNDING_LOST = "FUNDING_LOST"


class VisaCategory(str, Enum):
    TN = "TN"
    J1_RESEARCH_SCHOLAR = "J1_RESEARCH_SCHOLAR"
    H1B = "H1B"
    O1 = "O1"


class ProcessingTrack(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class VisaCaseStatus(str, Enum):
    DOCS_PENDING = "DOCS_PENDING"
    SUBMITTED = "SUBMITTED"
    RFE_RECEIVED = "RFE_RECEIVED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class ProjectionVariant(str, Enum):
    INITIAL_FILING = "INITIAL_FILING"
    POST_RFE_REFILING = "POST_RFE_REFILING"


class AdjudicationOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RFE = "RFE"


class DocumentType(str, Enum):
    MENTORING_PLAN = "MENTORING_PLAN"
    IDP = "IDP"


class DocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class ExportReviewStatus(str, Enum):
    QUEUED = "QUEUED"
    CLEARED = "CLEARED"
    CLEARED_WITH_CONDITIONS = "CLEARED_WITH_CONDITIONS"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class ScreeningTier(str, Enum):
    TIER_1_STANDARD = "TIER_1_STANDARD"
    TIER_2_ENHANCED = "TIER_2_ENHANCED"


class LabGrantStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    COMPLIANCE_REGRESSION = "COMPLIANCE_REGRESSION"
    EXIT_PROCESSING = "EXIT_PROCESSING"


class ReappointmentReviewStatus(str, Enum):
    OPENED = "OPENED"
    RECOMMENDED_RENEW = "RECOMMENDED_RENEW"
    RECOMMENDED_NON_RENEW = "RECOMMENDED_NON_RENEW"
    FINALIZED_RENEWED = "FINALIZED_RENEWED"
    FINALIZED_NON_RENEWED = "FINALIZED_NON_RENEWED"


class Recommendation(str, Enum):
    RENEW = "RENEW"
    NON_RENEW = "NON_RENEW"


class GrievanceCategory(str, Enum):
    PROCEDURAL = "PROCEDURAL"
    NOTICE_UNTIMELY = "NOTICE_UNTIMELY"
    RETALIATION = "RETALIATION"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    RESOLVED_DENIED = "RESOLVED_DENIED"
    RESOLVED_SUSTAINED = "RESOLVED_SUSTAINED"


class GrievanceOutcome(str, Enum):
    DENY = "DENY"
    SUSTAIN = "SUSTAIN"


class ExitReason(str, Enum):
    TERM_COMPLETION = "TERM_COMPLETION"
    NON_RENEWAL = "NON_RENEWAL"
    RESIGNATION = "RESIGNATION"
    COMPLIANCE_TERMINATION = "COMPLIANCE_TERMINATION"


class ExitRecordStatus(str, Enum):
    INITIATED = "INITIATED"
    IP_ASSIGNMENT_SIGNED = "IP_ASSIGNMENT_SIGNED"
    CLOSED = "CLOSED"


class VerificationDecision(str, Enum):
    VERIFY = "VERIFY"
    SUSPEND = "SUSPEND"


class DocumentReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Every entity below carries id / created_at / updated_at / version: PRD
# section 2.4 states that no entity in this system is exempt.

class Postdoc(TypedDict):
    id: str
    full_name: str
    email: str
    citizenship_country: str
    requires_sponsorship: bool
    phd_award_date: str
    prior_external_months_in_rank: int
    o1_endorsement_on_file: bool
    j1_two_year_bar_flag: bool
    restricted_party_flag: bool
    status: str
    total_months_in_rank: int
    created_at: str
    updated_at: str
    version: int


class FacultyMentor(TypedDict):
    id: str
    full_name: str
    department: str
    mentor_training_valid_through: str
    max_concurrent_postdocs: int
    active_postdoc_count: int
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict):
    id: str
    sponsor_name: str
    funding_type: str
    salary_floor_policy: str
    award_start_date: str
    award_end_date: str
    annual_budget_usd: float
    requires_mentoring_plan: bool
    requires_idp: bool
    verification_status: str
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    encumbered_usd: float
    available_balance_usd: float
    created_at: str
    updated_at: str
    version: int


class Laboratory(TypedDict):
    id: str
    name: str
    biosafety_level: str
    bench_capacity: int
    decontamination_buffer_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    postdoc_id: str
    mentor_id: str
    funding_source_id: str
    predecessor_appointment_id: Optional[str]
    title_classification: str
    employment_class: str
    term_start_date: str
    term_end_date: str
    annual_salary_usd: float
    appointment_status: str
    compliance_status: str
    prepared_by_user_id: str
    term_months: int
    months_in_rank_at_start: int
    cumulative_months_in_rank_at_end: int
    salary_floor_usd: float
    salary_exception_floor_usd: Optional[float]
    salary_exception_approved_by_user_id: Optional[str]
    justification: Optional[str]
    benefits_package: str
    fringe_rate: float
    encumbrance_usd: float
    withdraw_reason: Optional[str]
    reinstated_count: int
    created_at: str
    updated_at: str
    version: int


class VisaCase(TypedDict):
    id: str
    appointment_id: str
    visa_category: str
    processing_track: str
    status: str
    filed_at: Optional[str]
    rfe_round_count: int
    projection_variant: Optional[str]
    projected_decision_date: Optional[str]
    earliest_lawful_start_date: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DevelopmentDocument(TypedDict):
    id: str
    appointment_id: str
    doc_type: str
    status: str
    content_summary: Optional[str]
    postdoc_acknowledged: bool
    submitted_by_user_id: Optional[str]
    revision_round: int
    reviewer_note: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExportControlReview(TypedDict):
    id: str
    appointment_id: str
    cycle_index: int
    status: str
    restricted_party_hit: bool
    controlled_technology_flag: bool
    screening_tier: Optional[str]
    risk_score: Optional[float]
    deemed_export_license_required: bool
    reviewer_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabAccessGrant(TypedDict):
    id: str
    appointment_id: str
    laboratory_id: str
    bench_seats: int
    access_start_date: str
    access_end_date: str
    status: str
    suspension_reason: str
    requested_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ReappointmentReview(TypedDict):
    id: str
    appointment_id: str
    review_cycle: int
    status: str
    recommendation: Optional[str]
    mentor_recommendation_note: Optional[str]
    recommended_by_user_id: Optional[str]
    finalized_by_user_id: Optional[str]
    service_months_at_review: Optional[int]
    notice_days_required: Optional[int]
    notice_deadline_date: Optional[str]
    notice_issued_at: Optional[str]
    notice_timely: Optional[bool]
    grievance_window_end: Optional[str]
    pre_notice_term_end_date: Optional[str]
    term_extension_days: int
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict):
    id: str
    reappointment_review_id: str
    category: str
    narrative: str
    status: str
    filed_at: str
    filed_by_user_id: str
    resolution_note: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExitRecord(TypedDict):
    id: str
    appointment_id: str
    exit_reason: str
    status: str
    initiated_at: str
    ip_disclosure_count: int
    ip_assignment_signed_at: Optional[str]
    lab_access_cleared: bool
    final_months_posted: int
    created_at: str
    updated_at: str
    version: int
