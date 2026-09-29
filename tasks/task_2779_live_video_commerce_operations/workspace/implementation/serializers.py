"""Resource representations. Derived fields are reconciled at read time so a read
issued immediately after a cascade sees fully reconciled values (PRD 2.11)."""

from store import common_out, fmt_dt
import calc


def dt(value):
    if value is None:
        return None
    return fmt_dt(value)


def num(value):
    return float(value)


def host_out(host):
    data = common_out(host)
    data.update({
        "full_name": host["full_name"],
        "handle": host["handle"],
        "commission_pct": num(host["commission_pct"]),
        "disclosure_certification_expires_at": dt(host["disclosure_certification_expires_at"]),
        "certification_status": calc.certification_status(host),
        "effectiveness_score_live": host["effectiveness_score_live"],
        "effectiveness_score_attributed": host["effectiveness_score_attributed"],
    })
    return data


def product_out(product):
    reserved, committed, available = calc.product_pools(product)
    data = common_out(product)
    data.update({
        "sku": product["sku"],
        "title": product["title"],
        "base_price_cents": product["base_price_cents"],
        "unit_cost_cents": product["unit_cost_cents"],
        "on_hand_qty": product["on_hand_qty"],
        "reserved_qty": reserved,
        "committed_qty": committed,
        "available_qty": available,
        "claim_text": product["claim_text"],
        "claim_substantiation_status": product["claim_substantiation_status"],
        "substantiated_by_user_id": product["substantiated_by_user_id"],
        "substantiated_at": dt(product["substantiated_at"]),
    })
    return data


def viewer_out(viewer):
    data = common_out(viewer)
    data.update({
        "display_name": viewer["display_name"],
        "email": viewer["email"],
        "chat_status": viewer["chat_status"],
        "strike_count": viewer["strike_count"],
        "muted_until": dt(viewer["muted_until"]),
    })
    return data


def show_out(show):
    data = common_out(show)
    data.update({
        "title": show["title"],
        "scheduled_start_at": dt(show["scheduled_start_at"]),
        "scheduled_end_at": dt(show["scheduled_end_at"]),
        "status": show["status"],
        "created_by_user_id": show["created_by_user_id"],
        "readiness_checked_at": dt(show["readiness_checked_at"]),
        "went_live_at": dt(show["went_live_at"]),
        "ended_at": dt(show["ended_at"]),
        "settled_at": dt(show["settled_at"]),
        "compliance_signoff_by_user_id": show["compliance_signoff_by_user_id"],
        "simulcast_readiness_index": show["simulcast_readiness_index"],
        "gross_merchandise_cents": calc.gross_merchandise_cents(show["id"]),
        "margin_provisional_cents": show["margin_provisional_cents"],
        "margin_final_cents": show["margin_final_cents"],
        "abandoned_cart_count": calc.abandoned_cart_count(show["id"]),
        "abandonment_rate_bp": calc.abandonment_rate_bp(show["id"]),
        "pending_question_count": calc.pending_question_count(show["id"]),
        "replay_attributed_revenue_cents": calc.replay_attributed_revenue_cents(show["id"]),
    })
    return data


def channel_out(channel):
    data = common_out(channel)
    data.update({
        "show_id": channel["show_id"],
        "platform": channel["platform"],
        "is_primary": channel["is_primary"],
        "target_latency_ms": channel["target_latency_ms"],
        "status": channel["status"],
        "latency_ms": channel["latency_ms"],
        "dropped_frame_pct": num(channel["dropped_frame_pct"]),
        "readiness_index": channel["readiness_index"],
        "health_report_count": channel["health_report_count"],
    })
    return data


def booking_out(booking):
    data = common_out(booking)
    data.update({
        "show_id": booking["show_id"],
        "host_id": booking["host_id"],
        "role": booking["role"],
        "status": booking["status"],
        "call_time_at": dt(booking["call_time_at"]),
        "release_time_at": dt(booking["release_time_at"]),
        "fee_cents": booking["fee_cents"],
        "confirmed_at": dt(booking["confirmed_at"]),
        "cancel_reason": booking["cancel_reason"],
    })
    return data


