"""Domain types: entity TypedDicts, status enums, role enum.

All enum string values and field names mirror the PRD's resource definitions
exactly. Every entity in this domain carries the common system-managed fields
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD section on user and role-based access control)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    SURVEY_METHODOLOGIST = "SurveyMethodologist"
    COLLECTION_OFFICER = "CollectionOfficer"
    RESPONDENT = "Respondent"
    ESTIMATION_ANALYST = "EstimationAnalyst"
    DISCLOSURE_OFFICER = "DisclosureOfficer"
    RELEASE_MANAGER = "ReleaseManager"
    ACCREDITED_MEDIA = "AccreditedMedia"


# ---------------------------------------------------------------------------
# Shared dimension enums
# ---------------------------------------------------------------------------
class IndustryCode(str, Enum):
    MANUFACTURING = "MANUFACTURING"
    RETAIL = "RETAIL"
    HEALTHCARE = "HEALTHCARE"
    CONSTRUCTION = "CONSTRUCTION"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


# ---------------------------------------------------------------------------
# Status enums (one per entity state machine)
# ---------------------------------------------------------------------------
class FrameStatus(str, Enum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"
    SUPERSEDED = "SUPERSEDED"


class EnrollmentStatus(str, Enum):
    INVITED = "INVITED"
    ENROLLED = "ENROLLED"
    REFUSED = "REFUSED"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTING = "COLLECTING"
    PROCESSING = "PROCESSING"
    CERTIFIED = "CERTIFIED"
    PUBLISHED = "PUBLISHED"
    REVISION_OPEN = "REVISION_OPEN"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    IN_CONTACT = "IN_CONTACT"
    ESCALATED = "ESCALATED"
    CLOSED_RESPONDED = "CLOSED_RESPONDED"
    CLOSED_REFUSED = "CLOSED_REFUSED"
    CLOSED_UNRESPONSIVE = "CLOSED_UNRESPONSIVE"


class EstimateStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    REVISED = "REVISED"
    FINAL = "FINAL"
    RECONSTRUCTED = "RECONSTRUCTED"


class SuppressionStatus(str, Enum):
    NONE = "NONE"
    PRIMARY = "PRIMARY"
    COMPLEMENTARY = "COMPLEMENTARY"


class ImputationVariant(str, Enum):
    LINK_RELATIVE = "LINK_RELATIVE"
    STRATUM_MEAN = "STRATUM_MEAN"


class FactorSetStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class BenchmarkRunStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ANNOUNCED = "ANNOUNCED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class NoticeScope(str, Enum):
    ALL_SERIES = "ALL_SERIES"
    LISTED_SERIES = "LISTED_SERIES"


class PubStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EMBARGO_OPEN = "EMBARGO_OPEN"
    POSTPONED = "POSTPONED"
    PUBLISHED = "PUBLISHED"


class DisclosureStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AccreditationStatus(str, Enum):
    PENDING = "PENDING"
    ACCREDITED = "ACCREDITED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class GrantStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCESSED = "ACCESSED"
    REVOKED = "REVOKED"
    BREACHED = "BREACHED"


# ---------------------------------------------------------------------------
# Action enums (action-style endpoints)
# ---------------------------------------------------------------------------
class CycleAction(str, Enum):
    OPEN_COLLECTION = "OPEN_COLLECTION"
    CLOSE_COLLECTION = "CLOSE_COLLECTION"
    COMPUTE_ESTIMATES = "COMPUTE_ESTIMATES"
    CERTIFY = "CERTIFY"
    REOPEN_REVISION = "REOPEN_REVISION"


class ReportAction(str, Enum):
    SUBMIT = "SUBMIT"
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class LifecycleAction(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    EXIT = "EXIT"


class CaseAction(str, Enum):
    RECORD_CONTACT = "RECORD_CONTACT"
    VOID_CONTACT = "VOID_CONTACT"
    ESCALATE = "ESCALATE"
    CLOSE = "CLOSE"


class ReleaseAction(str, Enum):
    POSTPONE = "POSTPONE"
    RESCHEDULE = "RESCHEDULE"
    OPEN_EMBARGO = "OPEN_EMBARGO"
    APPROVE_DISCLOSURE = "APPROVE_DISCLOSURE"
    REJECT_DISCLOSURE = "REJECT_DISCLOSURE"
    PUBLISH = "PUBLISH"


class AccreditationAction(str, Enum):
    ACCREDIT = "ACCREDIT"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    REVOKE = "REVOKE"


class NoticeAction(str, Enum):
    ANNOUNCE = "ANNOUNCE"
    ACTIVATE = "ACTIVATE"
    WITHDRAW = "WITHDRAW"


class CloseOutcome(str, Enum):
    REFUSED = "REFUSED"
    UNRESPONSIVE = "UNRESPONSIVE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class SurveyProgram(TypedDict, total=False):
    id: str
    code: str
    name: str
    sample_budget: int
    embargo_window_minutes: int
    annual_burden_budget_minutes: int
    created_at: str
    updated_at: str
    version: int


class Stratum(TypedDict, total=False):
    industry_code: str
    size_class: str
    frame_unit_count: int
    allocated_sample_size: Optional[int]


class SampleFrame(TypedDict, total=False):
    id: str
    program_code: str
    reference_quarter: str
    strata: List[Stratum]
    total_sample_size: Optional[int]
    frame_status: str
    frozen_at: Optional[str]
    replaced_by_frame_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Establishment(TypedDict, total=False):
    id: str
    ein: str
    name: str
    industry_code: str
    size_class: str
    created_at: str
    updated_at: str
    version: int


class PanelEnrollment(TypedDict, total=False):
    id: str
    establishment_id: str
    program_code: str
    industry_code: str
    size_class: str
    base_weight: float
    burden_minutes_ytd: int
    burden_year: Optional[int]
    enrollment_status: str
    created_at: str
    updated_at: str
    version: int


class SurveyCycle(TypedDict, total=False):
    id: str
    program_code: str
    reference_month: str
    collection_open_at: str
    collection_close_at: str
    cycle_status: str
    estimates_computed_at: Optional[str]
    weighted_response_rate: Optional[float]
    unweighted_response_rate: Optional[float]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResponseReport(TypedDict, total=False):
    id: str
    enrollment_id: str
    cycle_id: str
    employment: int
    report_status: str
    submit_count: int
    submitted_at: str
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContactEntry(TypedDict, total=False):
    seq: int
    contact_minutes: int
    channel: str
    contacted_at: str
    voided: bool


class FollowUpCase(TypedDict, total=False):
    id: str
    enrollment_id: str
    cycle_id: str
    case_status: str
    opened_at: str
    contacts: List[ContactEntry]
    total_contact_minutes: int
    created_at: str
    updated_at: str
    version: int


class CellEstimate(TypedDict, total=False):
    id: str
    cycle_id: str
    program_code: str
    industry_code: str
    size_class: str
    estimate_status: str
    revision_no: int
    employment_estimate: Optional[int]
    variance_estimate: Optional[int]
    respondent_count: int
    enrolled_count: int
    dominance_flag: bool
    suppression_status: str
    imputation_variant: Optional[str]
    seasonally_adjusted_concurrent: Optional[int]
    seasonally_adjusted_revised: Optional[int]
    wedge_factor: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SeasonalFactorSet(TypedDict, total=False):
    id: str
    program_code: str
    industry_code: str
    size_class: str
    year: int
    factors: List[float]
    set_status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdminCellCount(TypedDict, total=False):
    industry_code: str
    size_class: str
    admin_employment: int


class BenchmarkRun(TypedDict, total=False):
    id: str
    program_code: str
    benchmark_month: str
    admin_cell_counts: List[AdminCellCount]
    run_status: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeriesRef(TypedDict, total=False):
    industry_code: str
    size_class: str


class MethodologyNotice(TypedDict, total=False):
    id: str
    program_code: str
    title: str
    effective_from: str
    scope: str
    series: Optional[List[SeriesRef]]
    reconstruction_factor_ppm: int
    notice_status: str
    announced_at: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseEvent(TypedDict, total=False):
    id: str
    cycle_id: str
    program_code: str
    release_at: str
    embargo_open_at: str
    pub_status: str
    disclosure_status: str
    revision_notice_required: bool
    active_embargo_grant_count: int
    created_at: str
    updated_at: str
    version: int


class MediaOutlet(TypedDict, total=False):
    id: str
    name: str
    outlet_code: str
    accreditation_status: str
    created_at: str
    updated_at: str
    version: int


class EmbargoGrant(TypedDict, total=False):
    id: str
    release_event_id: str
    media_outlet_id: str
    grant_status: str
    issued_at: str
    first_accessed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bulletin(TypedDict, total=False):
    release_event_id: str
    reference_month: str
    release_status: str
    embargoed: bool
    cells: List[Dict[str, Any]]
    industry_totals: List[Dict[str, Any]]
