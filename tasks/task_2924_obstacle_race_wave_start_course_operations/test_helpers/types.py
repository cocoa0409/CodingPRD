"""Response shapes, as PRD §2.4 and §3 declare them.

`Division` and `ObstacleAttempt` deliberately omit `updated_at` and `version`:
PRD §2.4 states that for those two entity types "`updated_at` and `version` are
absent from the response body entirely; only `id` and `created_at` are
present". Every other resource inherits `_Versioned`.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is not needed on 3.11+
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore

JsonDict = Dict[str, Any]
Headers = Dict[str, str]


class _Immutable(TypedDict):
    id: str
    created_at: str


class _Versioned(_Immutable):
    updated_at: str
    version: int


class Venue(_Versioned, total=False):
    name: str
    terrain_type: str
    water_access: str
    land_use_zone: str
    protected_acreage_sqm: int
    restoration_bond_cents: int
    site_posture: str
    disturbed_area_sqm: int
    bond_released_cents: int
    bond_forfeited_cents: int
    bond_held_cents: int


class LandUsePermit(_Versioned, total=False):
    venue_id: str
    permit_number: str
    water_use_allowed: bool
    max_disturbed_area_sqm: int
    quiet_hours_start_hour_utc: int
    quiet_hours_end_hour_utc: int
    valid_until_utc: str
    restoration_deadline_utc: str
    status: str
    revision_rounds: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]


class Course(_Versioned, total=False):
    venue_id: str
    name: str
    total_distance_m: int
    corral_release_rate_per_min: float
    corral_throughput_capacity: int
    status: str
    readiness_posture: str
    obstacle_count: int
    difficulty_progression_score: float
    design_capacity_pph: int
    bottleneck_capacity_pph: int
    medic_headcount: int
    water_safety_headcount: int
    scheduled_capacity_total: int


class Obstacle(_Versioned, total=False):
    course_id: str
    name: str
    station_index: int
    difficulty_rating: int
    lane_count: int
    service_rate_per_min: float
    marshals_required: int
    footprint_sqm: int
    water_contact: bool
    bypass_mode: str
    penalty_seconds: int
    paired_obstacle_id: Optional[str]
    confirmed_marshal_count: int
    staffing_state: str
    design_clearance_rate_per_min: float
    effective_clearance_rate_per_min: float


class Division(_Immutable, total=False):
    name: str
    division_type: str
    bypass_policy: str
    scoring_mode: str
    min_age: int
    team_size_min: int
    team_size_max: int


class Wave(_Versioned, total=False):
    course_id: str
    division_id: str
    wave_code: str
    scheduled_start_utc: str
    capacity: int
    release_status: str
    roster_status: str
    assigned_count: int
    hold_reason: Optional[str]
    actual_start_utc: Optional[str]
    closed_at_utc: Optional[str]


class Participant(_Versioned, total=False):
    full_name: str
    birth_year: int
    email: str
    chip_id: str
    waiver_signed: bool
    clearance_status: str
    medical_flags: List[str]


class Entry(_Versioned, total=False):
    wave_id: str
    participant_id: str
    bib_number: int
    team_code: Optional[str]
    progress_status: str
    result_status: str
    bag_tag_code: Optional[str]
    chip_start_offset_seconds: int
    chip_start_utc: Optional[str]
    finish_recorded_utc: Optional[str]
    provisional_penalty_seconds: int
    official_penalty_seconds: int
    provisional_elapsed_seconds: Optional[int]
    official_elapsed_seconds: Optional[int]
    disputed_attempt_id: Optional[str]
    protest_rounds: int
    voided_attempt_ids: List[str]
    dq_reason: Optional[str]


class ObstacleAttempt(_Immutable, total=False):
    entry_id: str
    obstacle_id: str
    outcome: str
    provisional_penalty_seconds: int
    obstacle_staffing_state_at_record: str
    recorded_at: str
    recorded_by_user_id: str
    recorded_by_role: str


class StaffAssignment(_Versioned, total=False):
    course_id: str
    obstacle_id: Optional[str]
    staff_person_id: str
    staff_role: str
    certification_level: str
    shift_start_utc: str
    shift_end_utc: str
    status: str
    vacate_reason: Optional[str]


class FestivalService(_Versioned, total=False):
    venue_id: str
    service_type: str
    footprint_sqm: int
    capacity: int
    water_draw_lpm: int
    status: str


class RestorationTask(_Versioned, total=False):
    venue_id: str
    task_type: str
    area_sqm: int
    status: str
    bond_release_cents: int
    inspection_rounds: int
    findings_note: Optional[str]


class ClockReading(TypedDict, total=False):
    """PRD §2.5: the clock response is not an envelope-wrapped entity."""

    current_utc: str
    expired_permit_ids: List[str]
