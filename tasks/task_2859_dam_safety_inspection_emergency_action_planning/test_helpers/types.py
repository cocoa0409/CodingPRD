"""TypedDict shapes for the resources declared by the PRD.

These exist for editor/reader clarity in the test suite; the tests assert on
plain dicts returned by the API. Every field listed here is a field the PRD
declares on the corresponding resource.
"""

from __future__ import annotations

from typing import Any, Optional, TypedDict


class Envelope(TypedDict):
    meta: dict[str, Any]
    response_type: str
    data: Any


class ErrorPayload(TypedDict):
    error_id: str
    message: str


class Owner(TypedDict, total=False):
    id: str
    legal_name: str
    owner_type: str
    contact_email: str
    financial_assurance_bond_cents: int
    fee_balance_cents: int
    delinquency_status: str
    registered_dam_count: int
    created_at: str
    updated_at: str
    version: int


class Engineer(TypedDict, total=False):
    id: str
    full_name: str
    license_number: str
    license_expires_at: str
    certified_hazard_classes: list[str]
    license_status: str
    open_inspection_count: int
    created_at: str
    updated_at: str
    version: int


class RiverReach(TypedDict, total=False):
    id: str
    name: str
    channel_capacity_cfs: float
    downstream_community: str
    committed_release_cfs: float
    active_drawdown_count: int
    created_at: str
    updated_at: str
    version: int


class Dam(TypedDict, total=False):
    id: str
    owner_id: str
    river_reach_id: str
    name: str
    nid_code: str
    height_ft: float
    gross_storage_acre_ft: float
    crest_elevation_ft: float
    normal_pool_elevation_ft: float
    year_completed: int
    registered_at: str
    hazard_class: str
    safety_status: str
    regulatory_status: str
    current_consequence_score: Optional[float]
    eap_required: bool
    latest_eap_status: str
    next_inspection_due_at: str
    inspection_overdue: bool
    open_inspection_count: int
    open_deficiency_count: int
    deficiency_count: int
    committed_drawdown_acre_ft: float
    available_conservation_storage_acre_ft: float
    created_at: str
    updated_at: str
    version: int


class ConsequenceAssessment(TypedDict, total=False):
    id: str
    dam_id: str
    population_at_risk: int
    habitable_structures: int
    critical_facilities: int
    breach_peak_outflow_cfs: float
    breach_travel_time_minutes: float
    inundation_area_acres: float
    inundation_map_ref: str
    screening_score: Optional[float]
    recommended_hazard_class: Optional[str]
    certified_score: Optional[float]
    certified_hazard_class: Optional[str]
    status: str
    prepared_by_user_id: str
    certified_at: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    dam_id: str
    engineer_id: str
    inspection_type: str
    window_start: str
    window_end: str
    status: str
    performed_at: Optional[str]
    condition_rating: Optional[str]
    narrative: Optional[str]
    return_count: int
    return_reason: Optional[str]
    accepted_at: Optional[str]
    accepted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deficiency(TypedDict, total=False):
    id: str
    dam_id: str
    inspection_id: Optional[str]
    source: str
    category: str
    severity: str
    description: str
    status: str
    order_count: int
    remediation_due_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationOrder(TypedDict, total=False):
    id: str
    deficiency_id: str
    dam_id: str
    owner_id: str
    order_type: str
    requested_response_days: int
    effective_response_days: int
    issued_at: str
    compliance_deadline_at: str
    daily_penalty_rate_cents: int
    assessed_penalty_cents: int
    status: str
    corrective_action_summary: Optional[str]
    completed_at: Optional[str]
    response_filed_at: Optional[str]
    defaulted_at: Optional[str]
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyActionPlan(TypedDict, total=False):
    id: str
    dam_id: str
    version_label: str
    inundation_map_ref: str
    notification_flowchart_ref: str
    notification_contact_count: int
    drawdown_procedure_ref: str
    status: str
    review_findings: Optional[str]
    approved_at: Optional[str]
    expires_at: Optional[str]
    last_accepted_exercise_at: Optional[str]
    accepted_exercise_count: int
    exercise_current: bool
    created_at: str
    updated_at: str
    version: int


class EapExercise(TypedDict, total=False):
    """Append-only: the PRD gives this row only ``id`` and ``created_at``."""

    id: str
    eap_id: str
    exercise_type: str
    conducted_at: str
    participant_count: int
    notification_test_passed: bool
    outcome: str
    deficiency_reason: Optional[str]
    logged_by_user_id: str
    created_at: str


class Permit(TypedDict, total=False):
    id: str
    dam_id: str
    owner_id: str
    permit_type: str
    scope_description: str
    estimated_project_cost_cents: int
    proposed_start_date: str
    base_fee_cents: int
    engineering_review_fee_cents: int
    delinquency_surcharge_cents: int
    volume_credit_cents: int
    total_fee_cents: int
    status: str
    revision_count: int
    review_engineer_id: Optional[str]
    decision_findings: Optional[str]
    conditions: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HighWaterEvent(TypedDict, total=False):
    id: str
    dam_id: str
    declared_at: str
    trigger_description: str
    declared_inflow_cfs: float
    status: str
    reading_count: int
    current_alert_level: str
    peak_pool_elevation_ft: Optional[float]
    escalated_at: Optional[str]
    stood_down_at: Optional[str]
    final_pool_elevation_ft: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ElevationReading(TypedDict, total=False):
    """Append-only: the PRD gives this row only ``id`` and ``created_at``."""

    id: str
    high_water_event_id: str
    reading_at: str
    pool_elevation_ft: float
    observed_inflow_cfs: float
    freeboard_ft: float
    alert_level: str
    rising: bool
    recorded_by_user_id: str
    created_at: str


class DrawdownOrder(TypedDict, total=False):
    id: str
    dam_id: str
    river_reach_id: str
    high_water_event_id: str
    requested_release_cfs: float
    window_start: str
    window_end: str
    planned_release_acre_ft: float
    actual_release_acre_ft: Optional[float]
    status: str
    coordinated_at: Optional[str]
    activated_at: Optional[str]
    completed_at: Optional[str]
    cancelled_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeLedgerEntry(TypedDict, total=False):
    """Append-only: the PRD gives this row only ``id`` and ``created_at``."""

    id: str
    owner_id: str
    sequence_no: int
    entry_type: str
    amount_cents: int
    source_ref: Optional[str]
    memo: Optional[str]
    balance_after_cents: int
    posted_by_user_id: str
    created_at: str
