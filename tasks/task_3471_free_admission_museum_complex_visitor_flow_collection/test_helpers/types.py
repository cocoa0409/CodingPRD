"""Domain vocabulary: entity record shapes, status enumerations, and the role enum.

Every record the API returns carries the four common properties from PRD §2.5
(`id`, `created_at`, `updated_at`, `version`) because every entity in this
domain is a full lifecycle entity — there are no append-only logs here.

Field names below are PRD-exact. Optional[...] marks fields the PRD declares
nullable (for example `holder_member_id` on a pass, `review_id` on an
expenditure, `submitted_by_user_id` on a fresh review).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ── Roles (PRD §2.1 — the fifteen roles, spelled exactly) ────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    VISITOR_SERVICES = "VisitorServices"
    SECURITY_SCREENER = "SecurityScreener"
    EXHIBITION_MANAGER = "ExhibitionManager"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    DOCENT = "Docent"
    PUBLIC = "Public"
    MEMBER = "Member"
    LOANS_OFFICER = "LoansOfficer"
    BORROWER_REP = "BorrowerRep"
    REGISTRAR = "Registrar"
    CURATOR = "Curator"
    COMMITTEE_CHAIR = "CommitteeChair"
    FINANCE_OFFICER = "FinanceOfficer"
    SCHOLAR = "Scholar"


# ── Enumerated field vocabularies ────────────────────────────────────────────
class PassStatus(str, Enum):
    RESERVED = "RESERVED"
    ADMITTED = "ADMITTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class ExhibitionStatus(str, Enum):
    DRAFT = "DRAFT"
    ON_SALE = "ON_SALE"
    CLOSED = "CLOSED"


class TicketStatus(str, Enum):
    PURCHASED = "PURCHASED"
    REDEEMED = "REDEEMED"
    REFUNDED = "REFUNDED"


class DayOfWeek(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class CertificationLevel(str, Enum):
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class ProgramStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class ReservationStatus(str, Enum):
    # REQUESTED exists only transiently during creation evaluation; the stored
    # state is always CONFIRMED or WAITLISTED (PRD §3.3).
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class ObjectStatus(str, Enum):
    IN_COLLECTION = "IN_COLLECTION"
    OUT_ON_LOAN = "OUT_ON_LOAN"
    UNDER_CONSERVATION = "UNDER_CONSERVATION"
    PENDING_DEACCESSION = "PENDING_DEACCESSION"
    DEACCESSIONED = "DEACCESSIONED"
    REPATRIATED = "REPATRIATED"


class LoanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    AGREED = "AGREED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CoverageType(str, Enum):
    INSURANCE = "INSURANCE"
    INDEMNITY = "INDEMNITY"


class ReportKind(str, Enum):
    OUTBOUND = "OUTBOUND"
    RETURN = "RETURN"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ReportOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"


class ReviewKind(str, Enum):
    ACQUISITION = "ACQUISITION"
    DEACCESSION = "DEACCESSION"


class DisposalMethod(str, Enum):
    TRANSFER = "TRANSFER"
    SALE = "SALE"
    DESTRUCTION = "DESTRUCTION"
    REPATRIATION = "REPATRIATION"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class ReviewOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FundType(str, Enum):
    FEDERAL = "FEDERAL"
    TRUST = "TRUST"


class FundStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class ActivityType(str, Enum):
    OPERATIONS = "OPERATIONS"
    EDUCATION = "EDUCATION"
    ACQUISITION = "ACQUISITION"
    EXHIBITION = "EXHIBITION"


class ExpenditureStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ResearchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ResearchOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# ── Entity record shapes (all carry the four common properties) ──────────────
class Museum(TypedDict, total=False):
    id: str
    museum_code: str
    display_name: str
    requires_timed_pass: bool
    quarter_hour_pass_quota: int
    daily_pass_quota: int
    screening_rate_per_quarter_hour: int
    closed_dates: List[str]
    # Forward-looking screening backlog for the current slot, exposed on reads
    # (PRD §3.1); not asserted as universally present on every write response.
    screening_backlog_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TimedEntryPass(TypedDict):
    id: str
    museum_id: str
    visitor_name: str
    holder_member_id: Optional[str]
    visit_date: str
    entry_quarter_hour: int
    status: str
    admitted_slot: Optional[int]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    membership_term_months: int
    expires_on: str
    member_status: str
    created_at: str
    updated_at: str
    version: int


class SpecialExhibition(TypedDict):
    id: str
    museum_id: str
    revenue_fund_id: str
    title: str
    fee_cents: int
    daily_ticket_quota: int
    member_presale_opens_at: str
    public_sale_opens_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExhibitionTicket(TypedDict):
    id: str
    exhibition_id: str
    member_id: Optional[str]
    buyer_name: str
    visit_date: str
    price_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EducationProgram(TypedDict):
    id: str
    museum_id: str
    title: str
    gallery_code: str
    day_of_week: str
    start_minute: int
    end_minute: int
    student_capacity: int
    docent_ratio: int
    max_group_size: int
    required_docent_certification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Docent(TypedDict):
    id: str
    full_name: str
    certification_level: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class DocentAssignment(TypedDict):
    id: str
    program_id: str
    docent_id: str
    service_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SchoolGroupReservation(TypedDict):
    id: str
    museum_id: str
    program_id: str
    school_name: str
    headcount: int
    visit_date: str
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class CollectionObject(TypedDict):
    id: str
    accession_number: str
    title: str
    declared_value_cents: int
    is_cultural_property: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanAgreement(TypedDict):
    id: str
    object_id: str
    borrower_institution: str
    loan_start_date: str
    loan_end_date: str
    declared_value_cents: int
    coverage_type: str
    courier_required: bool
    status: str
    negotiated_round: int
    premium_cents: int
    created_at: str
    updated_at: str
    version: int


class ConditionReport(TypedDict):
    id: str
    loan_id: str
    report_kind: str
    condition_summary: str
    damage_noted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CollectionReview(TypedDict):
    id: str
    review_kind: str
    object_id: Optional[str]
    fund_id: Optional[str]
    proposed_object_title: Optional[str]
    estimated_cost_cents: Optional[int]
    disposal_method: Optional[str]
    cultural_property_review_completed: bool
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundAccount(TypedDict):
    id: str
    fund_code: str
    fund_type: str
    appropriation_cents: int
    status: str
    receipts_cents: int
    settled_available_cents: int
    committed_available_cents: int
    created_at: str
    updated_at: str
    version: int


class Expenditure(TypedDict):
    id: str
    fund_id: str
    review_id: Optional[str]
    amount_cents: int
    activity_type: str
    memo: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ResearchAccessRequest(TypedDict):
    id: str
    object_id: str
    scholar_name: str
    research_topic: str
    visit_start_date: str
    visit_end_date: str
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int
