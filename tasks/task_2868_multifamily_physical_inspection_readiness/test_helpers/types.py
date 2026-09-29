"""Typed dictionaries describing the twelve resource shapes and their payloads.

Field names are the PRD's field names verbatim so that both the request
payloads the factories build and the response bodies the assertions read use
one vocabulary.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing shim for older interpreters
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


Headers = Dict[str, str]
Payload = Dict[str, Any]
Json = Dict[str, Any]


class CommonFields(TypedDict, total=False):
    """The four properties every one of the twelve resource types carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class InspectionStandard(CommonFields, total=False):
    code: str
    name: str
    effective_date: str
    unit_weight_pct: float
    inside_weight_pct: float
    outside_weight_pct: float
    adoption_status: str
    adopted_at: Optional[str]
    superseded_at: Optional[str]
    defect_definition_count: int
    life_threatening_definition_count: int


class DefectDefinition(CommonFields, total=False):
    standard_id: str
    code: str
    name: str
    inspectable_area: str
    severity: str
    base_point_value: float
    correction_deadline_hours: int
    is_life_threatening: bool


class Property(CommonFields, total=False):
    name: str
    total_unit_count: int
    capital_reserve_cents: int
    owner_contact_email: str
    readiness_posture: str
    open_life_threatening_count: int
    overdue_life_threatening_count: int
    open_severe_count: int
    allocated_reserve_total_cents: int
    last_final_score: Optional[float]
    last_sweep_closed_at: Optional[str]


class Unit(CommonFields, total=False):
    property_id: str
    unit_number: str
    bedroom_count: int
    occupancy_status: str
    occupant_display_name: Optional[str]
    prior_deficiency_count: int
    open_deficiency_count: int


class SelfAssessmentSweep(CommonFields, total=False):
    property_id: str
    window_start: str
    window_end: str
    planned_area_scope: str
    status: str
    started_at: Optional[str]
    closed_at: Optional[str]
    generated_work_order_count: int
    verified_work_order_count: int
    void_work_order_count: int
    urgent_work_order_count: int
    closure_verified_rate: float


class WorkOrder(CommonFields, total=False):
    sweep_id: str
    deficiency_id: str
    repair_status: str
    verification_status: str
    priority_tier: str
    due_at: str
    completed_at: Optional[str]
    completed_by_user_id: Optional[str]
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    resolution_note: Optional[str]
    rejection_count: int
    void_reason: Optional[str]


class Inspection(CommonFields, total=False):
    property_id: str
    standard_id: str
    inspection_kind: str
    scheduled_start: str
    scheduled_end: str
    status: str
    drawn_at: Optional[str]
    started_at: Optional[str]
    scored_at: Optional[str]
    rescored_at: Optional[str]
    finalized_at: Optional[str]
    sample_tier_value: int
    sample_size: int
    inspected_unit_count: int
    refused_unit_count: int
    unit_area_points: float
    inside_area_points: float
    outside_area_points: float
    total_points_deducted: float
    life_threatening_count: int
    provisional_score: Optional[float]
    final_score: Optional[float]
    appeal_deadline_at: Optional[str]
    cap_required: bool
    cap_window_days: Optional[int]
    cap_due_at: Optional[str]
    followup_due_at: Optional[str]


class SampleSelection(CommonFields, total=False):
    inspection_id: str
    unit_id: str
    selection_rank: int
    selection_basis: str
    selection_status: str
    access_status: str
    replaced_selection_id: Optional[str]
    notice_method: Optional[str]
    notified_at: Optional[str]
    access_window_start: Optional[str]
    access_window_end: Optional[str]
    notice_lead_hours: Optional[float]
    access_recorded_at: Optional[str]
    refusal_reason: Optional[str]


class Deficiency(CommonFields, total=False):
    inspection_id: Optional[str]
    sweep_id: Optional[str]
    unit_id: Optional[str]
    defect_definition_id: str
    supersedes_deficiency_id: Optional[str]
    source: str
    inspectable_area: str
    severity: str
    status: str
    observed_at: str
    points_deducted: float
    recurrence_applied: bool
    correction_due_at: str
    corrected_at: Optional[str]
    verified_at: Optional[str]
    inspection_version_after_record: Optional[int]


class Appeal(CommonFields, total=False):
    inspection_id: str
    contested_deficiency_id: str
    appeal_type: str
    status: str
    rationale: str
    filed_at: str
    requested_point_adjustment: Optional[float]
    granted_point_adjustment: Optional[float]
    decided_at: Optional[str]
    reviewer_note: Optional[str]
    additional_evidence: Optional[str]
    resubmission_count: int


class CorrectiveActionPlan(CommonFields, total=False):
    inspection_id: str
    narrative: str
    total_estimated_cost_cents: int
    milestone_count: int
    target_completion_at: str
    submitted_at: str
    status: str
    decided_at: Optional[str]
    reviewer_note: Optional[str]
    revision_count: int
    follow_up_inspection_id: Optional[str]


class CapitalNeedItem(CommonFields, total=False):
    property_id: str
    defect_definition_id: str
    recurrence_basis: str
    recurrence_count: int
    priority_score: float
    allocation_rank: int
    allocated_reserve_cents: int
    computed_at: str


class PaginationMeta(TypedDict, total=False):
    limit: int
    offset: int
    total_count: int
    has_more: bool


__all__ = [
    "Headers",
    "Payload",
    "Json",
    "CommonFields",
    "InspectionStandard",
    "DefectDefinition",
    "Property",
    "Unit",
    "SelfAssessmentSweep",
    "WorkOrder",
    "Inspection",
    "SampleSelection",
    "Deficiency",
    "Appeal",
    "CorrectiveActionPlan",
    "CapitalNeedItem",
    "PaginationMeta",
    "Any",
    "Dict",
    "List",
    "Optional",
]
