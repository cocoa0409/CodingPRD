"""TypedDict shapes for every entity the API exposes.

Entities that carry the full identity set declare id / created_at /
updated_at / version. The three append-only entities (ShopperRating,
BatchOrder, CreditLedgerEntry) declare only id and created_at, because the
PRD states their rows are never updated and must not carry updated_at or
version at all.
"""

from typing import Any, Dict, List, Optional, TypedDict


class VersionedEntity(TypedDict):
    """Full identity set: id, created_at, updated_at, version."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyEntity(TypedDict):
    """Append-only identity set: id and created_at only."""

    id: str
    created_at: str


class Retailer(VersionedEntity):
    legal_name: str
    store_code: str
    catalog_markup_pct: float
    parity_disclosure_required: bool
    ebt_snap_enabled: bool
    concurrent_shopper_cap: int
    status: str


class CatalogItem(VersionedEntity):
    retailer_id: str
    sku: str
    name: str
    pricing_unit: str
    in_store_price_cents: int
    catalog_price_cents: int
    is_ebt_eligible: bool
    is_weighted: bool
    estimated_weight_lb: float
    unit_weight_lb: float
    availability: str


class Customer(VersionedEntity):
    display_name: str
    card_last4: str
    ebt_snap_balance_cents: int
    ebt_captured_total_cents: int
    credit_balance_cents: int


class Shopper(VersionedEntity):
    display_name: str
    service_area_code: str
    vehicle_capacity_units: int
    committed_units: int
    completed_batch_count: int
    abandonment_count: int
    rolling_recent_avg: float
    lifetime_rating_avg: float
    rolling_tier_score: float
    lifetime_tier_score: float
    tier: str
    lifetime_tier: str
    status: str


class ShopperRating(AppendOnlyEntity):
    shopper_id: str
    order_id: Optional[str]
    stars: int
    sequence_no: int


class Order(VersionedEntity):
    customer_id: str
    retailer_id: str
    delivery_distance_mi: float
    delivery_deadline: str
    ebt_requested: bool
    tip_amount_cents: int
    fulfillment_status: str
    payment_status: str
    estimated_subtotal_cents: int
    authorization_ceiling_cents: int
    authorized_ebt_cents: int
    authorized_card_cents: int
    captured_subtotal_cents: int
    ebt_captured_cents: int
    card_captured_cents: int
    refunded_cents: int
    tip_original_cents: int
    tip_adjustment_count: int
    delivered_at: Optional[str]
    tip_window_closes_at: Optional[str]
    parity_markup_cents: int
    parity_disclosed: bool


class OrderLine(VersionedEntity):
    order_id: str
    catalog_item_id: str
    requested_qty: int
    requested_weight_lb: float
    unit_price_cents_snapshot: int
    in_store_price_cents_snapshot: int
    ebt_eligible_snapshot: bool
    picked_qty: int
    final_weight_lb: float
    final_price_cents: int
    status: str


class Batch(VersionedEntity):
    service_area_code: str
    shop_window_start: str
    shop_window_end: str
    tier_access_floor: str
    status: str
    offered_shopper_id: Optional[str]
    claimed_shopper_id: Optional[str]
    declined_shopper_ids: List[str]
    offer_expires_at: Optional[str]
    delivery_deadline: Optional[str]
    total_units: int
    total_weight_lb: float
    total_distance_mi: float
    store_count: int
    checkout_blocked_count: int
    reassignment_count: int
    abandoned_at: Optional[str]


class BatchOrder(AppendOnlyEntity):
    batch_id: str
    order_id: str
    sequence_no: int
    units: int


class ReplacementRequest(VersionedEntity):
    batch_id: str
    order_line_id: str
    proposed_catalog_item_id: str
    proposed_qty: int
    proposed_weight_lb: float
    price_delta_cents: int
    expires_at: str
    status: str
    resolution_effect: str


class ShopperPayout(VersionedEntity):
    batch_id: str
    shopper_id: str
    base_pay_cents: int
    heavy_pay_cents: int
    mileage_bonus_cents: int
    multi_store_bonus_cents: int
    tip_pass_through_cents: int
    tip_protection_cents: int
    guarantee_top_up_cents: int
    total_payout_cents: int
    status: str


class CreditLedgerEntry(AppendOnlyEntity):
    customer_id: str
    order_id: Optional[str]
    amount_cents: int
    reason_code: str


class ParityDisclosure(TypedDict):
    """Shape of the computed read GET /orders/{id}/parity-disclosure."""

    order_id: str
    catalog_total_cents: int
    in_store_total_cents: int
    markup_cents: int
    effective_markup_pct: float
    disclosure_required: bool
    disclosure_satisfied: bool


# Convenience aliases used by fixtures that hand back whole scenario graphs.
Payload = Dict[str, Any]
Headers = Dict[str, str]
Scenario = Dict[str, Any]
