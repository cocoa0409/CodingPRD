"""Structural descriptions of the resources the API returns.

These TypedDicts document the shape the PRD promises so that assertions can
be written against a named contract instead of bare string keys.  They are
declared ``total=False`` because tests routinely inspect a subset of a
payload.

Note the asymmetry the PRD sets up in section 2.4: a point-ledger entry is
append-only and therefore carries only ``id`` and ``created_at``, with no
``updated_at`` and no ``version``.  Every other resource carries all four
common properties.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ─── Common property groups ───────────────────────────────────────────────


class CommonProps(TypedDict, total=False):
    """id, created_at, updated_at and version, per PRD section 2.4."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyProps(TypedDict, total=False):
    """id and created_at only - the point-ledger entry's reduced set."""

    id: str
    created_at: str


# ─── Envelope shapes (PRD section 2.2) ────────────────────────────────────


class SuccessEnvelope(TypedDict, total=False):
    success: bool
    data: Any


class ErrorDetail(TypedDict, total=False):
    error_id: str
    message: str
    details: Optional[Dict[str, Any]]


class ErrorEnvelope(TypedDict, total=False):
    success: bool
    error: ErrorDetail


class PageMeta(TypedDict, total=False):
    total_count: int
    limit: int
    offset: int
    has_more: bool


class PaginatedEnvelope(TypedDict, total=False):
    success: bool
    data: List[Any]
    meta: PageMeta


# ─── Domain resources ─────────────────────────────────────────────────────


class Donor(CommonProps, total=False):
    full_name: str
    email: str
    alumni_status: str
    entity_type: str
    donor_status: str
    status_effective_date: Optional[str]
    household_partner_donor_id: Optional[str]
    season_ticket_first_cycle_year: Optional[int]
    season_ticket_seasons_purchased: int
    cumulative_giving_cents: int
    consecutive_giving_years: int
    provisional_points: float
    certified_base_points: float
    certified_points: float
    transferred_points_in: float
    transferred_points_out: float
    dispute_adjustment_points: float
    rank_position: Optional[int]
    pending_request_count: int


class Gift(CommonProps, total=False):
    donor_id: str
    gift_date: str
    cycle_year: int
    amount_cents: int
    designation: str
    gift_status: str
    counts_toward_points: bool
    settled_at: Optional[str]


class PointLedgerEntry(AppendOnlyProps, total=False):
    donor_id: str
    recalculation_id: str
    entry_type: str
    variant: str
    points: float
    basis_note: Optional[str]
    computed_at: str


class PointRecalculation(CommonProps, total=False):
    cycle_year: int
    cutoff_date: str
    dispute_window_end: str
    status: str
    initiated_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    donors_processed_count: int
    communication_sent_count: int
    certified_points_sum: float
    certified_at: Optional[str]


class PointDispute(CommonProps, total=False):
    donor_id: str
    recalculation_id: str
    claimed_points_delta: float
    basis_note: str
    status: str
    info_request_rounds: int
    reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    granted_points_delta: float
    decided_at: Optional[str]


class PointTransfer(CommonProps, total=False):
    source_donor_id: str
    recipient_donor_id: str
    basis: str
    points_amount: float
    status: str
    transfer_pct_cap: float
    max_transferable_points: float
    exception_required: bool
    exception_granted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    decision_note: Optional[str]
    reversed_at: Optional[str]


class RequirementHistoryRow(TypedDict, total=False):
    cycle_year: int
    per_seat_requirement_cents: int


class Section(CommonProps, total=False):
    section_code: str
    venue_code: str
    seat_capacity: int
    per_seat_requirement_cents: int
    required_points_per_seat: float
    requirement_history: List[RequirementHistoryRow]
    status: str
    renovation_status: str
    post_renovation_capacity: Optional[int]
    post_renovation_requirement_cents: Optional[int]
    reseating_recalculation_id: Optional[str]
    reseated_donor_count: int
    reseating_invoice_total_cents: int
    seat_row_count: int
    seats_available: int
    seats_committed_count: int
    decommissioned_seat_count: int
    assigned_seat_count: int
    underwater_seat_count: int
    pricing_posture: str


class Seat(CommonProps, total=False):
    section_id: str
    row_label: str
    seat_number: int
    seat_status: str
    max_concurrent_holds: int


class SeatAssignment(CommonProps, total=False):
    seat_id: str
    donor_id: str
    selection_slot_id: Optional[str]
    occupancy_status: str
    payment_status: str
    hold_start: str
    hold_end: str
    first_occupied_cycle_year: int
    pricing_mode: str
    grandfathered_requirement_cents: Optional[int]
    requirement_cents: int
    handling_fee_cents: int
    total_due_cents: int
    amount_paid_cents: int
    required_points: float
    points_at_pick: float
    eligibility_status: str
    release_reason: str


class SelectionEvent(CommonProps, total=False):
    recalculation_id: str
    event_type: str
    status: str
    window_start: str
    window_end: str
    slot_minutes: int
    slot_buffer_minutes: int
    eligible_donor_min_points: float
    published_slot_count: int
    scheduled_slot_count: int


class SelectionSlot(CommonProps, total=False):
    selection_event_id: str
    donor_id: str
    rank_at_publish: int
    slot_index: int
    slot_start: str
    slot_end: str
    slot_status: str


class RelocationRequest(CommonProps, total=False):
    donor_id: str
    current_seat_assignment_id: str
    target_section_id: str
    selection_event_id: str
    request_type: str
    status: str
    granted_seat_assignment_id: Optional[str]
    decision_note: Optional[str]


# ─── Computed reads ───────────────────────────────────────────────────────


class RetentionAnalysis(TypedDict, total=False):
    """The inline object returned by the retention-analysis computed read."""

    cycle_year: int
    donors_processed_count: int
    retained_donor_count: int
    new_donor_count: int
    lapsed_risk_donor_count: int
    retention_rate: float
    average_certified_points: float
    certified_points_sum: float


class PricingSensitivity(TypedDict, total=False):
    """The inline object returned by the pricing-sensitivity computed read."""

    section_code: str
    per_seat_requirement_cents: int
    required_points_per_seat: float
    assigned_seat_count: int
    underwater_seat_count: int
    underwater_ratio: float
    pricing_posture: str
    requirement_history: List[RequirementHistoryRow]
    recommended_requirement_cents: int


RETENTION_ANALYSIS_FIELDS = (
    "cycle_year",
    "donors_processed_count",
    "retained_donor_count",
    "new_donor_count",
    "lapsed_risk_donor_count",
    "retention_rate",
    "average_certified_points",
    "certified_points_sum",
)

PRICING_SENSITIVITY_FIELDS = (
    "section_code",
    "per_seat_requirement_cents",
    "required_points_per_seat",
    "assigned_seat_count",
    "underwater_seat_count",
    "underwater_ratio",
    "pricing_posture",
    "requirement_history",
    "recommended_requirement_cents",
)
