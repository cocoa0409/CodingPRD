"""TypedDict shapes for every entity the API publishes.

The shapes exist so tests can name fields once and so the shape assertions in
``assertions.py`` can iterate the declared key sets. Twelve entities carry the
common properties ``id``, ``created_at``, ``updated_at`` and ``version``;
``ReadingLogEntry`` is the sole exception and carries only ``id`` and
``created_at``, which is exactly why it gets its own base class here.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four properties every entity but the reading log entry carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyFields(TypedDict):
    """The reduced property set of an append-only record."""

    id: str
    created_at: str


COMMON_FIELD_NAMES = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_FIELD_NAMES = ("id", "created_at")


class Branch(CommonFields):
    name: str
    branch_code: str
    overlapping_program_capacity: int
    per_program_fee_cap_cents: int
    programs_over_budget_count: int


class Room(CommonFields):
    branch_id: str
    room_name: str
    capacity_seats: int
    min_setup_minutes: int
    min_teardown_minutes: int
    accessibility_features: List[str]
    status: str


class Program(CommonFields):
    branch_id: str
    title: str
    age_group: str
    delivery_mode: str
    registration_policy: str
    start_utc: str
    end_utc: str
    attendance_target: int
    attendance_cap: int
    supply_sku: str
    supply_units_per_attendee: int
    materials_budget_cents: int
    presenter_fee_budget_cents: int
    challenge_id: Optional[str]
    partner_type: str
    partner_org_name: Optional[str]
    partner_insurance_expires_on: Optional[str]
    accessibility_accommodations: List[str]
    serves_minors: bool
    operational_status: str
    compliance_status: str
    registered_count: int
    registrant_references: List[str]
    confirmed_room_capacity: int
    supply_draw_lines: List[Dict[str, Any]]
    materials_available_cents: int
    materials_committed_cents: int
    materials_spent_cents: int
    presenter_fee_committed_cents: int
    presenter_fee_spent_cents: int
    budget_variance_cents: int
    budget_posture: str
    verified_registrant_attendance: Optional[int]
    drop_in_headcount: Optional[int]
    surveys_collected: Optional[int]
    gross_attendance: Optional[int]
    no_show_count: Optional[int]
    survey_response_rate_pct: Optional[float]
    attendance_attainment_funder_pct: Optional[float]
    attendance_attainment_internal_pct: Optional[float]
    closure_reason: Optional[str]


class RoomReservation(CommonFields):
    program_id: str
    room_id: str
    start_utc: str
    end_utc: str
    setup_minutes: int
    teardown_minutes: int
    occupancy_start_utc: str
    occupancy_end_utc: str
    effective_capacity_seats: int
    status: str


class Presenter(CommonFields):
    legal_name: str
    presenter_type: str
    insurance_certificate_expires_on: str
    quoted_fee_cents: int
    engagement_status: str
    screening_decision: str
    screening_status: str
    screening_tier: str
    screening_decided_on: Optional[str]
    screening_valid_until: Optional[str]
    executed_contract_count: int


class PresenterContract(CommonFields):
    presenter_id: str
    program_id: str
    round_trip_miles: int
    status: str
    negotiation_round: int
    offered_fee_cents: Optional[int]
    countered_fee_cents: Optional[int]
    agreed_fee_cents: Optional[int]
    travel_fee_cents: int
    escort_fee_cents: int
    insurance_rider_fee_cents: int
    weekend_premium_cents: int
    total_fee_cents: int
    kill_fee_cents: int
    offered_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]


class ReadingChallenge(CommonFields):
    name: str
    logging_method: str
    unit_label: str
    start_on: str
    end_on: str
    correction_policy: str
    status: str
    prize_budget_cents: int
    prize_available_cents: int
    prize_committed_cents: int
    prize_spent_cents: int
    prize_budget_posture: str
    prize_inventory_posture: str
    participant_count: int
    deferred_award_count: int


class IncentiveTier(CommonFields):
    challenge_id: str
    tier_index: int
    threshold_units: int
    prize_sku: str
    prize_units_per_participant: int
    award_count: int
    deferred_count: int


class Participant(CommonFields):
    challenge_id: str
    home_branch_id: str
    display_name: str
    age_band: str
    cumulative_units: int
    entry_count: int
    last_entry_on: Optional[str]
    eligible_tier_index: int
    awarded_tier_index: int


class ReadingLogEntry(AppendOnlyFields):
    """Append-only ledger row: no ``updated_at`` and no ``version``."""

    participant_id: str
    entry_type: str
    units: int
    units_delta: int
    logged_on: str
    source: Optional[str]
    corrected_entry_id: Optional[str]
    note: Optional[str]
    recorded_by_user_id: str


class InventoryLot(CommonFields):
    branch_id: str
    category: str
    sku: str
    description: Optional[str]
    unit_cost_cents: int
    quantity_procured: int
    quantity_available: int
    quantity_reserved: int
    quantity_issued: int
    reuse_pool: bool
    status: str


class TierAward(CommonFields):
    participant_id: str
    tier_id: str
    lot_id: Optional[str]
    units: int
    unit_cost_cents: int
    line_cost_cents: int
    transfer_surcharge_cents: int
    award_total_cents: int
    status: str


class SupplyDrawLine(TypedDict):
    lot_id: str
    units: int
    unit_cost_cents: int
    surcharge_cents: int
    line_total_cents: int


SUPPLY_DRAW_LINE_FIELDS = (
    "lot_id",
    "units",
    "unit_cost_cents",
    "surcharge_cents",
    "line_total_cents",
)
