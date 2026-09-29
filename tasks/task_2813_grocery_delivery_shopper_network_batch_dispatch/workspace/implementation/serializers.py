"""Response payload shapes, one per entity family (SCAFFOLD 1.1)."""
from decimal import Decimal

from store import fmt_ts


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, with_version=True):
    out = {"id": row["id"], "created_at": fmt_ts(row["created_at"])}
    if with_version:
        out["updated_at"] = fmt_ts(row["updated_at"])
        out["version"] = row["version"]
    return out


def retailer(row):
    out = _common(row)
    out.update(
        {
            "legal_name": row["legal_name"],
            "store_code": row["store_code"],
            "catalog_markup_pct": num(row["catalog_markup_pct"]),
            "parity_disclosure_required": row["parity_disclosure_required"],
            "ebt_snap_enabled": row["ebt_snap_enabled"],
            "concurrent_shopper_cap": row["concurrent_shopper_cap"],
            "status": row["status"],
        }
    )
    return out


def catalog_item(row):
    out = _common(row)
    out.update(
        {
            "retailer_id": row["retailer_id"],
            "sku": row["sku"],
            "name": row["name"],
            "pricing_unit": row["pricing_unit"],
            "in_store_price_cents": row["in_store_price_cents"],
            "catalog_price_cents": row["catalog_price_cents"],
            "is_ebt_eligible": row["is_ebt_eligible"],
            "is_weighted": row["is_weighted"],
            "estimated_weight_lb": num(row["estimated_weight_lb"]),
            "unit_weight_lb": num(row["unit_weight_lb"]),
            "availability": row["availability"],
        }
    )
    return out


def customer(row):
    out = _common(row)
    out.update(
        {
            "display_name": row["display_name"],
            "card_last4": row["card_last4"],
            "ebt_snap_balance_cents": row["ebt_snap_balance_cents"],
            "ebt_captured_total_cents": row["ebt_captured_total_cents"],
            "credit_balance_cents": row["credit_balance_cents"],
        }
    )
    return out


def shopper(row):
    out = _common(row)
    out.update(
        {
            "display_name": row["display_name"],
            "service_area_code": row["service_area_code"],
            "vehicle_capacity_units": row["vehicle_capacity_units"],
            "committed_units": row["committed_units"],
            "completed_batch_count": row["completed_batch_count"],
            "abandonment_count": row["abandonment_count"],
            "rolling_recent_avg": num(row["rolling_recent_avg"]),
            "lifetime_rating_avg": num(row["lifetime_rating_avg"]),
            "rolling_tier_score": num(row["rolling_tier_score"]),
            "lifetime_tier_score": num(row["lifetime_tier_score"]),
            "tier": row["tier"],
            "lifetime_tier": row["lifetime_tier"],
            "status": row["status"],
        }
    )
    return out


def shopper_rating(row):
    out = _common(row, with_version=False)
    out.update(
        {
            "shopper_id": row["shopper_id"],
            "order_id": row["order_id"],
            "stars": row["stars"],
            "sequence_no": row["sequence_no"],
        }
    )
    return out


def order(row):
    out = _common(row)
    out.update(
        {
            "customer_id": row["customer_id"],
            "retailer_id": row["retailer_id"],
            "delivery_distance_mi": num(row["delivery_distance_mi"]),
            "delivery_deadline": fmt_ts(row["delivery_deadline"]),
            "ebt_requested": row["ebt_requested"],
            "tip_amount_cents": row["tip_amount_cents"],
            "fulfillment_status": row["fulfillment_status"],
            "payment_status": row["payment_status"],
            "estimated_subtotal_cents": row["estimated_subtotal_cents"],
            "authorization_ceiling_cents": row["authorization_ceiling_cents"],
            "authorized_ebt_cents": row["authorized_ebt_cents"],
            "authorized_card_cents": row["authorized_card_cents"],
            "captured_subtotal_cents": row["captured_subtotal_cents"],
            "ebt_captured_cents": row["ebt_captured_cents"],
            "card_captured_cents": row["card_captured_cents"],
            "refunded_cents": row["refunded_cents"],
            "tip_original_cents": row["tip_original_cents"],
            "tip_adjustment_count": row["tip_adjustment_count"],
            "delivered_at": fmt_ts(row["delivered_at"]),
            "tip_window_closes_at": fmt_ts(row["tip_window_closes_at"]),
            "parity_markup_cents": row["parity_markup_cents"],
            "parity_disclosed": row["parity_disclosed"],
        }
    )
    return out


