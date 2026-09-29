"""Domain types for the Dog Show Trials API: status enums, role enum, entity shapes.

Field names mirror the PRD exactly. `PerformanceRun` is the single append-only
resource: it exposes only `id` and `created_at`, with no `updated_at` and no
`version` (PRD 2.4).
"""

from enum import Enum
from typing import Dict, List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CLUB_OFFICER = "ClubOfficer"
    SANCTION_OFFICER = "SanctionOfficer"
    SHOW_SECRETARY = "ShowSecretary"
    JUDGE = "Judge"
    HANDLER = "Handler"
    REGISTRY_OFFICER = "RegistryOfficer"


ALL_ROLES = [r.value for r in UserRole]


# ─── Controlled vocabularies ──────────────────────────────────────────────────

class RegionCode(str, Enum):
    NE = "NE"
    SE = "SE"
    MW = "MW"
    WC = "WC"


class BreedGroupCode(str, Enum):
    SPORTING = "SPORTING"
    HOUND = "HOUND"
    WORKING = "WORKING"
    TERRIER = "TERRIER"
    TOY = "TOY"
    NON_SPORTING = "NON_SPORTING"
    HERDING = "HERDING"


class Discipline(str, Enum):
    AGILITY = "AGILITY"
    OBEDIENCE = "OBEDIENCE"
    RALLY = "RALLY"


class ClubSanctionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class JudgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROVISIONAL = "PROVISIONAL"
    SUSPENDED = "SUSPENDED"


class HandlerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ShowStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RESULTS_FILED = "RESULTS_FILED"


class ShowType(str, Enum):
    CONFORMATION = "CONFORMATION"
    PERFORMANCE = "PERFORMANCE"
    COMBINED = "COMBINED"


class PointsScale(str, Enum):
    SCALE_A = "SCALE_A"
    SCALE_B = "SCALE_B"


class ClassLevel(str, Enum):
    BREED = "BREED"
    GROUP = "GROUP"
    BEST_IN_SHOW = "BEST_IN_SHOW"
    PERFORMANCE = "PERFORMANCE"


class PanelRole(str, Enum):
    BREED_JUDGE = "BREED_JUDGE"
    GROUP_JUDGE = "GROUP_JUDGE"
    BIS_JUDGE = "BIS_JUDGE"
    PERFORMANCE_JUDGE = "PERFORMANCE_JUDGE"


class SlotStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"


class ClassStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class EntryStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    JUDGED = "JUDGED"
    ABSENT = "ABSENT"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class WelfareStatus(str, Enum):
    CLEAR = "CLEAR"
    SEASON_DECLARED = "SEASON_DECLARED"
    HEAT_HOLD = "HEAT_HOLD"


class EntrySource(str, Enum):
    HANDLER_SUBMITTED = "HANDLER_SUBMITTED"
    PROMOTION = "PROMOTION"


class FeeBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class DogSex(str, Enum):
    DOG = "DOG"
    BITCH = "BITCH"


class MeasurementStatus(str, Enum):
    UNMEASURED = "UNMEASURED"
    TEMP_CARD = "TEMP_CARD"
    PERMANENT_CARD = "PERMANENT_CARD"


