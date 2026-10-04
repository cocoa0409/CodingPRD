"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CNCS_PROGRAM_OFFICER = "CNCSProgramOfficer"
    GRANTEE_STAFF = "GranteeStaff"
    MEMBER = "Member"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRUST_ADMINISTRATOR = "TrustAdministrator"


class OrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEBARRED = "DEBARRED"


class OrgType(str, Enum):
    NONPROFIT = "NONPROFIT"
    PUBLIC_AGENCY = "PUBLIC_AGENCY"
    INSTITUTION_OF_HIGHER_ED = "INSTITUTION_OF_HIGHER_ED"
    TRIBAL = "TRIBAL"


class CompetitionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDS_FINALIZED = "AWARDS_FINALIZED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"


class AwardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    FILLED = "FILLED"
    VACATED = "VACATED"
    RETIRED = "RETIRED"


class TermCategory(str, Enum):
    FULL_TIME = "FULL_TIME"
    HALF_TIME = "HALF_TIME"
    REDUCED_HALF_TIME = "REDUCED_HALF_TIME"
    QUARTER_TIME = "QUARTER_TIME"
    MINIMUM_TIME = "MINIMUM_TIME"
    ABBREVIATED_TIME = "ABBREVIATED_TIME"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEBARRED = "DEBARRED"


class CitizenshipStatus(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    US_NATIONAL = "US_NATIONAL"
    LAWFUL_PERMANENT_RESIDENT = "LAWFUL_PERMANENT_RESIDENT"


class ComponentStatus(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class Adjudication(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class CheckComponent(str, Enum):
    NSOPR = "NSOPR"
    STATE_REPOSITORY = "STATE_REPOSITORY"
    FBI_FINGERPRINT = "FBI_FINGERPRINT"


class EnrollmentStatus(str, Enum):
    PENDING_CHECKS = "PENDING_CHECKS"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED_SUCCESSFUL = "EXITED_SUCCESSFUL"
    EXITED_COMPELLING = "EXITED_COMPELLING"
    RELEASED_FOR_CAUSE = "RELEASED_FOR_CAUSE"
    CANCELLED = "CANCELLED"


class SuspensionOrigin(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    AWARD_CASCADE = "AWARD_CASCADE"


class ExitReason(str, Enum):
    SUCCESSFUL = "SUCCESSFUL"
    COMPELLING_CIRCUMSTANCE = "COMPELLING_CIRCUMSTANCE"
    FOR_CAUSE = "FOR_CAUSE"


class HourEntryStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class ActivityCode(str, Enum):
    DIRECT_SERVICE = "DIRECT_SERVICE"
    CAPACITY_BUILDING = "CAPACITY_BUILDING"
    TRAINING = "TRAINING"
    FUNDRAISING = "FUNDRAISING"
    PROSELYTIZING = "PROSELYTIZING"
    PARTISAN_LOBBYING = "PARTISAN_LOBBYING"


class EducationAwardStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_USED = "PARTIALLY_USED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class UseStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESCINDED = "RESCINDED"


class UseType(str, Enum):
    TUITION = "TUITION"
    QUALIFIED_LOAN = "QUALIFIED_LOAN"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    CLOSED = "CLOSED"


class VisitType(str, Enum):
    SITE_VISIT = "SITE_VISIT"
    FILE_REVIEW = "FILE_REVIEW"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    ACTION_ASSIGNED = "ACTION_ASSIGNED"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class GrievanceOutcome(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class MeasureStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class MeasureCode(str, Enum):
    MSY_OUTPUT = "MSY_OUTPUT"
    BENEFICIARY_OUTCOME = "BENEFICIARY_OUTCOME"
    COMMUNITY_OUTCOME = "COMMUNITY_OUTCOME"


class MatchCategory(str, Enum):
    CASH = "CASH"
    IN_KIND = "IN_KIND"


# --- Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version) ---

class GranteeOrganization(TypedDict, total=False):
    id: str
    legal_name: str
    ein: str
    org_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantCompetition(TypedDict, total=False):
    id: str
    title: str
    fiscal_year: int
    application_open_at: str
    application_close_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantApplication(TypedDict, total=False):
    id: str
    competition_id: str
    organization_id: str
    federal_share_requested_cents: int
    slot_requests: list
    match_lines: list
    allowable_match_commitment_cents: int
    total_term_minutes: int
    msy_requested: float
    cost_per_msy_federal_cents: float
    cost_per_msy_total_cents: float
    clarification_question: Optional[str]
    clarification_response: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantAward(TypedDict, total=False):
    id: str
    application_id: str
    organization_id: str
    competition_id: str
    federal_share_awarded_cents: int
    total_term_minutes: int
    awarded_slot_count: int
    cost_per_msy_awarded_cents: float
    allowable_match_cents: int
    suspension_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PositionSlot(TypedDict, total=False):
    id: str
    award_id: str
    term_category: str
    slot_index: int
    fill_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    citizenship_status: str
    status: str
    for_cause_release_count: int
    created_at: str
    updated_at: str
    version: int


class CriminalHistoryCheck(TypedDict, total=False):
    id: str
    member_id: str
    check_seq: int
    nsopr_status: str
    state_status: str
    fbi_status: str
    adjudication: str
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MemberEnrollment(TypedDict, total=False):
    id: str
    member_id: str
    award_id: str
    slot_id: str
    term_category: str
    term_minutes: int
    service_start_date: str
    service_end_date: str
    certified_minutes: int
    fundraising_certified_minutes: int
    allowance_paid_cents: int
    suspension_origin: str
    exit_reason: Optional[str]
    exited_at: Optional[str]
    exit_overpayment_cents: Optional[int]
    education_award_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceHourEntry(TypedDict, total=False):
    id: str
    enrollment_id: str
    service_date: str
    minutes: int
    activity_code: str
    reject_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LivingAllowancePayment(TypedDict, total=False):
    # Immutable disbursement record: carries ONLY id and created_at of the
    # common field set — no updated_at, no version (PRD §2.5).
    id: str
    enrollment_id: str
    amount_cents: int
    note: Optional[str]
    created_at: str


class EducationAward(TypedDict, total=False):
    id: str
    member_id: str
    enrollment_id: str
    term_category: str
    issued_amount_cents: int
    remaining_balance_cents: int
    issued_at: str
    use_deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EducationAwardUse(TypedDict, total=False):
    id: str
    education_award_id: str
    use_type: str
    amount_cents: int
    institution_title_iv: Optional[bool]
    decision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceVisit(TypedDict, total=False):
    id: str
    award_id: str
    visit_type: str
    scheduled_date: str
    created_by_officer_id: str
    conducted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict, total=False):
    id: str
    visit_id: str
    award_id: str
    severity: str
    description: str
    requirement: Optional[str]
    due_days: Optional[int]
    due_at: Optional[str]
    evidence_note: Optional[str]
    submitted_by_org_id: Optional[str]
    decided_by_officer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict, total=False):
    id: str
    enrollment_id: str
    description: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceMeasure(TypedDict, total=False):
    id: str
    award_id: str
    measure_code: str
    target_value: int
    unit: str
    latest_period_start: Optional[str]
    latest_period_end: Optional[str]
    latest_actual_value: Optional[int]
    review_comment: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