def order_line(row):
    out = _common(row)
    out.update(
        {
            "order_id": row["order_id"],
            "catalog_item_id": row["catalog_item_id"],
            "requested_qty": row["requested_qty"],
            "requested_weight_lb": num(row["requested_weight_lb"]),
            "unit_price_cents_snapshot": row["unit_price_cents_snapshot"],
            "in_store_price_cents_snapshot": row["in_store_price_cents_snapshot"],
            "ebt_eligible_snapshot": row["ebt_eligible_snapshot"],
            "picked_qty": row["picked_qty"],
            "final_weight_lb": num(row["final_weight_lb"]),
            "final_price_cents": row["final_price_cents"],
            "status": row["status"],
        }
    )
    return out


def batch(row):
    out = _common(row)
    out.update(
        {
            "service_area_code": row["service_area_code"],
            "shop_window_start": fmt_ts(row["shop_window_start"]),
            "shop_window_end": fmt_ts(row["shop_window_end"]),
            "tier_access_floor": row["tier_access_floor"],
            "status": row["status"],
            "offered_shopper_id": row["offered_shopper_id"],
            "claimed_shopper_id": row["claimed_shopper_id"],
            "declined_shopper_ids": list(row["declined_shopper_ids"]),
            "offer_expires_at": fmt_ts(row["offer_expires_at"]),
            "delivery_deadline": fmt_ts(row["delivery_deadline"]),
            "total_units": row["total_units"],
            "total_weight_lb": num(row["total_weight_lb"]),
            "total_distance_mi": num(row["total_distance_mi"]),
            "store_count": row["store_count"],
            "checkout_blocked_count": row["checkout_blocked_count"],
            "reassignment_count": row["reassignment_count"],
            "abandoned_at": fmt_ts(row["abandoned_at"]),
        }
    )
    return out


def batch_order(row):
    out = _common(row, with_version=False)
    out.update(
        {
            "batch_id": row["batch_id"],
            "order_id": row["order_id"],
            "sequence_no": row["sequence_no"],
            "units": row["units"],
        }
    )
    return out


def replacement_request(row):
    out = _common(row)
    out.update(
        {
            "batch_id": row["batch_id"],
            "order_line_id": row["order_line_id"],
            "proposed_catalog_item_id": row["proposed_catalog_item_id"],
            "proposed_qty": row["proposed_qty"],
            "proposed_weight_lb": num(row["proposed_weight_lb"]),
            "price_delta_cents": row["price_delta_cents"],
            "expires_at": fmt_ts(row["expires_at"]),
            "status": row["status"],
            "resolution_effect": row["resolution_effect"],
        }
    )
    return out


def shopper_payout(row):
    out = _common(row)
    out.update(
        {
            "batch_id": row["batch_id"],
            "shopper_id": row["shopper_id"],
            "base_pay_cents": row["base_pay_cents"],
            "heavy_pay_cents": row["heavy_pay_cents"],
            "mileage_bonus_cents": row["mileage_bonus_cents"],
            "multi_store_bonus_cents": row["multi_store_bonus_cents"],
            "tip_pass_through_cents": row["tip_pass_through_cents"],
            "tip_protection_cents": row["tip_protection_cents"],
            "guarantee_top_up_cents": row["guarantee_top_up_cents"],
            "total_payout_cents": row["total_payout_cents"],
            "status": row["status"],
        }
    )
    return out


def credit_entry(row):
    out = _common(row, with_version=False)
    out.update(
        {
            "customer_id": row["customer_id"],
            "order_id": row["order_id"],
            "amount_cents": row["amount_cents"],
            "reason_code": row["reason_code"],
        }
    )
    return out
