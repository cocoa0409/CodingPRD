"""Typed shapes for every persisted resource the API returns.

Three resources are written once and never updated -- the vehicle owner, the
teardown finding and the parts delay event -- so they carry an `id` and a
`created_at` and nothing else from the common block: no `updated_at`, and no
`version`. Every other resource carries the full quartet.
"""

from typing import Any, Dict, List, Optional, TypedDict


class AppendOnlyCommon(TypedDict):
    """Identity block of a resource that is never updated."""

    id: str
    created_at: str


class MutableCommon(AppendOnlyCommon):
    """Identity block of a resource that can be updated and versioned."""

    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Standing registries
# ---------------------------------------------------------------------------
class Customer(AppendOnlyCommon):
    """A vehicle owner. Immutable once written, and therefore unversioned."""

    full_name: str
    phone: str
    email: str
    preferred_alternate_parts_ok: bool


class Insurer(MutableCommon):
    """An insurer program: policy flags, rate ceilings and negotiation limits."""

    insurer_code: str
    name: str
    aftermarket_allowed: bool
    recycled_allowed: bool
    reconditioned_allowed: bool
    alternate_parts_min_vehicle_age_years: int
    parts_price_ceiling_pct: float
    supplement_round_limit: int
    rate_ceiling_cents: Dict[str, int]


class PartsVendor(MutableCommon):
    """A parts supplier with its commercial terms and both performance scores."""

    name: str
    vendor_type: str
    part_types_offered: List[str]
    status: str
    discount_pct: float
    core_charge_cents: int
    restocking_fee_pct: float
    max_qty_per_line: int
    order_seq_counter: int
    fulfillment_score_rolling: int
    fulfillment_score_lifetime: int


class Stall(MutableCommon):
    """A production stall with its derived booked minutes."""

    name: str
    stall_type: str
    cleanup_buffer_minutes: int
    status: str
    booked_minutes: int


class CalibrationBay(MutableCommon):
    """An ADAS calibration bay with its derived scheduled-window count."""

    name: str
    supported_types: List[str]
    concurrent_capacity: int
    scheduled_window_count: int


# ---------------------------------------------------------------------------
# The repair order aggregate
# ---------------------------------------------------------------------------
class RepairOrder(MutableCommon):
    """Both state dimensions, every money field and the current version."""

    customer_id: str
    insurer_id: str
    claim_number: str
    vehicle_vin: str
    vehicle_model_year: int
    vehicle_make_model: str
    initial_authorized_cents: int
    deductible_cents: int

    stage: str
    authorization_posture: str
    consent_state: str
    consent_basis_cents: Optional[int]
    consent_alternate_parts: bool

    checkin_at: str
    delivered_at: Optional[str]
    blueprint_by_user_id: Optional[str]
    estimate_locked_at: Optional[str]
    total_loss_note: Optional[str]

    teardown_finding_count: int
    qc_inspection_count: int
    open_parts_delay_count: int

    refinish_hours_provisional: float
    refinish_hours_final: float
    approved_labor_hours: float

    labor_subtotal_cents: int
    parts_gross_cents: int
    parts_discount_cents: int
    parts_subtotal_cents: int
    betterment_cents: int
    supplies_fee_cents: int
    pre_tax_total_cents: int
    insurer_authorized_cents: int
    customer_pay_cents: int

    parts_ordered_gross_cents: int
    parts_committed_cents: int
    parts_return_credit_cents: int
    parts_restocking_loss_cents: int


class DamageLine(AppendOnlyCommon):
    """One teardown finding. Append-only, and therefore unversioned."""

    repair_order_id: str
    panel_code: str
    severity: str
    requires_blend: bool
    adas_component_touched: bool
    structural: bool
    discovered_at_stage: str


class EstimateLine(MutableCommon):
    """One labor operation with its allocation, effective rate and amount."""

    repair_order_id: str
    damage_line_id: Optional[str]
    supplement_id: Optional[str]
    operation_code: str
    labor_type: str
    guide_hours: float
    not_included_operation: bool
    justification_note: Optional[str]
    is_blend: bool
    is_adjacent_panel: bool
    two_stage: bool
    pay_type: str
    line_status: str
    allocated_hours: Optional[float]
    effective_rate_cents: Optional[int]
    line_amount_cents: Optional[int]


class PartsLine(MutableCommon):
    """One part with both state dimensions, the prices and the return ledger."""

    estimate_line_id: str
    vendor_id: Optional[str]
    part_number: str
    part_description: str
    part_type: str
    list_price_cents: int
    qty: int
    oem_upgrade: bool

    procurement_status: str
    authorization_status: str

    quote_round: int
    quoted_unit_price_cents: Optional[int]
    counter_unit_price_cents: Optional[int]
    unit_price_cents: Optional[int]
    unit_extended_cents: Optional[int]
    extended_price_cents: int

    vendor_order_seq: Optional[int]
    promised_eta: Optional[str]
    received_at: Optional[str]
    received_qty: int
    on_time: Optional[bool]
    returned_qty: int
    return_reason: Optional[str]
    restocking_fee_cents: int


class PartsDelayEvent(AppendOnlyCommon):
    """One supply interruption. Append-only, and therefore unversioned."""

    repair_order_id: str
    parts_line_id: str
    reason: str
    opened_at: str
    closed_at: Optional[str]
    delay_minutes: Optional[int]


class Supplement(MutableCommon):
    """One request back to the insurer, with its round count and amounts."""

    repair_order_id: str
    reason_code: str
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    round_count: int
    submitted_at: str
    decided_at: Optional[str]
    adjuster_note: Optional[str]
    info_request_note: Optional[str]


class ProcedureRecord(MutableCommon):
    """One researched procedure, its adherence flag and its calibration state."""

    repair_order_id: str
    procedure_code: str
    source: str
    operation_scope: str
    requires_calibration: bool
    calibration_type: str
    calibration_status: str
    adherence_documented: bool
    adherence_doc_ref: Optional[str]
    bay_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    post_scan_dtc_count: Optional[int]
    scan_report_ref: Optional[str]


class StageAssignment(MutableCommon):
    """One stall booking for one stage of one order."""

    repair_order_id: str
    stall_id: str
    stage: str
    window_start: str
    window_end: str
    occupied_minutes: int
    status: str


class QcInspection(MutableCommon):
    """One post-repair inspection, created directly in its final verdict."""

    repair_order_id: str
    inspector_user_id: str
    sequence_number: int
    checklist_passed: bool
    post_scan_dtc_count: int
    scan_report_ref: Optional[str]
    result: str
    failure_reason: Optional[str]
    warranty_certificate_number: Optional[str]
    warranty_expires_at: Optional[str]


# ---------------------------------------------------------------------------
# Computed reads
# ---------------------------------------------------------------------------
class CycleTime(TypedDict):
    """The computed cycle-time report. Nothing about it is persisted."""

    repair_order_id: str
    gross_minutes: int
    excluded_minutes: int
    net_touch_minutes: int
    supplement_wait_minutes: int
    parts_delay_minutes: int
    open_interval_count: int


class DelaySweepResult(TypedDict):
    """The answer of the late-parts sweep."""

    opened_count: int
    open_parts_delay_count: int


class ClockReading(TypedDict):
    """The answer of the logical clock endpoint."""

    current_utc: str


JsonDict = Dict[str, Any]
