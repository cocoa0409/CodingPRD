"""Domain types: entity TypedDicts, status enums, and the role enum.

Field names are PRD-exact.  Every entity in this API carries the common
system fields of PRD §2.5 (``id``, ``created_at``, ``updated_at``,
``version``); no append-only exceptions exist here, so every TypedDict lists
all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1 — twelve roles, spelled exactly) ────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"
    RECORDS_OFFICER = "RecordsOfficer"
    AGENCY_LIAISON = "AgencyLiaison"
    APPRAISAL_ARCHIVIST = "AppraisalArchivist"
    PROCESSING_ARCHIVIST = "ProcessingArchivist"
    DECLASS_REVIEWER = "DeclassReviewer"
    CHIEF_ARCHIVIST = "ChiefArchivist"
    RESEARCH_ROOM_STAFF = "ResearchRoomStaff"
    FOIA_OFFICER = "FoiaOfficer"
    FOIA_APPEALS_OFFICER = "FoiaAppealsOfficer"
    RESEARCHER = "Researcher"


# ─── Status enumerations (PRD §3 narratives) ─────────────────────────────────
class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPRAISED = "APPRAISED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    VALIDATED = "VALIDATED"
    DEFICIENT = "DEFICIENT"
    ACCESSIONED = "ACCESSIONED"
    WITHDRAWN = "WITHDRAWN"


class ProcessingStatus(str, Enum):
    UNPROCESSED = "UNPROCESSED"
    PROCESSING = "PROCESSING"
    DESCRIBED = "DESCRIBED"
    PUBLISHED = "PUBLISHED"


class DigitizationStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    QUEUED = "QUEUED"
    DIGITIZED = "DIGITIZED"


class RestrictionPosture(str, Enum):
    PUBLIC = "PUBLIC"
    CLASSIFIED_REVIEW_REQUIRED = "CLASSIFIED_REVIEW_REQUIRED"
    PRESIDENTIAL_HOLD = "PRESIDENTIAL_HOLD"


class ReviewType(str, Enum):
    SYSTEMATIC = "SYSTEMATIC"
    MANDATORY = "MANDATORY"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ReviewOutcome(str, Enum):
    NONE = "NONE"
    DECLASSIFIED = "DECLASSIFIED"
    PARTIAL = "PARTIAL"
    EXEMPT_RETAINED = "EXEMPT_RETAINED"


class ReferralStatus(str, Enum):
    SENT = "SENT"
    RESPONDED = "RESPONDED"


class ReferralDecision(str, Enum):
    NONE = "NONE"
    DECLASSIFY = "DECLASSIFY"
    EXEMPT = "EXEMPT"


class ResearcherStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class PullStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PULLED = "PULLED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class ReproductionStatus(str, Enum):
    QUOTED = "QUOTED"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class FoiaStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_REVIEW = "IN_REVIEW"
    GRANTED = "GRANTED"
    PARTIAL_GRANT = "PARTIAL_GRANT"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    APPEAL_GRANTED = "APPEAL_GRANTED"
    APPEAL_UPHELD = "APPEAL_UPHELD"
    CLOSED = "CLOSED"


class FoiaAdjudication(str, Enum):
    GRANT = "GRANT"
    PARTIAL = "PARTIAL"
    DENY = "DENY"


class FoiaAppealDecision(str, Enum):
    GRANT = "GRANT"
    UPHOLD = "UPHOLD"
    REMAND = "REMAND"


class RestrictionStatus(str, Enum):
    IMPOSED = "IMPOSED"
    NOTIFIED = "NOTIFIED"
    RELEASED = "RELEASED"


class AppraisalRecommendation(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


class ScheduleDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


# ─── Entity TypedDicts (PRD §2.5 common fields + §3 field names) ─────────────
class Agency(TypedDict, total=False):
    id: str
    agency_code: str
    name: str
    created_at: str
    updated_at: str
    version: int


class RecordsSchedule(TypedDict, total=False):
    id: str
    agency_id: str
    schedule_number: str
    title: str
    records_domain: str
    disposition: str
    transfer_lag_years: Optional[int]
    classification_default: str
    status: str
    appraiser_id: Optional[str]
    appraisal_recommendation: Optional[str]
    decided_by: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict, total=False):
    id: str
    schedule_id: str
    agency_id: str
    transfer_method: str
    metadata_standard: str
    unit_count: int
    linear_feet: Optional[float]
    checksum_manifest: Optional[str]
    records_cutoff_date: str
    status: str
    submitted_metadata_elements: List[str]
    last_missing_elements: List[str]
    accessioned_at: Optional[str]
    collection_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Collection(TypedDict, total=False):
    id: str
    transfer_id: str
    schedule_id: str
    agency_id: str
    records_domain: str
    classification_level: str
    records_cutoff_date: str
    units_total: int
    processing_status: str
    assigned_archivist_id: Optional[str]
    scope_note: Optional[str]
    arrangement_note: Optional[str]
    container_list_summary: Optional[str]
    restriction_posture: str
    backlog_score: int
    pull_count_total: int
    repro_pages_fulfilled: int
    foia_release_count: int
    digitization_status: str
    digitization_priority: Optional[int]
    declass_outcome: str
    created_at: str
    updated_at: str
    version: int


class DeclassReview(TypedDict, total=False):
    id: str
    collection_id: str
    review_type: str
    requester_researcher_id: Optional[str]
    justification: Optional[str]
    status: str
    lead_reviewer_id: Optional[str]
    reviewer_assessment: Optional[str]
    exemption_codes: List[str]
    outcome: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquityReferral(TypedDict, total=False):
    id: str
    review_id: str
    agency_id: str
    sent_at: str
    response_due_at: str
    status: str
    decision: Optional[str]
    exemption_code: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResearcherRegistration(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    affiliation: str
    id_document: str
    status: str
    card_expires_at: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PullRequest(TypedDict, total=False):
    id: str
    researcher_id: str
    collection_id: str
    unit_start: int
    unit_end: int
    visit_date: str
    status: str
    due_back_at: str
    returned_at: Optional[str]
    late_return: bool
    created_at: str
    updated_at: str
    version: int


class ReproductionRequest(TypedDict, total=False):
    id: str
    researcher_id: str
    collection_id: str
    page_count: int
    format: str
    rush: bool
    fee_cents: int
    status: str
    payment_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FoiaRequest(TypedDict, total=False):
    id: str
    researcher_id: str
    collection_id: str
    description_of_records: str
    status: str
    claimed_exemptions: List[str]
    adjudicator_id: Optional[str]
    decided_at: Optional[str]
    appeal_reason: Optional[str]
    appeal_decider_id: Optional[str]
    appeal_decision: Optional[str]
    remand_count: int
    close_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PresidentialRestriction(TypedDict, total=False):
    id: str
    collection_id: str
    category: str
    status: str
    representative_id: Optional[str]
    notified_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
