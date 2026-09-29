"""Typed shapes for every response body the apparel rental API returns.

The three append-only event records (Inspection, FitFeedback, FeeLedgerEntry)
deliberately omit ``updated_at`` and ``version``: they are never mutated after
creation, so the requirements give them only ``id`` and ``created_at``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class ResponseMeta(TypedDict, total=False):
    total_count: int
    has_more: bool
    limit: int
    offset: int


class ErrorPayload(TypedDict):
    error_id: str
    message: str


class Envelope(TypedDict, total=False):
    meta: ResponseMeta
    response_type: str
    data: Any


# ---------------------------------------------------------------------------
# Mutable entities: id, created_at, updated_at, version
# ---------------------------------------------------------------------------


class MembershipPlan(TypedDict, total=False):
    id: str
    code: str
    name: str
    item_slots: int
    monthly_fee_cents: int
    monthly_swaps_allowed: int
    shipping_cadence_days: int
    waiver_monthly_fee_cents: int
    waiver_coverage_cents: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    repair_certified: bool
    photography_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Style(TypedDict, total=False):
    id: str
    style_code: str
    brand: str
    category: str
    retail_price_cents: int
    acquisition_cost_cents: int
    size_run: List[str]
    expected_rental_turns_per_unit: int
    planned_eol_value_cents: int
    forecast_monthly_requests: int
    avg_rental_days: int
    planned_depth_units: int
    floor_ready_unit_count: int
    active_unit_count: int
    required_depth_units: int
    depth_gap_units: int
    replenishment_flag: bool
    demand_score: int
    created_at: str
    updated_at: str
    version: int


class RentalUnit(TypedDict, total=False):
    id: str
    style_id: str
    unit_code: str
    size: str
    acquisition_cost_cents: int
    availability_state: str
    condition_state: str
    condition_grade: str
    turns_completed: int
    cumulative_servicing_cost_cents: int
    realized_revenue_cents: int
    quarantine_hold: bool
    last_returned_at: Optional[str]
    occupied_until_date: Optional[str]
    retired_at: Optional[str]
    retirement_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    membership_plan_id: str
    full_name: str
    email: str
    status: str
    waiver_active: bool
    waiver_coverage_used_cents: int
    outstanding_fee_cents: int
    late_return_count: int
    swaps_used_current_month: int
    units_out_count: int
    preferred_categories: List[str]
    size_profile: str
    fit_confidence_score: int
    damage_risk_score: int
    damage_risk_band: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    member_id: str
    style_id: str
    requested_size: str
    requested_start_date: str
    requested_end_date: str
    allocated_unit_id: Optional[str]
    state: str
    waitlist_position: Optional[int]
    is_swap: bool
    superseded_reservation_id: Optional[str]
    matched_at: Optional[str]
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    returned_at: Optional[str]
    rental_days: Optional[int]
    late_days: int
    late_fee_cents: int
    revenue_attributed_cents: int
    created_at: str
    updated_at: str
    version: int


class ShipmentLeg(TypedDict, total=False):
    id: str
    reservation_id: str
    member_id: str
    direction: str
    state: str
    carrier_reference: Optional[str]
    planned_ship_date: str
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    received_at: Optional[str]
    exception_count: int
    exception_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReverseLogisticsJob(TypedDict, total=False):
    id: str
    reservation_id: str
    rental_unit_id: str
    state: str
    inspecting_technician_id: Optional[str]
    cleaning_required: bool
    repair_required: bool
    condemned: bool
    repair_attempts: int
    servicing_cost_cents: int
    cleaning_completed_at: Optional[str]
    repair_completed_at: Optional[str]
    photographed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    reservation_id: str
    rental_unit_id: str
    member_id: str
    inspection_id: str
    severity: str
    state: str
    residual_value_cents: int
    gross_fee_cents: int
    waiver_applied_cents: int
    net_fee_cents: int
    assessed_at: Optional[str]
    charged_at: Optional[str]
    dispute_round: int
    dispute_reason: Optional[str]
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResaleListing(TypedDict, total=False):
    id: str
    rental_unit_id: str
    channel: str
    state: str
    markdown_step: int
    base_price_cents: int
    list_price_cents: int
    channel_fee_cents: int
    net_recovery_cents: int
    floor_adjusted: bool
    sale_price_cents: Optional[int]
    listed_at: str
    sold_at: Optional[str]
    supersedes_listing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only event records: id and created_at only
# ---------------------------------------------------------------------------


class Inspection(TypedDict, total=False):
    id: str
    job_id: str
    rental_unit_id: str
    technician_id: str
    attempt_index: int
    soil_level: str
    damage_severity: str
    condition_grade_after: str
    biohazard_flag: bool
    notes: Optional[str]
    created_at: str


class FitFeedback(TypedDict, total=False):
    id: str
    reservation_id: str
    member_id: str
    style_id: str
    fit_rating: str
    occasion_match_score: int
    keep_intent: bool
    comment: Optional[str]
    created_at: str


class FeeLedgerEntry(TypedDict, total=False):
    id: str
    member_id: str
    kind: str
    amount_cents: int
    direction: str
    balance_after_cents: int
    reservation_id: Optional[str]
    damage_claim_id: Optional[str]
    memo: Optional[str]
    created_at: str


# ---------------------------------------------------------------------------
# Computed reads
# ---------------------------------------------------------------------------


class PersonalizationSummary(TypedDict, total=False):
    member_id: str
    fit_confidence_score: int
    feedback_count: int
    keep_intent_count: int
    dominant_fit_rating: Optional[str]
    preferred_categories: List[str]
    size_profile: Optional[str]


class DamageRiskProfile(TypedDict, total=False):
    member_id: str
    variant: str
    claim_count: int
    severity_points: int
    late_return_count: int
    damage_risk_score: int
    damage_risk_band: str


class UnitEconomics(TypedDict, total=False):
    style_id: str
    variant: str
    unit_count: int
    avg_acquisition_cost_cents: int
    avg_revenue_per_unit_cents: int
    avg_servicing_cost_per_unit_cents: int
    avg_eol_value_cents: int
    avg_margin_per_unit_cents: int
    avg_margin_per_turn_cents: int


JsonDict = Dict[str, Any]
