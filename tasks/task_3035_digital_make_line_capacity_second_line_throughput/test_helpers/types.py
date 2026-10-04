"""Typed shapes for every resource the Digital Makeline Capacity API returns.

Each TypedDict mirrors the field list the contract declares for that resource.
Every resource in this domain is mutable and carries the full common quartet —
``id``, ``created_at``, ``updated_at`` and ``version`` — so no shape here omits
them.
"""

from typing import List, Optional, TypedDict


class ResponseMeta(TypedDict, total=False):
    """The meta block that accompanies every response."""

    api_request_id: str
    api_request_timestamp: str
    response_type: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class Store(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_code: str
    name: str
    digital_line_capacity_per_interval: int
    instore_line_capacity_per_interval: int
    pacing_interval_minutes: int
    instore_promise_minutes: int
    overage_threshold_pct: float
    marketplace_commission_pct: float
    digital_interval_load: int
    instore_interval_load: int
    throttle_state: str
    forecast_day_cents: int
    theoretical_food_cost_cents: int
    actual_food_cost_cents: int
    food_cost_variance_bps: int
    current_business_day: str


class Ingredient(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    ingredient_code: str
    display_name: str
    unit_cost_cents_per_gram: float
    par_level_grams: int
    hold_time_minutes: int
    batch_size_grams: int
    on_hand_grams: int
    shortage_state: str


class IngredientBatch(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    ingredient_id: str
    store_id: str
    cooked_at: str
    grams_cooked: int
    grams_remaining: int
    discard_at: str
    discarded_grams: int
    status: str


class MenuItem(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_id: str
    item_code: str
    display_name: str
    base_price_cents: int
    is_digital_eligible: bool
    theoretical_cost_cents: int
    suppression_state: str


class RecipeComponent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    menu_item_id: str
    ingredient_id: str
    standard_grams: int


class MarketplaceChannel(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    channel_code: str
    markup_pct: float
    commission_pct: float
    active: bool


class ProductionWindow(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_id: str
    interval_start: str
    interval_end: str
    digital_capacity: int
    digital_committed: int
    digital_completed: int
    instore_committed: int
    status: str


class Order(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_id: str
    channel: str
    marketplace_channel_id: Optional[str]
    external_order_ref: Optional[str]
    promised_at: str
    placed_at: str
    line: str
    production_window_id: Optional[str]
    subtotal_cents: int
    commission_cents: int
    net_revenue_cents: int
    theoretical_cost_cents: int
    entree_count: int
    payment_status: str
    fulfillment_status: str
    accuracy_status: str


class OrderLine(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    menu_item_id: str
    quantity: int
    unit_price_cents: int
    customizations: List[dict]
    lid_label_code: str
    accuracy_check: str


class AccuracyVerification(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    order_id: str
    verified_by: str
    checked_components: int
    mismatched_lines: int
    result: str
    created_at_note: str


class StaffingDeployment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_id: str
    shift_date: str
    predicted_digital_mix_pct: float
    predicted_instore_mix_pct: float
    headcount: int
    digital_headcount: int
    instore_headcount: int
    status: str


class SuppressionEvent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_id: str
    menu_item_id: str
    ingredient_id: str
    scope: str
    cause: str
    status: str


class WasteEvent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_id: str
    ingredient_batch_id: str
    grams: int
    reason: str
    cost_cents: int


class DayClose(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_id: str
    business_day: str
    orders_accepted: int
    orders_completed: int
    digital_net_revenue_cents: int
    instore_net_revenue_cents: int
    food_cost_variance_bps: int
    status: str


class ClockState(TypedDict):
    """What the clock write reports back."""

    current_utc: str