def slot_out(slot):
    data = common_out(slot)
    data.update({
        "show_id": slot["show_id"],
        "product_id": slot["product_id"],
        "slot_sequence": slot["slot_sequence"],
        "planned_start_at": dt(slot["planned_start_at"]),
        "planned_end_at": dt(slot["planned_end_at"]),
        "planned_qty": slot["planned_qty"],
        "unit_cost_snapshot_cents": slot["unit_cost_snapshot_cents"],
        "replay_marker_offset_sec": slot["replay_marker_offset_sec"],
        "replay_product_link_url": slot["replay_product_link_url"],
        "replay_marker_status": slot["replay_marker_status"],
        "replay_conversions_count": slot["replay_conversions_count"],
        "replay_attributed_revenue_cents": slot["replay_attributed_revenue_cents"],
    })
    return data


def offer_out(offer):
    held, sold, remaining = calc.offer_pools(offer)
    data = common_out(offer)
    data.update({
        "lineup_slot_id": offer["lineup_slot_id"],
        "superseded_by_offer_id": offer["superseded_by_offer_id"],
        "offer_price_cents": offer["offer_price_cents"],
        "window_start_at": dt(offer["window_start_at"]),
        "window_end_at": dt(offer["window_end_at"]),
        "max_qty": offer["max_qty"],
        "held_qty": held,
        "sold_qty": sold,
        "remaining_qty": remaining,
        "status": offer["status"],
        "activated_at": dt(offer["activated_at"]),
    })
    return data


def disclosure_out(record):
    data = common_out(record)
    data.update({
        "show_id": record["show_id"],
        "host_booking_id": record["host_booking_id"],
        "disclosure_type": record["disclosure_type"],
        "required_script_code": record["required_script_code"],
        "status": record["status"],
        "acknowledged_at": dt(record["acknowledged_at"]),
        "acknowledged_late": record["acknowledged_late"],
    })
    return data


def cart_out(cart):
    lines = calc.items_of_cart(cart["id"])
    held = [line for line in lines if line["state"] == "HELD"]
    data = common_out(cart)
    data.update({
        "show_id": cart["show_id"],
        "viewer_id": cart["viewer_id"],
        "status": cart["status"],
        "pre_discount_subtotal_cents": sum(
            line["offer_unit_price_cents"] * line["qty"] for line in held),
        "bundle_discount_pct": num(cart["bundle_discount_pct"]),
        "held_item_count": len(held),
        "abandoned_at": dt(cart["abandoned_at"]),
        "recovery_deadline_at": dt(cart["recovery_deadline_at"]),
        "recovered_count": cart["recovered_count"],
        "checked_out_at": dt(cart["checked_out_at"]),
    })
    return data


def item_out(item):
    data = common_out(item)
    data.update({
        "cart_id": item["cart_id"],
        "flash_offer_id": item["flash_offer_id"],
        "lineup_slot_id": item["lineup_slot_id"],
        "qty": item["qty"],
        "list_unit_price_cents": item["list_unit_price_cents"],
        "offer_unit_price_cents": item["offer_unit_price_cents"],
        "effective_unit_price_cents": item["effective_unit_price_cents"],
        "line_gross_cents": item["line_gross_cents"],
        "line_tax_cents": item["line_tax_cents"],
        "state": item["state"],
        "released_reason": item["released_reason"],
        "released_at": dt(item["released_at"]),
    })
    return data


def order_out(order):
    data = common_out(order)
    data.update({
        "cart_id": order["cart_id"],
        "show_id": order["show_id"],
        "viewer_id": order["viewer_id"],
        "payment_state": order["payment_state"],
        "fulfillment_state": order["fulfillment_state"],
        "merchandise_cents": order["merchandise_cents"],
        "tax_cents": order["tax_cents"],
        "shipping_cents": order["shipping_cents"],
        "total_cents": order["total_cents"],
        "host_commission_accrued_cents": order["host_commission_accrued_cents"],
        "refunded_cents": order["refunded_cents"],
        "captured_at": dt(order["captured_at"]),
        "cancelled_at": dt(order["cancelled_at"]),
        "cancel_reason": order["cancel_reason"],
    })
    return data


def interaction_out(item):
    data = common_out(item)
    data.update({
        "show_id": item["show_id"],
        "viewer_id": item["viewer_id"],
        "host_id": item["host_id"],
        "kind": item["kind"],
        "body": item["body"],
        "state": item["state"],
        "moderated_at": dt(item["moderated_at"]),
        "blocked_reason": item["blocked_reason"],
        "routed_at": dt(item["routed_at"]),
        "defer_count": item["defer_count"],
        "answered_at": dt(item["answered_at"]),
        "answer_body": item["answer_body"],
        "options": item["options"],
        "tallies": item["tallies"],
        "voted_viewer_ids": item["voted_viewer_ids"],
        "vote_count": item["vote_count"],
    })
    return data
