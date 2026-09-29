"""Resource serialisers.  Computed fields are derived at render time."""
from core import iso

import calc

COMMON = ("created_at", "updated_at", "version")


def _base(record, keys, instants=()):
    out = {"id": record["id"]}
    for key in keys:
        value = record.get(key)
        if key in instants:
            value = iso(value)
        out[key] = value
    for key in COMMON:
        out[key] = record[key]
    return out


def material(record):
    out = _base(record, (
        "sku", "name", "offered_forms", "seasonal_category",
        "density_lb_per_cubic_yard", "shrinkage_factor", "moisture_pct",
        "unit_bag_cubic_yards", "prebuy_eligible", "status",
    ))
    out["effective_density_lb_per_cubic_yard"] = calc.effective_density(record)
    out["available_net_cubic_yards"] = calc.material_available_net(record)
    for key in COMMON:
        out[key] = record[key]
    return out


def price_schedule(record):
    return _base(record, (
        "material_id", "effective_from", "bulk_price_per_cubic_yard_cents",
        "bagged_price_per_bag_cents", "seasonal_surcharge_pct", "status",
    ), instants=("effective_from",))


def inventory_lot(record):
    return _base(record, (
        "material_id", "gross_cubic_yards", "moisture_pct_at_intake",
        "current_moisture_pct", "basis", "withdrawn_gross_cubic_yards",
        "net_sellable_cubic_yards", "reserved_cubic_yards", "status",
    ))


def contractor_account(record):
    return _base(record, (
        "business_name", "credit_limit_cents", "po_required",
        "driveway_protection_required", "credit_used_cents",
        "credit_available_cents", "pallet_deposit_balance_cents", "account_status",
    ))


def job_purchase_order(record):
    return _base(record, (
        "contractor_account_id", "po_number", "job_code", "po_limit_cents",
        "committed_cents", "status",
    ))


def prebuy_contract(record):
    return _base(record, (
        "contractor_account_id", "material_id",
        "locked_price_per_cubic_yard_cents", "contracted_cubic_yards",
        "season_start_date", "season_end_date", "drawn_cubic_yards",
        "remaining_cubic_yards", "status",
    ))


def material_order(record):
    return _base(record, (
        "contractor_account_id", "job_purchase_order_id", "fulfillment_mode",
        "delivery_address", "driveway_access_class", "delivery_distance_miles",
        "bulk_subtotal_cents", "bagged_subtotal_cents", "volume_discount_pct",
        "volume_discount_cents", "min_load_fee_cents", "delivery_fee_cents",
        "quoted_total_cents", "final_total_cents", "credit_memo_cents",
        "paid_amount_cents", "quote_locked_at", "fulfillment_status",
        "settlement_status",
    ), instants=("quote_locked_at",))


def order_line(record):
    return _base(record, (
        "material_order_id", "material_id", "prebuy_contract_id",
        "inventory_lot_id", "form", "quantity", "unit_price_cents",
        "line_price_cents", "line_volume_cubic_yards",
        "delivered_volume_cubic_yards", "final_line_price_cents",
    ))


def delivery_truck(record):
    return _base(record, (
        "truck_code", "axle_class", "max_payload_lb", "bed_capacity_cubic_yards",
        "min_driveway_access_class", "status",
    ))


def delivery_load(record):
    return _base(record, (
        "material_order_id", "delivery_truck_id", "inventory_lot_id",
        "planned_cubic_yards", "window_start", "window_end", "planned_payload_lb",
        "max_allowed_cubic_yards", "actual_net_cubic_yards",
        "spillage_cubic_yards", "driveway_protection_used",
        "dispatched_by_user_id", "refusal_reason", "status",
    ), instants=("window_start", "window_end"))


def will_call_ticket(record):
    out = _base(record, (
        "material_order_id", "requested_pickup_at", "inventory_lot_id",
        "staging_window_start", "staging_window_end", "safety_briefing_code",
        "ppe_confirmed", "loaded_cubic_yards", "staged_by_user_id", "status",
    ), instants=("requested_pickup_at", "staging_window_start",
                 "staging_window_end"))
    out["priority_class"] = calc.ticket_priority_class(record)
    out["queue_position"] = calc.ticket_queue_position(record)
    for key in COMMON:
        out[key] = record[key]
    return out


def claim_case(record):
    return _base(record, (
        "material_order_id", "delivery_load_id", "will_call_ticket_id",
        "claim_type", "claimed_amount_cents", "description", "review_round",
        "approved_amount_cents", "payable_cents", "invoice_offset_cents",
        "deposit_offset_cents", "goodwill_credit_cents", "decided_by_user_id",
        "denial_reason", "info_request_note", "status",
    ))


def container_return(record):
    return _base(record, (
        "material_order_id", "container_type", "issued_count", "returned_count",
        "deposit_per_unit_cents", "issued_at", "last_received_at", "refund_cents",
        "forfeited_cents", "status",
    ), instants=("issued_at", "last_received_at"))
