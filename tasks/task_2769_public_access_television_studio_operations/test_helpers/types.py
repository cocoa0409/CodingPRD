"""TypedDict shapes for the API resources described by the PRD.

Fields are declared ``total=False`` because assertions in the suite always
target the specific fields a PRD rule names, rather than requiring the whole
shape to be present.

Note on common fields: every resource carries ``id``, ``created_at``,
``updated_at`` and ``version`` except the attestation resource, which the PRD
declares append-only and therefore exposes only ``id`` and ``created_at`` --
never ``updated_at`` and never ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class Producer(TypedDict, total=False):
    id: str
    legal_name: str
    email: str
    residency_verified: bool
    status: str
    certification_level: str
    competency_codes: List[str]
    suspension_points: int
    indemnification_expires_at: Optional[str]
    deposit_held_cents: int
    deposit_forfeited_total_cents: int
    volunteer_hours_tenths: int
    confirmed_crew_commitments: int
    reinstated_count: int
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    tier: str
    grants_competency_codes: List[str]
    seat_capacity: int
    session_start_at: str
    session_end_at: str
    enrolled_count: int
    passed_count: int
    created_at: str
    updated_at: str
    version: int


class CourseEnrollment(TypedDict, total=False):
    id: str
    producer_id: str
    course_id: str
    status: str
    practical_score: Optional[int]
    attended_at: Optional[str]
    graded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Series(TypedDict, total=False):
    id: str
    producer_id: str
    title: str
    cadence: str
    first_air_date: str
    predecessor_series_id: Optional[str]
    sequence_number: int
    seniority_at: Optional[str]
    status: str
    hold_plan_slots_granted: int
    remaining_hold_slots: int
    missed_windows: int
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    producer_id: str
    series_id: Optional[str]
    title: str
    episode_number: Optional[int]
    runtime_seconds: int
    is_live: bool
    required_crew_roles: List[str]
    review_status: str
    clearance_status: str
    reviewed_by_user_id: Optional[str]
    finding_category: Optional[str]
    finding_notes: Optional[str]
    revision_round: int
    attestation_sequence_high: int
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Attestation(TypedDict, total=False):
    """Append-only resource: only ``id`` and ``created_at`` are ever emitted."""

    id: str
    program_id: str
    signed_by_producer_id: str
    attestation_kind: str
    statement_version: str
    third_party_material: bool
    license_reference: Optional[str]
    sequence_number: int
    effective_from: str
    effective_until: Optional[str]
    created_at: str


class Channel(TypedDict, total=False):
    id: str
    call_sign: str
    tier: str
    daily_window_start_minute: int
    daily_window_end_minute: int
    inter_program_buffer_seconds: int
    preemption_enabled: bool
    scheduled_seconds: int
    aired_seconds: int
    slot_sequence_high: int
    created_at: str
    updated_at: str
    version: int


class PlaybackSlot(TypedDict, total=False):
    id: str
    channel_id: str
    program_id: str
    series_id: Optional[str]
    booking_type: str
    start_at: str
    occupied_seconds: int
    end_at: str
    status: str
    required_crew_roles: List[str]
    staffing_status: str
    preempted_by_slot_id: Optional[str]
    measured_households: Optional[int]
    aired_at: Optional[str]
    sequence_number: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    slot_id: str
    volunteer_producer_id: str
    crew_role: str
    status: str
    credited_hours_tenths: int
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StudioResource(TypedDict, total=False):
    id: str
    resource_code: str
    resource_class: str
    required_competency_code: str
    capacity_slots: int
    turnaround_minutes: int
    base_deposit_cents: int
    replacement_value_cents: int
    status: str
    open_reservation_count: int
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    producer_id: str
    resource_id: str
    linked_slot_id: Optional[str]
    start_at: str
    end_at: str
    status: str
    risk_bp: int
    deposit_hold_cents: int
    late_fee_cents: int
    assessed_repair_cents: int
    deposit_forfeited_cents: int
    deposit_refunded_cents: int
    uncovered_liability_cents: int
    checked_out_at: Optional[str]
    returned_at: Optional[str]
    condition_notes: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageAssessment(TypedDict, total=False):
    id: str
    reservation_id: str
    severity: str
    repair_estimate_cents: int
    assessed_repair_cents: int
    suspension_points_assessed: int
    status: str
    filed_by_user_id: str
    waived_by_user_id: Optional[str]
    waiver_reason: Optional[str]
    damage_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingPeriod(TypedDict, total=False):
    id: str
    fiscal_year: int
    quarter: int
    basis: str
    gross_franchise_fee_cents: int
    service_period_earned_cents: int
    remittance_received_cents: int
    capital_grant_cents: int
    allocable_base_cents: int
    admin_reserve_cents: int
    capital_allocation_cents: int
    operating_allocation_cents: int
    total_program_funds_cents: int
    report_status: str
    revision_round: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ArchiveAsset(TypedDict, total=False):
    id: str
    program_id: str
    source_slot_id: str
    retention_class: Optional[str]
    retain_until: Optional[str]
    on_demand_status: str
    on_demand_views: int
    measured_households: int
    volunteer_hours_tenths: int
    community_impact_index: float
    impact_variant: str
    published_at: Optional[str]
    purged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


ApiResponse = Dict[str, Any]
