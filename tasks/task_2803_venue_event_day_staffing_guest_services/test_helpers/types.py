"""TypedDict shapes for the API resources.

Only SatisfactionResponse omits ``updated_at`` and ``version``: the PRD makes it
append-only, carrying its ``id`` and ``created_at`` alone.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Event(CommonFields):
    name: str
    event_date: str
    doors_open_at: str
    doors_close_at: str
    expected_attendance: int
    historical_actual_attendance: Optional[int]
    attendance_tier: str
    refund_budget_total_cents: int
    refund_approved_total_cents: int
    refund_budget_remaining_cents: int
    gratuity_pool_cents: int
    gratuity_allocated_cents: int
    status: str


class PositionType(CommonFields):
    code: str
    display_name: str
    base_hourly_rate_cents: int
    attendance_ratio_per_1000: float
    min_headcount: int
    required_certifications: List[str]
    is_tip_eligible: bool
    is_contracted_position: bool


class StaffingPlan(CommonFields):
    event_id: str
    plan_variant: str
    basis_attendance: int
    basis_attendance_tier: str
    revision_number: int
    total_required_headcount: int
    base_labor_cost_cents: int
    accessibility_surcharge_cents: int
    projected_labor_cost_cents: int
    activated_at: Optional[str]
    status: str


class PositionSlot(CommonFields):
    plan_id: str
    position_type_id: str
    zone_code: str
    shift_start: str
    shift_end: str
    shift_minutes: int
    ratio_derived_headcount: int
    required_headcount_override: Optional[int]
    required_headcount: int
    filled_headcount: int
    slot_labor_cost_cents: int
    status: str


class StaffMember(CommonFields):
    full_name: str
    employment_type: str
    seniority_date: str
    hourly_rate_cents: int
    in_backfill_pool: bool
    reliability_score: int
    season_reliability_score: int
    no_show_strikes: int
    completed_assignment_count: int
    last_status_reason: Optional[str]
    status: str


class Certification(CommonFields):
    staff_member_id: str
    cert_type: str
    issued_on: str
    expires_on: str
    revoked_at: Optional[str]
    status: str


class ShiftBid(CommonFields):
    staff_member_id: str
    position_slot_id: str
    submitted_at: str
    rank_score: Optional[int]
    decision_reason: Optional[str]
    decided_at: Optional[str]
    status: str


class StaffAssignment(CommonFields):
    position_slot_id: str
    staff_member_id: str
    shift_bid_id: Optional[str]
    source: str
    attendance_status: str
    payout_status: str
    check_in_at: Optional[str]
    checked_out_at: Optional[str]
    late_check_in: bool
    worked_minutes: Optional[int]
    base_pay_cents: int
    gratuity_cents: int
    total_payout_cents: int


class BackfillRequest(CommonFields):
    position_slot_id: str
    triggering_assignment_id: str
    attempt_count: int
    selected_staff_member_id: Optional[str]
    filled_assignment_id: Optional[str]
    cancel_reason: Optional[str]
    status: str


class GuestIssue(CommonFields):
    event_id: str
    channel: str
    category: str
    severity: str
    description: str
    seat_reference: Optional[str]
    reported_by_user_id: str
    assigned_staff_member_id: Optional[str]
    sla_minutes: int
    sla_clock_started_at: str
    sla_deadline: str
    sla_breached: bool
    resolution_type: Optional[str]
    relocation_zone_code: Optional[str]
    resolved_at: Optional[str]
    resolved_by_user_id: Optional[str]
    reopen_count: int
    escalated_from_issue_id: Optional[str]
    refund_status: str
    refund_requested_cents: int
    refund_approved_cents: int
    refund_requested_by_user_id: Optional[str]
    refund_decided_by_user_id: Optional[str]
    status: str


class AccessibilityResource(CommonFields):
    event_id: str
    resource_type: str
    zone_code: str
    unit_count: int
    peak_committed_units: int
    status: str


class AccessibilityRequest(CommonFields):
    resource_id: str
    guest_reference: str
    window_start: str
    window_end: str
    units_requested: int
    companion_seats_requested: int
    confirmed_at: Optional[str]
    service_started_at: Optional[str]
    completed_at: Optional[str]
    denial_reason: Optional[str]
    status: str


class SatisfactionResponse(TypedDict):
    """Append-only: no updated_at and no version."""

    id: str
    created_at: str
    event_id: str
    zone_code: str
    score: int
    comment: Optional[str]
    submitted_by_user_id: str


# A generic staffing context returned by the composite builders in fixtures.py.
StaffingContext = Dict[str, Any]
