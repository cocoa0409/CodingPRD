"""TypedDict shapes for every persisted entity of the Comprehensive Plan Update API.

PRD section 2.4 splits the entities into two groups. Most rows carry `id`,
`created_at`, `updated_at` and `version`. Two rows are "configuration rather than
workflow and are deliberately exempt": a Venue "carries only id and created_at:
it has no updated_at and no version", and a ParticipationRecord "likewise carries
only id and created_at". VenueDict and ParticipationRecordDict therefore omit
`updated_at` and `version` on purpose — tests assert those keys are absent.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - Python version shim
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


class VersionedRow(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class ConfigRow(TypedDict):
    """id + created_at only — Venue and ParticipationRecord."""

    id: str
    created_at: str


class PlanUpdateDict(VersionedRow, total=False):
    title: str
    jurisdiction_code: str
    base_year: int
    horizon_year: int
    status: str
    state_review_status: str
    state_findings: Optional[str]
    adopted_scenario_id: Optional[str]
    adopted_at: Optional[str]
    compliance_posture: str
    resubmission_count: int
    open_consistency_link_count: int
    required_elements_complete_count: int
    housing_shortfall_total: int
    monitoring_on_track_count: int
    equity_share_pct: float
    participation_weight_total: float
    underrepresented_weight_total: float


class InventoryDatasetDict(VersionedRow, total=False):
    plan_update_id: str
    inventory_type: str
    status: str
    vintage_year: int
    record_count: Optional[int]
    vacant_acres: Optional[float]
    underutilized_acres: Optional[float]
    infrastructure_constrained_acres: Optional[float]
    allowed_density_units_per_acre: Optional[float]
    referencing_scenario_count: int
    authored_by_user_id: str
    certified_by_user_id: Optional[str]


class GrowthScenarioDict(VersionedRow, total=False):
    plan_update_id: str
    land_use_inventory_id: str
    label: str
    method: str
    horizon_year: int
    status: str
    base_households: int
    annual_household_growth_rate: float
    job_growth_total: int
    demolition_replacement_units: int
    capacity_variant: str
    land_capacity_units: int
    projected_demand_units: int
    capacity_gap_units: int


class HousingAllocationDict(VersionedRow, total=False):
    plan_update_id: str
    income_tier: str
    assigned_units: int
    cycle_deadline: str
    tier_capacity_units: int
    carryover_in_units: int
    accommodated_units: int
    shortfall_units: int


class PlanElementDict(VersionedRow, total=False):
    plan_update_id: str
    element_type: str
    title: str
    draft_body: str
    policy_count: int
    status: str
    consistency_status: str
    revision_round: int
    authored_by_user_id: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]


class ConsistencyLinkDict(VersionedRow, total=False):
    source_element_id: str
    target_element_id: str
    dependency_type: str
    status: str
    reconciliation_note: Optional[str]
    reconciled_by_user_id: Optional[str]
    staled_by_amendment_id: Optional[str]


class VenueDict(ConfigRow, total=False):
    name: str
    seated_capacity: int
    turnover_buffer_minutes: int
    ada_accessible: bool
    transit_served: bool


class EngagementActivityDict(VersionedRow, total=False):
    plan_update_id: str
    activity_type: str
    title: str
    venue_id: Optional[str]
    start_at: str
    end_at: str
    interpretation_offered: bool
    status: str
    weighting_variant: str
    record_count: int
    underrepresented_record_count: int
    total_weighted_count: float
    underrepresented_weighted_count: float
    equity_share_pct: float
    completed_at: Optional[str]
    cancellation_reason: Optional[str]


class ParticipationRecordDict(ConfigRow, total=False):
    activity_id: str
    respondent_ref: str
    demographic_group: str
    census_tract: str
    interpreter_used: bool
    comment_text: Optional[str]
    is_underrepresented: bool
    weight: float


class EnvironmentalReviewDict(VersionedRow, total=False):
    plan_update_id: str
    document_type: str
    title: str
    status: str
    alternative_count: int
    comment_period_days: Optional[int]
    circulated_at: Optional[str]
    comment_period_ends_at: Optional[str]
    preferred_alternative_id: Optional[str]
    certified_at: Optional[str]


class PlanAlternativeDict(VersionedRow, total=False):
    environmental_review_id: str
    label: str
    traffic_vmt_index: float
    ghg_index: float
    habitat_index: float
    water_index: float
    raw_impact_score: float
    mitigation_credit: float
    net_impact_score: float
    status: str


class HearingDict(VersionedRow, total=False):
    plan_update_id: str
    body_type: str
    scheduled_start: str
    scheduled_end: str
    notice_published_at: str
    status: str
    outcome: Optional[str]
    minutes_note: Optional[str]
    opened_at: Optional[str]
    closed_at: Optional[str]
    amendment_count: int
    adopted_amendment_count: int


class AmendmentDict(VersionedRow, total=False):
    hearing_id: str
    target_element_id: str
    summary: str
    policy_delta: int
    status: str
    element_version_at_proposal: int
    proposed_by_user_id: str
    applied_policy_count: Optional[int]
    prior_element_status: Optional[str]
    withdrawal_reason: Optional[str]
    rescission_reason: Optional[str]


class ImplementationActionDict(VersionedRow, total=False):
    plan_update_id: str
    source_element_id: str
    action_type: str
    title: str
    indicator_name: str
    indicator_direction: str
    baseline_value: float
    target_value: float
    status: str
    reading_count: int
    on_track: bool
    latest_reading_value: Optional[float]
    latest_reading_at: Optional[str]
    due_at: Optional[str]


class ComplianceSummaryDict(TypedDict, total=False):
    """The computed read of PRD section 2.11 — twelve fields, no id of its own."""

    plan_update_id: str
    compliance_posture: str
    state_review_status: str
    required_elements_complete_count: int
    missing_element_types: List[str]
    open_consistency_link_count: int
    housing_shortfall_total: int
    equity_share_pct: float
    land_capacity_units: int
    projected_demand_units: int
    capacity_gap_units: int
    monitoring_on_track_count: int


class ClockDict(TypedDict, total=False):
    current_utc: str


JsonDict = Dict[str, Any]
