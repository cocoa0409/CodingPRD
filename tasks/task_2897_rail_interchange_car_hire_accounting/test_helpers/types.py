"""TypedDict shapes for the rail interchange car hire accounting API.

Only ``Railroad``, ``Junction``, ``Car``, ``CarHireMovement``, ``ReclaimClaim``,
``EmbargoOrder``, ``RepairBill``, ``SettlementCycle``, ``Dispute`` and
``CorrectionRequest`` carry the full common-field block (``id``, ``created_at``,
``updated_at``, ``version``).  ``CarType``, ``InterchangeEvent`` and
``HireLedgerEntry`` carry only ``id`` and ``created_at`` -- they have no
``updated_at`` and no ``version``.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing_extensions is optional
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore

Json = Dict[str, Any]
JsonList = List[Json]


class Envelope(TypedDict, total=False):
    response_type: str
    data: Any
    meta: Json


class Meta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    total_count: int
    has_more: bool
    limit: int
    offset: int


class VersionedRow(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int


class UnversionedRow(TypedDict, total=False):
    """Rows declared without the common-field block: only id and created_at."""

    id: str
    created_at: str


class Railroad(VersionedRow, total=False):
    reporting_mark: str
    name: str
    status: str
    per_diem_credit_limit_cents: int
    per_diem_exposure_cents: int
    foreign_car_balance: int
    owned_car_count: int


class CarType(UnversionedRow, total=False):
    car_type_code: str
    description: str
    time_component_mode: str
    per_diem_rate_cents: Optional[int]
    tier2_threshold_days: Optional[int]
    tier2_per_diem_rate_cents: Optional[int]
    hourly_rate_cents: Optional[int]
    free_time_hours: int
    mileage_rate_millicents_per_mile: int
    loaded_mileage_only: bool


class Junction(VersionedRow, total=False):
    junction_code: str
    name: str
    road_a_id: str
    road_b_id: str
    status: str


class Car(VersionedRow, total=False):
    car_mark: str
    car_type_id: str
    owner_road_id: str
    current_handling_road_id: str
    custody_status: str
    mechanical_status: str
    routing_status: str
    prescribed_return_junction_id: Optional[str]
    obligation_issued_at: Optional[str]
    obligation_due_at: Optional[str]
    bad_order_since: Optional[str]
    bad_order_cleared_at: Optional[str]
    cumulative_mileage: int


class InterchangeEvent(UnversionedRow, total=False):
    car_id: str
    junction_id: str
    event_type: str
    delivering_road_id: str
    receiving_road_id: str
    interchange_at: str
    odometer_miles: int
    load_status: str
    status: str
    source: str
    recorded_by_road_id: str
    corrects_event_id: Optional[str]


class CarHireMovement(VersionedRow, total=False):
    car_id: str
    handling_road_id: str
    owner_road_id: str
    received_event_id: Optional[str]
    delivered_event_id: Optional[str]
    status: str
    start_at: str
    end_at: Optional[str]
    start_odometer_miles: int
    end_odometer_miles: Optional[int]
    load_status: str
    hire_liable: bool
    elapsed_hours: Optional[float]
    chargeable_hours: Optional[float]
    chargeable_days: Optional[int]
    time_component_cents: Optional[int]
    mileage_component_cents: Optional[int]
    gross_hire_cents: Optional[int]
    reclaim_credit_cents: int
    reverse_route_penalty_cents: int
    net_hire_cents: Optional[int]
    adjusted_net_hire_cents: Optional[int]
    bad_order_from: Optional[str]
    bad_order_to: Optional[str]
    reclaim_locked: bool
    settlement_cycle_id: Optional[str]
    recompute_count: int


class ReclaimClaim(VersionedRow, total=False):
    movement_id: str
    filed_by_road_id: str
    against_road_id: str
    reason: str
    window_from: str
    window_to: str
    claimed_hours: float
    allowed_hours: Optional[float]
    split_pct_applied: Optional[float]
    credit_cents: int
    status: str
    decided_at: Optional[str]
    supporting_embargo_id: Optional[str]
    detention_notified_at: Optional[str]
    filing_note: Optional[str]
    decision_note: Optional[str]
    disallow_reason: Optional[str]


class EmbargoOrder(VersionedRow, total=False):
    issuing_road_id: str
    junction_id: str
    car_type_id: Optional[str]
    effective_from: str
    effective_to: str
    reason: str
    status: str
    lifted_at: Optional[str]


class RepairBill(VersionedRow, total=False):
    car_id: str
    billing_road_id: str
    responsible_road_id: Optional[str]
    responsibility_rule_applied: Optional[str]
    defect_code: str
    defect_class: str
    defect_occurred_at: str
    labor_hours: float
    material_cents: int
    labor_cents: int
    subtotal_cents: int
    handling_fee_cents: int
    total_cents: int
    status: str
    counter_round: int
    counter_amount_cents: Optional[int]
    accepted_at: Optional[str]
    settled_at: Optional[str]
    settlement_cycle_id: Optional[str]


class SettlementCycle(VersionedRow, total=False):
    payer_road_id: str
    payee_road_id: str
    period_month: str
    period_start_at: str
    period_end_at: str
    status: str
    variant_applied: Optional[str]
    movement_line_count: int
    gross_hire_cents: int
    reclaim_credit_cents: int
    penalty_cents: int
    repair_charge_cents: int
    dispute_adjustment_cents: int
    pre_fee_net_cents: int
    clearinghouse_fee_cents: int
    net_settlement_cents: int
    as_reported_net_cents: Optional[int]
    reconciled_net_cents: Optional[int]
    computed_at: Optional[str]
    exchanged_at: Optional[str]
    settled_at: Optional[str]
    reopened_at: Optional[str]
    archived_at: Optional[str]
    dispute_deadline_at: Optional[str]
    reopen_deadline_at: Optional[str]
    reopen_count: int


class Dispute(VersionedRow, total=False):
    settlement_cycle_id: str
    filed_by_road_id: str
    respondent_road_id: str
    dispute_reason: str
    disputed_amount_cents: int
    movement_id: Optional[str]
    repair_bill_id: Optional[str]
    subject_net_at_filing_cents: int
    status: str
    round_number: int
    counter_amount_cents: Optional[int]
    resolution_amount_cents: Optional[int]
    resolved_at: Optional[str]
    last_action_at: Optional[str]
    filing_note: Optional[str]


class CorrectionRequest(VersionedRow, total=False):
    car_id: str
    junction_id: str
    target_event_id: Optional[str]
    resulting_event_id: Optional[str]
    correction_type: str
    filed_by_road_id: str
    counterparty_road_id: str
    status: str
    direction: Optional[str]
    proposed_interchange_at: Optional[str]
    proposed_odometer_miles: Optional[int]
    proposed_load_status: Optional[str]
    filing_note: Optional[str]
    confirm_note: Optional[str]
    rejection_reason: Optional[str]
    confirm_deadline_at: str
    confirmed_at: Optional[str]
    applied_at: Optional[str]
    expired_at: Optional[str]
    rejected_at: Optional[str]


class HireLedgerEntry(UnversionedRow, total=False):
    entry_type: str
    amount_cents: int
    debit_road_id: str
    credit_road_id: str
    movement_id: Optional[str]
    reclaim_claim_id: Optional[str]
    repair_bill_id: Optional[str]
    dispute_id: Optional[str]
    settlement_cycle_id: Optional[str]
    effective_at: str
    memo: Optional[str]


VERSIONED_ENTITIES = (
    "Railroad",
    "Junction",
    "Car",
    "CarHireMovement",
    "ReclaimClaim",
    "EmbargoOrder",
    "RepairBill",
    "SettlementCycle",
    "Dispute",
    "CorrectionRequest",
)

UNVERSIONED_ENTITIES = ("CarType", "InterchangeEvent", "HireLedgerEntry")
