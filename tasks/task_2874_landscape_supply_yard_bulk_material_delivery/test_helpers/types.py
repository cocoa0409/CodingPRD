"""TypedDict shapes for every resource exposed by the Landscape Supply Yard API.

Every resource in this system carries the four common system fields (``id``,
``created_at``, ``updated_at``, ``version``); no resource omits ``updated_at`` or
``version``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """System-minted fields present on every resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ResponseMeta(TypedDict):
    api_request_id: str
    timestamp: str


class PaginationMeta(TypedDict):
    api_request_id: str
    timestamp: str
    total_count: int
    has_more: bool
    limit: int
    offset: int


class ErrorPayload(TypedDict):
    error_id: str
    message: str


class Material(CommonFields):
    sku: str
    name: str
    offered_forms: List[str]
    seasonal_category: str
    density_lb_per_cubic_yard: float
    shrinkage_factor: float
    moisture_pct: float
    unit_bag_cubic_yards: float
    prebuy_eligible: bool
    status: str
    effective_density_lb_per_cubic_yard: float
    available_net_cubic_yards: float


class PriceSchedule(CommonFields):
    material_id: str
    effective_from: str
    bulk_price_per_cubic_yard_cents: int
    bagged_price_per_bag_cents: int
    seasonal_surcharge_pct: float
    status: str


class InventoryLot(CommonFields):
    material_id: str
    gross_cubic_yards: float
    moisture_pct_at_intake: float
    current_moisture_pct: float
    basis: str
    withdrawn_gross_cubic_yards: float
    net_sellable_cubic_yards: float
    reserved_cubic_yards: float
    status: str


class ContractorAccount(CommonFields):
    business_name: str
    credit_limit_cents: int
    po_required: bool
    driveway_protection_required: bool
    credit_used_cents: int
    credit_available_cents: int
    pallet_deposit_balance_cents: int
    account_status: str


class JobPurchaseOrder(CommonFields):
    contractor_account_id: str
    po_number: str
    job_code: str
    po_limit_cents: int
    committed_cents: int
    status: str


class PreBuyContract(CommonFields):
    contractor_account_id: str
    material_id: str
    locked_price_per_cubic_yard_cents: int
    contracted_cubic_yards: float
    season_start_date: str
    season_end_date: str
    drawn_cubic_yards: float
    remaining_cubic_yards: float
    status: str


class MaterialOrder(CommonFields):
    contractor_account_id: str
    job_purchase_order_id: Optional[str]
    fulfillment_mode: str
    delivery_address: Optional[str]
    driveway_access_class: Optional[str]
    delivery_distance_miles: Optional[float]
    bulk_subtotal_cents: int
    bagged_subtotal_cents: int
    volume_discount_pct: float
    volume_discount_cents: int
    min_load_fee_cents: int
    delivery_fee_cents: int
    quoted_total_cents: Optional[int]
    final_total_cents: Optional[int]
    credit_memo_cents: int
    paid_amount_cents: int
    quote_locked_at: Optional[str]
    fulfillment_status: str
    settlement_status: str


class OrderLine(CommonFields):
    material_order_id: str
    material_id: str
    prebuy_contract_id: Optional[str]
    inventory_lot_id: Optional[str]
    form: str
    quantity: float
    unit_price_cents: Optional[int]
    line_price_cents: Optional[int]
    line_volume_cubic_yards: float
    delivered_volume_cubic_yards: float
    final_line_price_cents: Optional[int]


class DeliveryTruck(CommonFields):
    truck_code: str
    axle_class: str
    max_payload_lb: int
    bed_capacity_cubic_yards: float
    min_driveway_access_class: str
    status: str


class DeliveryLoad(CommonFields):
    material_order_id: str
    delivery_truck_id: str
    inventory_lot_id: Optional[str]
    planned_cubic_yards: float
    window_start: str
    window_end: str
    planned_payload_lb: int
    max_allowed_cubic_yards: float
    actual_net_cubic_yards: Optional[float]
    spillage_cubic_yards: float
    driveway_protection_used: Optional[bool]
    dispatched_by_user_id: Optional[str]
    refusal_reason: Optional[str]
    status: str


class WillCallTicket(CommonFields):
    material_order_id: str
    requested_pickup_at: str
    inventory_lot_id: Optional[str]
    priority_class: int
    queue_position: Optional[int]
    staging_window_start: Optional[str]
    staging_window_end: Optional[str]
    safety_briefing_code: Optional[str]
    ppe_confirmed: bool
    loaded_cubic_yards: Optional[float]
    staged_by_user_id: Optional[str]
    status: str


class ClaimCase(CommonFields):
    material_order_id: str
    delivery_load_id: Optional[str]
    will_call_ticket_id: Optional[str]
    claim_type: str
    claimed_amount_cents: int
    description: str
    review_round: int
    approved_amount_cents: Optional[int]
    payable_cents: Optional[int]
    invoice_offset_cents: int
    deposit_offset_cents: int
    goodwill_credit_cents: int
    decided_by_user_id: Optional[str]
    denial_reason: Optional[str]
    info_request_note: Optional[str]
    status: str


class ContainerReturn(CommonFields):
    material_order_id: str
    container_type: str
    issued_count: int
    returned_count: int
    deposit_per_unit_cents: int
    issued_at: str
    last_received_at: Optional[str]
    refund_cents: int
    forfeited_cents: int
    status: str


class ClockResult(TypedDict):
    current_utc: str
    promoted_price_schedule_ids: List[str]
    expired_prebuy_contract_ids: List[str]


Headers = Dict[str, str]
Payload = Dict[str, Any]

__all__ = [
    "CommonFields",
    "ResponseMeta",
    "PaginationMeta",
    "ErrorPayload",
    "Material",
    "PriceSchedule",
    "InventoryLot",
    "ContractorAccount",
    "JobPurchaseOrder",
    "PreBuyContract",
    "MaterialOrder",
    "OrderLine",
    "DeliveryTruck",
    "DeliveryLoad",
    "WillCallTicket",
    "ClaimCase",
    "ContainerReturn",
    "ClockResult",
    "Headers",
    "Payload",
]
