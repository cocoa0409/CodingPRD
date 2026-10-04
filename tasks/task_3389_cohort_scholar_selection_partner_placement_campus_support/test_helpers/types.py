"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    NOMINATOR = "Nominator"
    ASSESSOR = "Assessor"
    SELECTION_OFFICER = "SelectionOfficer"
    NOMINEE = "Nominee"
    FACULTY_MENTOR = "FacultyMentor"
    CAREER_DIRECTOR = "CareerDirector"
    SCHOLAR = "Scholar"


class PartnerKind(str, Enum):
    HIGH_SCHOOL = "HIGH_SCHOOL"
    COMMUNITY_ORG = "COMMUNITY_ORG"


class NomineeStatus(str, Enum):
    NOMINATED = "NOMINATED"
    ROUND_1 = "ROUND_1"
    ROUND_2 = "ROUND_2"
    ROUND_3 = "ROUND_3"
    SELECTED = "SELECTED"
    WAITLISTED = "WAITLISTED"
    PLACED = "PLACED"
    DROPPED = "DROPPED"
    WITHDRAWN = "WITHDRAWN"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    FULFILLED = "FULFILLED"


class CohortStatus(str, Enum):
    FORMING = "FORMING"
    LOCKED = "LOCKED"
    MATRICULATED = "MATRICULATED"
    COMPLETED = "COMPLETED"


class EnrollmentStatus(str, Enum):
    PRE_COLLEGIATE = "PRE_COLLEGIATE"
    MATRICULATED = "MATRICULATED"
    RETAINED = "RETAINED"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"
    DISMISSED = "DISMISSED"


class Standing(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"


class CollegeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    LAPSED = "LAPSED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"


class InternshipStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class TrainingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    COMPLETED = "COMPLETED"


class ModuleCode(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"
    T5 = "T5"
    T6 = "T6"
    T7 = "T7"
    T8 = "T8"


class TrainingCategory(str, Enum):
    ACADEMIC = "ACADEMIC"
    LEADERSHIP = "LEADERSHIP"
    TEAM_BUILDING = "TEAM_BUILDING"


class MeetingKind(str, Enum):
    COHORT = "COHORT"
    INDIVIDUAL = "INDIVIDUAL"


class Decision(str, Enum):
    ADVANCE = "ADVANCE"
    WAITLIST = "WAITLIST"
    DROP = "DROP"


class RenewalDecision(str, Enum):
    RENEW = "RENEW"
    LAPSE = "LAPSE"


# --- Entity bodies (common_fields: id + created_at [+ updated_at + version]) ---


class CityProgram(TypedDict, total=False):
    id: str
    code: str
    name: str
    admissions_cycle: str
    nomination_window_opens_at: str
    nomination_window_closes_at: str
    created_at: str
    updated_at: str
    version: int


class NominatingPartner(TypedDict, total=False):
    id: str
    city_program_id: str
    name: str
    kind: str
    nomination_quota: int
    nominations_used: int
    created_at: str
    updated_at: str
    version: int


class Nominee(TypedDict, total=False):
    id: str
    city_program_id: str
    nominator_id: str
    full_name: str
    first_generation: bool
    status: str
    current_round: int
    round_1_score: Optional[int]
    round_2_score: Optional[int]
    round_3_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict, total=False):
    # Append-only record: carries ONLY id + created_at — no updated_at, no version.
    id: str
    created_at: str
    nominee_id: str
    round_number: int
    assessor_ref: str
    leadership: int
    teamwork: int
    group_presence: int
    weighted_score: int


class PartnerCollege(TypedDict, total=False):
    id: str
    name: str
    status: str
    renewed_cycles_count: int
    created_at: str
    updated_at: str
    version: int


class Mentor(TypedDict, total=False):
    id: str
    partner_college_id: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class PartnerAgreement(TypedDict, total=False):
    id: str
    partner_college_id: str
    admissions_cycle: str
    cohort_size: int
    tuition_annual_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict, total=False):
    id: str
    agreement_id: str
    city_program_id: str
    partner_college_id: str
    mentor_id: str
    cohort_size: int
    tuition_annual_cents: int
    status: str
    seats_committed: int
    offers_outstanding: int
    seats_remaining: int
    projected_fill_provisional: int
    projected_fill_final: int
    meetings_held_count: int
    invoice_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    nominee_id: str
    cohort_id: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Scholar(TypedDict, total=False):
    id: str
    cohort_id: str
    nominee_id: str
    enrollment_status: str
    standing: str
    ever_matriculated: bool
    training_completed_count: int
    alumni_network_access: bool
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    scholar_id: str
    module_code: str
    category: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CohortMeeting(TypedDict, total=False):
    id: str
    cohort_id: str
    kind: str
    scholar_id: Optional[str]
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


class Internship(TypedDict, total=False):
    id: str
    scholar_id: str
    employer_name: str
    starts_on: str
    ends_on: str
    status: str
    created_at: str
    updated_at: str
    version: int
