"""TypedDict shapes for every resource the wind-ops API returns.

Every resource carries the four common fields ``id``, ``created_at``,
``updated_at`` and ``version``.  All keys are declared optional so that a test
may bind a partially-projected row without a type error; the shapes exist to
document the contract and to give editors something to complete against.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict, total=False):
    """Fields present on every resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


class WindFarm(CommonFields, total=False):
    name: str
    region_code: str
    grid_operator_code: str
    road_levy_pct: float
    community_levy_pct: float
    landowner_budget_cap_cents: int
    turbine_count: int
    installed_capacity_kw: float
    opex_accrued_cents: int
    landowner_payable_cents: int
    road_maintenance_reserve_cents: int
    community_fund_balance_cents: int
    maintenance_spend_cents: int


class TurbineModel(CommonFields, total=False):
    model_code: str
    rated_power_kw: float
    hub_height_m: float
    rotor_diameter_m: float
    service_interval_hours: float
    service_interval_tolerance_hours: float
    gearbox_lead_time_days: int
    blade_lead_time_days: int
    generator_lead_time_days: int


class Turbine(CommonFields, total=False):
    wind_farm_id: str
    turbine_model_id: str
    asset_tag: str
    commissioning_date: str
    expected_kwh_per_hour: float
    availability_state: str
    curtailment_state: str
    operating_hours: float
    last_service_operating_hours: float
    service_due_operating_hours: float
    service_due_flag: bool
    service_interval_breached: bool
    active_fault_code: Optional[str]
    remote_reset_count_24h: int
    reset_window_start_utc: Optional[str]
    active_curtailment_count: int
    effective_power_limit_kw: float
    cumulative_lost_energy_kwh: float
    counted_downtime_hours_period: float
    period_actual_energy_kwh: float
    period_potential_energy_kwh: float


class FaultCodeRule(CommonFields, total=False):
    fault_code: str
    severity_class: str
    max_remote_resets_per_24h: int
    requires_dispatch: bool
    contractual_exclusion: bool


class FaultEvent(CommonFields, total=False):
    turbine_id: str
    fault_code_rule_id: str
    fault_code: str
    triage_state: str
    raised_at: str
    cleared_at: Optional[str]
    severity_class_pinned: str
    max_remote_resets_pinned: int
    requires_dispatch_pinned: bool
    contractual_exclusion_pinned: bool
    fault_code_rule_version_pinned: int
    reset_attempt_count: int
    downtime_hours: Optional[float]
    lost_energy_kwh: Optional[float]


class Crew(CommonFields, total=False):
    wind_farm_id: str
    crew_code: str
    technician_count: int
    certifications: List[str]
    max_work_wind_speed_ms: float
    daily_hours_capacity: float
    hourly_rate_cents: int
    status: str


class WeatherWindow(CommonFields, total=False):
    wind_farm_id: str
    start_utc: str
    end_utc: str
    forecast_wind_speed_ms: float
    forecast_gust_ms: float
    icing_risk: bool
    state: str
    active_work_order_count: int


class WorkOrder(CommonFields, total=False):
    turbine_id: str
    fault_event_id: Optional[str]
    blade_damage_id: Optional[str]
    parent_work_order_id: Optional[str]
    crew_id: Optional[str]
    weather_window_id: Optional[str]
    work_type: str
    required_certification: str
    estimated_hours: float
    actual_hours: Optional[float]
    state: str
    revision_round: int
    submitted_by_user_id: Optional[str]
    planned_start_utc: Optional[str]
    planned_end_utc: Optional[str]
    priority_score: float
    labor_cost_cents: Optional[int]


class CraneMobilization(CommonFields, total=False):
    wind_farm_id: str
    crane_class: str
    mobilization_start_utc: str
    demobilization_end_utc: str
    day_rate_cents: int
    mobilization_fee_cents: int
    max_lift_wind_speed_ms: float
    state: str
    reserved_replacement_count: int
    lift_days: int
    standby_days: int
    billable_days: int
    subtotal_cents: int
    volume_credit_cents: int
    total_crane_cost_cents: int


class SparePart(CommonFields, total=False):
    component_type: str
    part_number: str
    quantity_on_hand: int
    quantity_reserved: int
    quantity_consumed: int
    total_units_accounted: int
    lead_time_days: int
    reorder_point: int
    unit_cost_cents: int
    uptower_repairable: bool
    status: str
    procurement_flag: bool


class ComponentReplacement(CommonFields, total=False):
    work_order_id: str
    spare_part_id: str
    crane_mobilization_id: Optional[str]
    component_type: str
    estimated_lift_hours: float
    uptower_labor_hours: Optional[float]
    execution_path: Optional[str]
    state: str
    allocated_crane_cost_cents: int


class BladeDamage(CommonFields, total=False):
    turbine_id: str
    inspection_method: str
    blade_position: str
    inspected_at: str
    recorded_by_user_id: str
    damage_category: int
    damage_type: str
    chord_position_pct: float
    damage_length_mm: float
    exposed_area_cm2: float
    severity_score: Optional[float]
    repair_priority_band: Optional[str]
    repair_due_days: Optional[int]
    state: str
    waiver_rationale: Optional[str]


class ServiceAgreement(CommonFields, total=False):
    wind_farm_id: str
    guaranteed_availability_pct: float
    availability_basis: str
    lda_rate_cents_per_pct_point: int
    lda_cap_cents: int
    period_start_utc: str
    period_end_utc: str
    time_based_availability_pct: Optional[float]
    energy_based_availability_pct: Optional[float]
    assessed_lda_cents: int
    projected_shortfall_pct: float
    at_risk_flag: bool
    state: str


class CurtailmentOrder(CommonFields, total=False):
    turbine_id: str
    reason: str
    compensable: bool
    start_utc: str
    end_utc: str
    power_limit_kw: float
    deemed_kwh_per_hour: float
    state: str
    curtailed_hours: float
    lost_energy_kwh: float


class LandownerSettlement(CommonFields, total=False):
    wind_farm_id: str
    parcel_code: str
    royalty_basis: str
    period_start_utc: str
    period_end_utc: str
    royalty_pct: float
    minimum_payment_cents: int
    energy_price_cents_per_kwh: float
    road_damage_assessment_cents: int
    metered_kwh: float
    deemed_kwh: float
    royalty_cents: int
    payment_cents: int
    road_levy_cents: int
    community_levy_cents: int
    state: str
    void_reason: Optional[str]


#: Loose alias for a list-endpoint ``meta`` block.
ListMeta = Dict[str, Any]
