"""TypedDicts for the registry, department, and water-domain resources.

All of these resources carry the common fields (``id``, ``created_at``,
``updated_at``, ``version``). Nullable fields are typed ``Optional``.
"""
from typing import Optional
from typing import TypedDict


class Community(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    state_code: str
    population: int
    area_sq_miles: float
    rural_area_pct: float
    comms_operators_on_duty_min: int
    comms_avg_alarm_to_dispatch_seconds: int
    comms_redundant_circuits: bool
    comms_backup_power: bool
    comms_attested: bool
    comms_attested_by: Optional[str]
    comms_attested_at: Optional[str]
    status: str
    current_class_number: Optional[int]
    current_split_class: Optional[int]
    current_premium_modifier: Optional[float]
    bound_exposure_cents: int
    next_evaluation_due_date: Optional[str]


class EvaluationCycle(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_id: str
    cycle_number: int
    field_analyst_id: str
    scheduled_open_date: str
    data_freeze_date: str
    status: str
    opened_at: Optional[str]


class FireDepartment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_id: str
    dept_type: str
    stations_active_count: int
    career_on_duty_per_shift: int
    volunteers_on_duty_avg: float
    training_hours_per_firefighter_annual: float
    training_facility_level: str
    live_fire_training: bool
    coverage_pct_within_5mi: float
    data_submitted: bool


class Apparatus(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    department_id: str
    kind: str
    pump_capacity_gpm: Optional[int]
    tank_capacity_gal: Optional[int]
    ladder_height_ft: Optional[int]
    status: str


class WaterSupplySystem(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_id: str
    needed_fire_flow_gpm: int
    storage_capacity_gal: int
    supply_works_capacity_gpm: int
    daily_consumption_gpm: int
    alternate_shuttle_capacity_gpm: int
    alternate_sites_count: int
    alternate_verified: bool
    active_certified_flow_gpm: float
    creditworthy_hydrant_count: int


class Hydrant(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    system_id: str
    location_descriptor: str
    status: str
    max_flow_gpm: Optional[int]
    last_certified_test_date: Optional[str]


class FlowTest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    system_id: str
    hydrant_id: str
    supersedes_test_id: Optional[str]
    test_date: str
    static_psi: float
    residual_psi: float
    measured_flow_gpm: float
    flow_at_20psi_gpm: Optional[int]
    status: str
    witnessed_by: Optional[str]
    certified_by: Optional[str]
    correction_reason: Optional[str]
