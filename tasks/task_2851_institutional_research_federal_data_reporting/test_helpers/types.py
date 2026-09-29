"""
Typed shapes for the Institutional Research & Federal Data Reporting API.

Each TypedDict mirrors the representation the PRD declares for one resource.
Almost every resource carries the four system-managed properties id, created_at,
updated_at and version. The single deliberate exception is FederalDefinition,
which is immutable configuration and therefore carries only id and created_at —
neither updated_at nor version appears in its representation.
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict

# ─── Enum-like literal aliases ────────────────────────────────────

RoleName = Literal[
    "IRAnalyst", "IRDirector", "RegistrarOfficer", "DataSteward", "DisclosureOfficer"
]
SnapshotPosture = Literal["OPEN", "CENSUS_LOCKED", "FROZEN", "REOPENED", "ARCHIVED"]
SurveyDomain = Literal["ENROLLMENT", "COMPLETIONS", "FINANCE", "HR"]
FrozenFileStatus = Literal["ACTIVE", "LOCKED", "SUPERSEDED"]
PrepStatus = Literal["DRAFT", "PREPARED", "CERTIFIED", "SUBMITTED"]
EditStatus = Literal["NOT_RUN", "OPEN_EDITS", "EXPLAINED", "CLEARED"]
EditCheckStatus = Literal[
    "OPEN", "EXPLAINED", "ACCEPTED", "WAIVED", "REJECTED", "VOIDED"
]
Severity = Literal["WARNING", "FATAL"]
MappingStatus = Literal["PROPOSED", "VALIDATED", "REJECTED"]
LocalSystemCode = Literal["SIS", "HR", "FIN", "ADV"]
CohortType = Literal["GRAD_RATE_150", "RETENTION_FT"]
CohortStatus = Literal["DRAFT", "LOCKED"]
EntryStatus = Literal["FULL_TIME", "PART_TIME"]
TrackedOutcome = Literal[
    "COMPLETED_150", "STILL_ENROLLED", "TRANSFERRED_OUT", "NO_LONGER_ENROLLED"
]
ExclusionStatus = Literal["NONE", "CLAIMED", "APPROVED", "DENIED"]
ExclusionCode = Literal[
    "DECEASED",
    "PERMANENTLY_DISABLED",
    "ARMED_FORCES",
    "FOREIGN_AID_SERVICE",
    "CHURCH_MISSION",
]
PublicationStatus = Literal[
    "PUBLISHED", "RESTATEMENT_PENDING", "RESTATED", "WITHDRAWN"
]
RestatementStatus = Literal[
    "SUBMITTED", "APPLIED", "REJECTED", "SUPERSEDED", "VOIDED"
]
RestatementOrigin = Literal["ANALYST", "CASCADE"]
TargetType = Literal["STATE", "CONSORTIUM", "RANKING"]
SubmissionStatus = Literal["DRAFT", "RECONCILED", "VARIANCE_HOLD", "TRANSMITTED"]
DataRequestStatus = Literal[
    "RECEIVED", "SCREENED", "REFUSED", "RELEASED", "SUPPRESSED_RELEASE"
]
RequesterType = Literal["INTERNAL", "EXTERNAL", "MEDIA"]
AvoidanceMethod = Literal["SMALL_CELL_SUPPRESSION", "CONTROLLED_ROUNDING"]
SuppressionState = Literal[
    "PENDING", "RELEASED", "PRIMARY_SUPPRESSED", "COMPLEMENTARY_SUPPRESSED"
]
Decision = Literal["ACCEPT", "WAIVE", "REJECT"]
ReviewDecision = Literal["APPROVE", "DENY"]


class CommonFields(TypedDict):
    """The four system-managed properties carried by almost every resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


# ─── Resources ────────────────────────────────────────────────────


class ReportingCycle(CommonFields):
    cycle_code: str
    collection_year: int
    census_date: str
    collection_deadline: str
    snapshot_posture: SnapshotPosture
    census_locked_at: Optional[str]
    frozen_at: Optional[str]
    reopen_count: int
    reopen_reason: Optional[str]
    active_record_count: int
    frozen_file_count: int


class FrozenFile(CommonFields):
    cycle_id: str
    domain: SurveyDomain
    record_count: int
    coverage_start_date: str
    coverage_end_date: str
    checksum: str
    status: FrozenFileStatus
    snapshot_taken_at: str
    supersedes_frozen_file_id: Optional[str]


class SurveyComponent(CommonFields):
    cycle_id: str
    frozen_file_id: str
    component_code: SurveyDomain
    prep_status: PrepStatus
    edit_status: EditStatus
    fatal_open_count: int
    mapping_coverage_pct: Optional[float]
    core_expense_per_fte_cents: Optional[int]
    prepared_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    certification_statement: Optional[str]
    submitted_at: Optional[str]


