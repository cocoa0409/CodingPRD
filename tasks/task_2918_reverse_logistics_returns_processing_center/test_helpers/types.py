"""TypedDict shapes for every resource the API returns (PRD §2.4, §3).

Ten resource types carry `updated_at` and an integer `version`; the four
append-only record types carry only `id` and `created_at`, and their shapes
below deliberately omit the two mutable-row fields.
"""

from typing import List, Optional, TypedDict


class VersionedResource(TypedDict):
    """The identity fields shared by the ten mutable resource types."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyResource(TypedDict):
    """The identity fields shared by the four append-only record types."""

    id: str
    created_at: str


class Client(VersionedResource):
    name: str
    client_code: str
    service_level: str
    inventory_ownership: str
    restock_grade_floor: str
    refund_hold_hours: int
    liquidation_floor_pct: float
    fraud_tolerance_cents: int
    donation_allowed: bool
    destroy_requires_dual_signoff: bool
    max_refund_exposure_cents: int
    status: str
    units_received: int
    units_in_process: int
    units_reserved_for_disposition: int
    units_dispositioned: int
    shrink_ledger_cents: int
    settlement_balance_cents: int
    projected_settlement_balance_cents: int
    open_rma_count: int


class CatalogItem(VersionedResource):
    client_id: str
    sku: str
    description: str
    declared_value_cents: int
    unit_weight_grams: int
    serialized: bool
    hazard_class: str
    regulated_flag: bool
    recall_status: str
    refurb_eligible: bool
    secondary_market_floor_cents: int


class ProcessingBay(VersionedResource):
    bay_code: str
    bay_type: str
    buffer_minutes: int
    status: str


class SecondaryMarketChannel(VersionedResource):
    name: str
    channel_code: str
    channel_type: str
    accepted_grades: List[str]
    fee_pct: float
    hazard_certified: bool
    recall_certified: bool
    min_lot_value_cents: int
    concurrent_lot_capacity: int
    price_index_pct: float
    status: str


class ReturnAuthorization(VersionedResource):
    client_id: str
    order_reference: str
    customer_reference: str
    order_placed_at: str
    expires_at: str
    supersedes_rma_id: Optional[str]
    status: str
    declared_line_count: int
    authorized_unit_total: int
    received_unit_total: int
    fraud_flag_count: int
    issued_at: Optional[str]


class ReturnAuthorizationLine(AppendOnlyResource):
    rma_id: str
    catalog_item_id: str
    authorized_quantity: int
    reason_code: str
    declared_serial: Optional[str]
    received_quantity: int


class Receipt(VersionedResource):
    rma_id: str
    tracking_reference: str
    gross_weight_grams: int
    expected_weight_grams: int
    empty_box_suspected: bool
    received_at: str
    scanned_by_user_id: str


class ReturnLine(VersionedResource):
    receipt_id: str
    rma_line_id: str
    bay_id: Optional[str]
    quantity: int
    scanned_serial: Optional[str]
    reason_code: str
    condition_grade: str
    disposition: str
    disposition_state: str
    financial_state: str
    quarantine_start_at: Optional[str]
    quarantine_end_at: Optional[str]
    days_since_order: int
    recovery_value_cents: int
    fraud_score_receipt: int
    fraud_score_release: int
    graded_by_user_id: Optional[str]
    released_by_user_id: Optional[str]


class FraudCheck(AppendOnlyResource):
    return_line_id: str
    check_type: str
    outcome: str
    weight_points: int
    evidence: str
    evaluated_stage: str


class RefurbWorkOrder(VersionedResource):
    return_line_id: str
    bay_id: Optional[str]
    assigned_technician_user_id: str
    status: str
    rework_cycles: int
    labor_minutes_total: int
    parts_cost_cents: int
    packaging_cost_cents: int
    total_cost_cents: int
    resulting_grade: Optional[str]
    test_window_start_at: Optional[str]
    test_window_end_at: Optional[str]
    qa_user_id: Optional[str]


class DispositionOrder(VersionedResource):
    return_line_id: str
    channel_id: Optional[str]
    disposition: str
    quantity: int
    unit_price_cents: int
    channel_window_start_at: Optional[str]
    channel_window_end_at: Optional[str]
    gross_lot_value_cents: int
    effective_fee_pct: float
    channel_fee_cents: int
    net_recovery_cents: int
    refurb_cost_cents: int
    status: str
    approved_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]
    executed_at: Optional[str]
    selected_by_policy: bool


class PricingFeedback(AppendOnlyResource):
    disposition_order_id: str
    channel_id: str
    expected_price_cents: int
    realized_price_cents: int
    variance_pct: float
    sequence_no: int


class RefundRelease(VersionedResource):
    return_line_id: str
    client_id: str
    gross_refund_cents: int
    restocking_fee_pct: float
    restocking_fee_cents: int
    net_refund_cents: int
    release_eligible_at: Optional[str]
    released_at: Optional[str]
    released_by_user_id: Optional[str]
    reversed_at: Optional[str]
    denial_reason: Optional[str]


class ShrinkLedgerEntry(AppendOnlyResource):
    client_id: str
    return_line_id: Optional[str]
    entry_type: str
    amount_cents: int
    memo: str
    sequence_no: int


class DispositionAuditReport(TypedDict):
    restock_count: int
    refurbish_count: int
    liquidate_count: int
    donate_count: int
    destroy_count: int
    pending_count: int
    recovery_credit_cents: int
    refund_debit_cents: int
    reversal_cents: int
    refurb_cost_cents: int
    donation_write_off_cents: int
    destruction_write_off_cents: int
    receipt_variance_cents: int
    recovery_variance_cents: int
    settlement_balance_cents: int
    projected_settlement_balance_cents: int
    shrink_ledger_cents: int
    units_received: int
    units_in_process: int
    units_reserved_for_disposition: int
    units_dispositioned: int
    unit_conservation_ok: bool
    money_conservation_ok: bool