class AdvisoryLevel(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class BlockStatus(str, Enum):
    PLANNED = "PLANNED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ProtestType(str, Enum):
    MEASUREMENT = "MEASUREMENT"
    ELIGIBILITY = "ELIGIBILITY"
    JUDGING_CONDUCT = "JUDGING_CONDUCT"
    WELFARE = "WELFARE"


class ResolutionCode(str, Enum):
    DISQUALIFY_ENTRY = "DISQUALIFY_ENTRY"
    VACATE_PLACEMENT = "VACATE_PLACEMENT"
    NO_ACTION = "NO_ACTION"
    WARNING = "WARNING"


class FilingStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED_INCOMPLETE = "REJECTED_INCOMPLETE"


class RunResult(str, Enum):
    QUALIFIED = "QUALIFIED"
    NQ = "NQ"
    ELIMINATED = "ELIMINATED"


class TitleCode(str, Enum):
    CH = "CH"
    AX = "AX"
    CD = "CD"
    RN = "RN"


class Attendance(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"


# ─── Entities carrying id + created_at + updated_at + version ─────────────────

class Club(TypedDict):
    id: str
    name: str
    club_code: str
    region_code: str
    sanction_status: str
    annual_event_allowance: int
    sanction_note: Optional[str]
    events_approved_count: int
    created_at: str
    updated_at: str
    version: int


class Show(TypedDict):
    id: str
    club_id: str
    show_name: str
    show_date: str
    show_type: str
    venue_name: str
    outdoor_venue: bool
    entry_open_at: str
    entry_close_at: str
    max_total_entries: int
    championship_points_scale: str
    status: str
    submitted_at: Optional[str]
    approved_by_user_id: Optional[str]
    approval_decided_at: Optional[str]
    return_reason: Optional[str]
    revision_count: int
    armband_high_water: int
    confirmed_entry_count: int
    fee_charged_cents: int
    fee_refunded_cents: int
    fee_retained_cents: int
    fee_collected_cents: int
    levy_total_cents: int
    fee_assessment_delta_cents: int
    points_awarded_total: int
    temperature_reading_count: int
    current_heat_index_c: Optional[float]
    current_advisory_level: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict):
    id: str
    judge_number: str
    full_name: str
    home_region_code: str
    approved_breed_group_codes: List[str]
    approved_performance_disciplines: List[str]
    max_daily_dog_count: int
    status: str
    confirmed_slot_count: int
    created_at: str
    updated_at: str
    version: int


class JudgePanelSlot(TypedDict):
    id: str
    show_id: str
    judge_id: str
    panel_role: str
    slot_status: str
    responded_at: Optional[str]
    decline_reason: Optional[str]
    assigned_class_count: int
    assigned_dog_capacity: int
    created_at: str
    updated_at: str
    version: int


class ShowClass(TypedDict):
    id: str
    show_id: str
    class_code: str
    class_level: str
    breed_code: Optional[str]
    group_code: Optional[str]
    discipline: Optional[str]
    jump_height_cm: Optional[int]
    entry_limit: int
    parent_class_id: Optional[str]
    points_scale_override: Optional[str]
    assigned_slot_id: Optional[str]
    status: str
    entry_count: int
    present_count: int
    counted_dog_count: int
    base_points: int
    final_assessment_done: bool
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Handler(TypedDict):
    id: str
    handler_name: str
    member_number: str
    region_code: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dog(TypedDict):
    id: str
    registration_number: str
    call_name: str
    breed_code: str
    group_code: str
    sex: str
    birth_date: str
    owner_handler_id: str
    measurement_status: str
    measured_height_cm: Optional[float]
    championship_points_total: int
    majors_count: int
    qualifying_leg_counts: Dict[str, int]
    title_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class Entry(TypedDict):
    id: str
    show_id: str
    class_id: str
    dog_id: str
    handler_id: str
    entry_status: str
    welfare_status: str
    source: str
    promoted_from_entry_id: Optional[str]
    armband_number: Optional[int]
    entry_fee_cents: int
    levy_cents: int
    fee_refunded_cents: int
    net_fee_cents: int
    fee_basis: Optional[str]
    conflict_deferred: bool
    placement: Optional[int]
    points_awarded: int
    created_at: str
    updated_at: str
    version: int


class RingBlock(TypedDict):
    id: str
    show_id: str
    class_id: str
    slot_id: str
    ring_number: int
    block_start_at: str
    block_end_at: str
    block_status: str
    scheduled_dog_count: int
    deferred_dog_count: int
    conflict_free_minutes: int
    judging_minutes_estimate: int
    superseded_block_id: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict):
    id: str
    show_id: str
    entry_id: str
    filed_by_handler_id: str
    protest_type: str
    statement: str
    deposit_cents: int
    status: str
    review_round: int
    evidence_request: Optional[str]
    evidence_note: Optional[str]
    resolution_code: Optional[str]
    reviewed_by_user_id: Optional[str]
    decided_at: Optional[str]
    deposit_refunded: bool
    created_at: str
    updated_at: str
    version: int


class RegistryFiling(TypedDict):
    id: str
    show_id: str
    filing_status: str
    filed_at: str
    adjudicated_at: Optional[str]
    reject_reason: Optional[str]
    championship_points_total_filed: int
    title_records_count: int
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity: id + created_at only, no updated_at, no version ──────

class PerformanceRun(TypedDict):
    id: str
    entry_id: str
    discipline: str
    course_yardage_m: float
    standard_course_time_s: float
    actual_time_s: float
    faults_count: int
    refusals_count: int
    obedience_deductions: float
    time_faults: float
    total_faults: float
    final_score: float
    run_result: str
    title_leg_awarded: bool
    created_at: str
