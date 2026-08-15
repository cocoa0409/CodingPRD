"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PRESERVATION_STAFF = "PreservationStaff"
    COMMISSIONER = "Commissioner"
    COUNCIL_MEMBER = "CouncilMember"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"


class SignificanceTier(str, Enum):
    LOCAL = "LOCAL"
    LANDMARK = "LANDMARK"
    ICONIC = "ICONIC"


class DistrictStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BOUNDARY_REVIEW = "BOUNDARY_REVIEW"


class GuidelineSetStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class ContributingStatus(str, Enum):
    CONTRIBUTING = "CONTRIBUTING"
    NON_CONTRIBUTING = "NON_CONTRIBUTING"
    VACANT_LOT = "VACANT_LOT"


class ListingStatus(str, Enum):
    INVENTORY = "INVENTORY"
    DEMOLITION_PENDING = "DEMOLITION_PENDING"
    DEMOLISHED = "DEMOLISHED"


class ApplicationType(str, Enum):
    ALTERATION = "ALTERATION"
    ADDITION = "ADDITION"
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"
    DEMOLITION = "DEMOLITION"
    RELOCATION = "RELOCATION"


class WorkCategory(str, Enum):
    EXTERIOR_ALTERATION = "EXTERIOR_ALTERATION"
    ADDITION = "ADDITION"
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"
    DEMOLITION = "DEMOLITION"
    RELOCATION = "RELOCATION"
    SITE_WORK = "SITE_WORK"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_STAFF_REVIEW = "UNDER_STAFF_REVIEW"
    INCOMPLETE = "INCOMPLETE"
    ACCEPTED = "ACCEPTED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    HEARING_DEFERRED = "HEARING_DEFERRED"
    HEARING_OPEN = "HEARING_OPEN"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    DENIED = "DENIED"
    APPROVED_ON_APPEAL = "APPROVED_ON_APPEAL"
    DENIED_FINAL = "DENIED_FINAL"
    WITHDRAWN = "WITHDRAWN"


class ReviewTrack(str, Enum):
    STAFF = "STAFF"
    COMMISSION = "COMMISSION"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPENED = "OPENED"
    CONTINUED = "CONTINUED"
    DECIDED = "DECIDED"
    WITHDRAWN = "WITHDRAWN"


class CommentStance(str, Enum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"
    NEUTRAL = "NEUTRAL"


class AppealStatus(str, Enum):
    FILED = "FILED"
    DECIDED_SUSTAINED = "DECIDED_SUSTAINED"
    DECIDED_UPHELD = "DECIDED_UPHELD"
    WITHDRAWN = "WITHDRAWN"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    AFTER_THE_FACT_PENDING = "AFTER_THE_FACT_PENDING"
    COMPLIANCE_VERIFIED = "COMPLIANCE_VERIFIED"
    COURT_REFERRAL = "COURT_REFERRAL"
    CLOSED = "CLOSED"


class DemolitionDelayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    LIFTED_BY_HARDSHIP = "LIFTED_BY_HARDSHIP"


class HardshipReviewStatus(str, Enum):
    FILED = "FILED"
    HEARD = "HEARD"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    CONDITIONS_VERIFIED = "CONDITIONS_VERIFIED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class PreservationPosture(str, Enum):
    STABLE = "STABLE"
    AT_RISK = "AT_RISK"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    UNDER_ENFORCEMENT = "UNDER_ENFORCEMENT"


# --- Entity TypedDicts (PRD §2.4 common fields: id, created_at, updated_at, version) ---


class HistoricDistrict(TypedDict, total=False):
    id: str
    name: str
    boundary_description: str
    significance_tier: str
    status: str
    contributing_count: int
    total_inventory_count: int
    preservation_posture: str
    created_at: str
    updated_at: str
    version: int


class DesignGuidelineSet(TypedDict, total=False):
    id: str
    district_id: str
    title: str
    sections: List[Dict[str, Any]]
    version_no: int
    adopted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PropertyOwner(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    mailing_address: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    address: str
    parcel_number: str
    district_id: Optional[str]
    owner_id: str
    contributing_status: str
    construction_year: int
    assessed_value_cents: int
    listing_status: str
    open_violation_count: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    property_id: str
    owner_id: str
    application_type: str
    is_visible_from_public_way: bool
    after_the_fact: bool
    violation_id: Optional[str]
    work_items: List[Dict[str, Any]]
    declared_cost_cents: int
    provisional_fee_cents: int
    verified_work_items: List[Dict[str, Any]]
    verified_cost_cents: Optional[int]
    review_track: Optional[str]
    assessed_fee_cents: Optional[int]
    paid_fee_cents: int
    refunded_fee_cents: int
    fee_balance_cents: int
    guideline_set_id: Optional[str]
    completeness_accepted_by: Optional[str]
    resubmission_count: int
    returned_at: Optional[str]
    decided_at: Optional[str]
    decision_conditions: List[str]
    denial_rationale_sections: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionMeeting(TypedDict, total=False):
    id: str
    meeting_date: str
    location: str
    agenda_capacity: int
    scheduled_hearing_count: int
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict, total=False):
    id: str
    application_id: str
    meeting_id: str
    notice_posted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# PublicComment is the single exception to the common fields: an immutable
# record of testimony carrying only id and created_at (PRD §2.4). No
# updated_at, no version.
class PublicComment(TypedDict, total=False):
    id: str
    hearing_id: str
    commenter_name: str
    stance: str
    comment_text: str
    submitted_at: str
    created_at: str


class Appeal(TypedDict, total=False):
    id: str
    application_id: str
    filed_at: str
    grounds: str
    council_findings: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    property_id: str
    observed_violation_date: str
    work_description: str
    notice_issued_at: Optional[str]
    demand_letter_amount_cents: Optional[int]
    compliance_verified_at: Optional[str]
    referred_at: Optional[str]
    final_penalty_cents: Optional[int]
    penalty_capped: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class DemolitionDelay(TypedDict, total=False):
    id: str
    application_id: str
    property_id: str
    base_delay_days: int
    postponement_count: int
    delay_start_at: str
    provisional_delay_end: str
    final_delay_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HardshipReview(TypedDict, total=False):
    id: str
    application_id: str
    filed_at: str
    claimed_rate_of_return_pct: float
    appraisal_basis_cents: int
    findings: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    application_id: str
    issued_at: str
    work_commence_deadline: str
    conditions: List[str]
    conditions_met_count: int
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