class ComponentMetric(CommonFields):
    component_id: str
    metric_key: str
    reported_value: float
    prior_year_value: Optional[float]
    source_field_path: str
    variance_pct: Optional[float]
    restated: bool
    restatement_note: Optional[str]


class EditCheck(CommonFields):
    component_id: str
    check_code: str
    metric_key: str
    severity: Severity
    status: EditCheckStatus
    sequence_no: int
    observed_value: Optional[float]
    prior_year_value: Optional[float]
    variance_pct: Optional[float]
    explanation_text: Optional[str]
    prior_year_comparison_note: Optional[str]
    explanation_round: int
    explained_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    adjudication_note: Optional[str]


class CohortDefinition(CommonFields):
    cycle_id: str
    cohort_type: CohortType
    entry_term: str
    publication_metric_key: str
    status: CohortStatus
    initial_count: int
    exclusion_count: int
    adjusted_count: int
    completers_count: int
    retained_count: int
    federal_rate_pct: Optional[float]
    ranking_rate_pct: Optional[float]
    locked_at: Optional[str]


class CohortMember(CommonFields):
    cohort_id: str
    student_local_id: str
    entry_status: EntryStatus
    outcome: TrackedOutcome
    exclusion_status: ExclusionStatus
    exclusion_code: Optional[ExclusionCode]
    exclusion_evidence_note: Optional[str]
    exclusion_claimed_by_user_id: Optional[str]
    exclusion_reviewed_by_user_id: Optional[str]
    review_note: Optional[str]


class RateSummary(TypedDict):
    """The computed read that exposes both rate variants side by side."""

    initial_count: int
    exclusion_count: int
    adjusted_count: int
    completers_count: int
    retained_count: int
    federal_rate_pct: Optional[float]
    ranking_rate_pct: Optional[float]
    rate_divergence_pp: Optional[float]


class FederalDefinition(TypedDict):
    """Immutable configuration: only id and created_at, no updated_at, no version."""

    id: str
    created_at: str
    definition_code: str
    survey_component: SurveyDomain
    value_domain: List[str]
    required: bool
    unit_of_measure: str
    effective_cycle_code: str


class ElementMapping(CommonFields):
    cycle_id: str
    definition_id: str
    local_system_code: LocalSystemCode
    local_field_path: str
    transform_expression: str
    value_map: Dict[str, str]
    status: MappingStatus
    revision_round: int
    validated_by_user_id: Optional[str]
    rejection_reason: Optional[str]


class ExternalSubmission(CommonFields):
    cycle_id: str
    component_id: str
    target_type: TargetType
    target_name: str
    metric_key: str
    reported_value: float
    status: SubmissionStatus
    federal_value: Optional[float]
    raw_delta_pct: Optional[float]
    allowance_pct: Optional[float]
    effective_delta_pct: Optional[float]
    tolerance_pct: Optional[float]
    override_reason: Optional[str]
    overridden_by_user_id: Optional[str]
    transmission_reference: Optional[str]
    transmitted_at: Optional[str]


class DashboardPublication(CommonFields):
    component_id: str
    metric_key: str
    published_value: float
    original_value: float
    net_applied_delta: float
    restatement_count: int
    effective_from: str
    effective_to: Optional[str]
    publication_status: PublicationStatus
    published_by_user_id: str
    withdrawal_reason: Optional[str]


class RestatementRequest(CommonFields):
    publication_id: str
    proposed_value: float
    baseline_value: float
    delta_pct: Optional[float]
    public_notice_required: bool
    public_notice_reference: Optional[str]
    justification: str
    status: RestatementStatus
    origin: RestatementOrigin
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]


class DataRequest(CommonFields):
    cycle_id: str
    requester_org: str
    requester_type: RequesterType
    requested_metric_key: str
    avoidance_method: AvoidanceMethod
    min_cell_size: int
    status: DataRequestStatus
    cell_count: int
    suppressed_cell_count: int
    released_cell_count: int
    residual_disclosure_risk: bool
    refusal_reason: Optional[str]
    screened_at: Optional[str]
    screened_by_user_id: Optional[str]
    release_note: Optional[str]


class DisclosureCell(CommonFields):
    request_id: str
    dimension_group: str
    dimension_key: str
    raw_count: int
    suppression_state: SuppressionState
    released_count: Optional[int]


class ClockReading(TypedDict):
    """The answer of the logical-clock endpoint."""

    current_utc: str


# ─── Envelope shapes ──────────────────────────────────────────────


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorPayload(TypedDict):
    error_id: str
    message: str


JsonDict = Dict[str, Any]
