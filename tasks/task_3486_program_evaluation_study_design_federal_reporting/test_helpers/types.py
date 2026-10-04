"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the standard system-managed fields (id, created_at,
updated_at, version) per PRD common-resource rules; no append-only
exemptions exist in this domain.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    AGENCY_OFFICER = "AgencyOfficer"
    PRINCIPAL_INVESTIGATOR = "PrincipalInvestigator"
    STUDY_DIRECTOR = "StudyDirector"
    DATA_MANAGER = "DataManager"
    IRB_REVIEWER = "IRBReviewer"
    PEER_REVIEWER = "PeerReviewer"
    PARTICIPANT = "Participant"
    EXTERNAL_RESEARCHER = "ExternalResearcher"
    PLATFORM_ADMIN = "PlatformAdmin"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class StudyStatus(str, Enum):
    DESIGN = "DESIGN"
    RECRUITMENT = "RECRUITMENT"
    DATA_COLLECTION = "DATA_COLLECTION"
    ANALYSIS = "ANALYSIS"
    REPORTING = "REPORTING"
    DISSEMINATION = "DISSEMINATION"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class SampleAdequacy(str, Enum):
    UNASSESSED = "UNASSESSED"
    ADEQUATE = "ADEQUATE"
    UNDERPOWERED = "UNDERPOWERED"


class DesignType(str, Enum):
    RCT = "RCT"
    QED_MATCHING = "QED_MATCHING"
    QED_RDD = "QED_RDD"
    QED_DID = "QED_DID"


class DesignPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AGENCY_APPROVED = "AGENCY_APPROVED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class IRBProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    MODIFICATIONS_REQUIRED = "MODIFICATIONS_REQUIRED"
    EXPIRED = "EXPIRED"


class SiteStatus(str, Enum):
    PROSPECTED = "PROSPECTED"
    CONTACTED = "CONTACTED"
    RECRUITED = "RECRUITED"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class ParticipantStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    CONSENTED = "CONSENTED"
    RANDOMIZED_TREATMENT = "RANDOMIZED_TREATMENT"
    RANDOMIZED_CONTROL = "RANDOMIZED_CONTROL"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class WithdrawalReason(str, Enum):
    PARTICIPANT_INITIATED = "PARTICIPANT_INITIATED"
    SITE_WITHDRAWN = "SITE_WITHDRAWN"
    CONTRACT_TERMINATED = "CONTRACT_TERMINATED"


class WaveType(str, Enum):
    SURVEY = "SURVEY"
    ADMIN_RECORDS = "ADMIN_RECORDS"
    SITE_VISIT = "SITE_VISIT"


class WaveStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    LINKED = "LINKED"
    CANCELLED = "CANCELLED"


class RecordStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    LINKED = "LINKED"
    QUARANTINED = "QUARANTINED"


class AnalysisPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PREREGISTERED = "PREREGISTERED"


class ReportType(str, Enum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PEER_REVIEWED = "PEER_REVIEWED"
    ACCEPTED = "ACCEPTED"
    REVISION = "REVISION"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class RestrictedUseFileStatus(str, Enum):
    DRAFT = "DRAFT"
    DISCLOSURE_REVIEW = "DISCLOSURE_REVIEW"
    RISK_REJECTED = "RISK_REJECTED"
    RELEASED = "RELEASED"


class DisseminationType(str, Enum):
    WEBINAR = "WEBINAR"
    TA_SESSION = "TA_SESSION"
    BRIEF = "BRIEF"


class DisseminationStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EvaluationContract(TypedDict):
    id: str
    agency_code: str
    title: str
    award_amount_cents: int
    deliverable_report_count: int
    disbursed_cents: int
    forfeited_cents: int
    remaining_cents: int
    status: str
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Study(TypedDict):
    id: str
    contract_id: str
    title: str
    research_question: str
    status: str
    committed_projected_n: int
    pipeline_projected_n: int
    enrolled_total: int
    quarantined_record_count: int
    sample_adequacy: str
    created_at: str
    updated_at: str
    version: int


class DesignPlan(TypedDict):
    id: str
    study_id: str
    design_type: str
    mde: float
    cluster_size: int
    icc: float
    attrition_rate: float
    alpha: float
    power_target: float
    randomization_ratio_num: int
    randomization_ratio_den: int
    n_per_arm: int
    required_total_n: int
    revision_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IRBProtocol(TypedDict):
    id: str
    study_id: str
    title: str
    estimated_burden_minutes: int
    status: str
    approval_start: Optional[str]
    approval_end: Optional[str]
    consent_form_version: int
    submitted_by_id: Optional[str]
    decided_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    study_id: str
    name: str
    max_participants: int
    enrolled_count: int
    randomized_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    site_id: str
    external_ref: str
    status: str
    consent_form_version: Optional[int]
    consented_at: Optional[str]
    burden_total_minutes: int
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataCollectionWave(TypedDict):
    id: str
    study_id: str
    wave_type: str
    site_id: Optional[str]
    open_at: str
    close_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ResponseRecord(TypedDict):
    id: str
    wave_id: str
    participant_id: str
    instrument_minutes: int
    payload_ref: str
    billed_minutes: int
    linkage_key: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnalysisPlan(TypedDict):
    id: str
    study_id: str
    primary_outcomes: List[str]
    secondary_outcomes: List[str]
    amendment_count: int
    registered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FindingsReport(TypedDict):
    id: str
    study_id: str
    title: str
    report_type: str
    addressed_primary_outcomes: List[str]
    payment_milestone_cents: int
    revision_count: int
    submitted_by_id: Optional[str]
    reviewed_by_id: Optional[str]
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    peer_review_due: Optional[str]
    revision_due: Optional[str]
    publication_due: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RestrictedUseFile(TypedDict):
    id: str
    study_id: str
    title: str
    cell_counts: List[int]
    sensitivity_weights: List[float]
    suppressed_cell_count: Optional[int]
    max_risk: Optional[float]
    mean_risk: Optional[float]
    prepared_by_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DisseminationActivity(TypedDict):
    id: str
    study_id: str
    activity_type: str
    title: str
    scheduled_at: str
    operator_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
