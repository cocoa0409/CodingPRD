"""Typed shapes for every response body the API returns.

The common-field split of PRD §2.4 is reflected structurally: ``VersionedEntity``
carries ``updated_at`` and ``version`` on top of ``id`` and ``created_at``, while
``ImmutableEntity`` carries only ``id`` and ``created_at`` — that is the shape a
ReviewRecord has, because a review record is written once and never revised.
"""

from typing import Any, Dict, List, Optional, TypedDict


class VersionedEntity(TypedDict):
    """Base shape for the entities that are mutable and therefore versioned."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableEntity(TypedDict):
    """Base shape for the entities that carry only an identifier and a birth stamp."""

    id: str
    created_at: str


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class Analyst(VersionedEntity, total=False):
    full_name: str
    disciplines: List[str]
    competency_level: int
    weekly_capacity_hours: float
    training_hours_per_week: float
    employment_status: str
    qualification_state: str
    consecutive_pt_failures: int
    assigned_casework_hours: float
    probation_entered_at_utc: Optional[str]
    suspended_at_utc: Optional[str]


class Method(VersionedEntity, total=False):
    name: str
    discipline: str
    standard_hours_per_item: float
    min_competency_level: int
    max_items_per_request: int
    is_consumptive: bool
    accreditation_scope_code: str
    validation_status: str
    validation_study_item_count: int
    precision_cv_pct: float
    validated_at_utc: Optional[str]
    validation_expires_at_utc: Optional[str]
    retired_at_utc: Optional[str]
    retirement_reason: Optional[str]


class Case(VersionedEntity, total=False):
    agency_case_number: str
    submitting_agency: str
    offense_category: str
    violent_crime_flag: bool
    suspect_in_custody: bool
    statutory_deadline_utc: Optional[str]
    court_date_utc: Optional[str]
    received_at_utc: str
    priority_score: float
    priority_class: str
    priority_override_class: Optional[str]
    priority_override_reason: Optional[str]
    workflow_status: str
    discovery_status: str
    discovery_requested_at_utc: Optional[str]
    discovery_due_utc: Optional[str]
    discovery_requesting_party: Optional[str]
    open_examination_request_count: int
    released_examination_request_count: int
    accepted_at_utc: Optional[str]
    reported_at_utc: Optional[str]
    gross_turnaround_days: Optional[float]
    net_turnaround_days: Optional[float]
    rejection_reason: Optional[str]


class EvidenceItem(VersionedEntity, total=False):
    case_id: str
    item_number: str
    item_description: str
    item_type: str
    seal_intact: bool
    custody_status: str
    checkout_count: int
    logged_at_utc: str


class ExaminationRequest(VersionedEntity, total=False):
    case_id: str
    evidence_item_id: str
    method_id: str
    assigned_analyst_id: Optional[str]
    discipline: str
    item_count: int
    estimated_hours: float
    actual_hours_logged: Optional[float]
    status: str
    revision_round: int
    requested_at_utc: str
    released_at_utc: Optional[str]
    vendor_custody_days: float


class Assignment(VersionedEntity, total=False):
    examination_request_id: str
    analyst_id: str
    estimated_hours: float
    assignment_reason: str
    status: str
    superseded_by_assignment_id: Optional[str]
    assigned_at_utc: str
    closed_at_utc: Optional[str]


class ReviewRecord(ImmutableEntity, total=False):
    """A review record is immutable: no updated_at and no version."""

    examination_request_id: str
    reviewer_analyst_id: Optional[str]
    reviewer_operator_id: Optional[str]
    review_type: str
    decision: str
    rationale: str
    revision_round_snapshot: int
    recorded_at_utc: str


class ProficiencyTest(VersionedEntity, total=False):
    analyst_id: str
    method_id: str
    test_cycle: str
    due_utc: str
    status: str
    submitted_at_utc: Optional[str]
    score_pct: Optional[float]
    result: Optional[str]
    late_submission: bool
    scored_at_utc: Optional[str]


class Vendor(VersionedEntity, total=False):
    name: str
    accredited_disciplines: List[str]
    accreditation_expires_at_utc: str
    concurrent_case_capacity: int
    unit_price_cents: int
    rush_surcharge_pct: float
    contract_ceiling_cents: int
    encumbered_cents: int
    spent_cents: int
    status: str
    suspension_reason: Optional[str]


class VendorEngagement(VersionedEntity, total=False):
    examination_request_id: str
    vendor_id: str
    window_start_utc: str
    window_end_utc: str
    rush_flag: bool
    item_count: int
    base_amount_cents: int
    rush_surcharge_cents: int
    tier_basis_cents: int
    volume_discount_pct: float
    discount_amount_cents: int
    award_amount_cents: int
    final_invoice_cents: Optional[int]
    variance_cents: Optional[int]
    status: str
    awarded_at_utc: str
    shipped_at_utc: Optional[str]
    returned_at_utc: Optional[str]
    custody_days: Optional[float]
    cancellation_reason: Optional[str]


class Nonconformance(VersionedEntity, total=False):
    examination_request_id: Optional[str]
    analyst_id: Optional[str]
    source: str
    severity: str
    description: str
    status: str
    root_cause_category: Optional[str]
    corrective_action_plan: Optional[str]
    capa_rejection_count: int
    opened_at_utc: str
    due_utc: str
    closed_at_utc: Optional[str]
    overdue: bool


class CourtEvent(VersionedEntity, total=False):
    examination_request_id: str
    analyst_id: str
    court_name: str
    docket_number: str
    start_utc: str
    end_utc: str
    notice_days: int
    subpoena_received: bool
    status: str
    testimony_note: Optional[str]
    cancellation_reason: Optional[str]


class AnalystWorkload(TypedDict, total=False):
    """The workload projection read model of PRD §3.4."""

    analyst_id: str
    available_hours: float
    projected_load_hours: float
    projected_utilization_pct: float
    realized_load_hours: float
    realized_utilization_pct: float
    casework_training_ratio: float
    active_assignment_count: int
    assigned_casework_hours: float


class BacklogReport(TypedDict, total=False):
    """The backlog read model of PRD §3.9."""

    as_of_utc: str
    open_request_count: int
    backlog_index: float
    bucket_0_29_count: int
    bucket_30_59_count: int
    bucket_60_89_count: int
    bucket_90_plus_count: int
    p1_open_count: int
    outsourcing_recommended: bool


class LogicalClock(TypedDict):
    current_utc: str


JsonDict = Dict[str, Any]
