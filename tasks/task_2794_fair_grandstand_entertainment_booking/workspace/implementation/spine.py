"""Cascade-created records and the cancellation cascade (PRD sections 3.4, 3.9)."""

from datetime import timedelta

import ledgers
from db import db, day_delta, fmt_ts, new_id, now_str, parse_ts, stamp_new, touch

SEED_RIDER_DESCRIPTION = "Stage plot and rigging review"


def create_advance_with_seed(booking):
    """A production advance in ADVANCE_PENDING plus its critical seed staging line."""
    advance = {
        "id": new_id(),
        "booking_id": booking["id"],
        "status": "ADVANCE_PENDING",
        "approved_rider_cost_cents": 0,
        "recoupable_rider_cost_cents": 0,
        "denied_item_count": 0,
        "blocked_reason_code": None,
    }
    stamp_new(advance)
    db.advances[advance["id"]] = advance

    seed = {
        "id": new_id(),
        "production_advance_id": advance["id"],
        "category": "STAGING",
        "description": SEED_RIDER_DESCRIPTION,
        "requested_cost_cents": 0,
        "is_critical": True,
        "artist_recoupable": False,
        "status": "REQUESTED",
        "approved_cost_cents": 0,
    }
    stamp_new(seed)
    db.rider_items[seed["id"]] = seed
    return advance


def create_booking_from_offer(offer):
    """The show booking born of an accepted offer, with every deal term pinned."""
    booking = {
        "id": new_id(),
        "offer_id": offer["id"],
        "stage_id": offer["target_stage_id"],
        "postponed_from_booking_id": None,
        "show_date": offer["target_show_date"],
        "load_in_start_utc": offer["load_in_start_utc"],
        "load_out_end_utc": offer["load_out_end_utc"],
        "doors_time_utc": None,
        "booking_status": "DATE_HELD",
        "ticketing_status": "SCALED_PENDING",
        "agreed_guarantee_cents": offer["agreed_guarantee_cents"],
        "agreed_deal_type": offer["deal_type"],
        "agreed_backend_split_pct": offer["backend_split_pct"],
        "agreed_breakeven_cents": offer["backend_breakeven_cents"],
        "gross_potential_cents": 0,
        "sponsorship_revenue_cents": 0,
        "recoupable_production_cost_cents": 0,
        "paid_attendance": 0,
        "refund_liability_cents": 0,
        "announced_at_utc": None,
    }
    stamp_new(booking)
    db.bookings[booking["id"]] = booking
    create_advance_with_seed(booking)
    return booking


def _shift_instant(instant_text, days):
    moment = parse_ts(instant_text)
    if moment is None:
        return instant_text
    return fmt_ts(moment + timedelta(days=days))


def create_replacement_booking(original, replacement_show_date):
    """The replacement a POSTPONE produces, on the same stage and with the same terms."""
    shift = day_delta(replacement_show_date, original["show_date"]) or 0
    booking = {
        "id": new_id(),
        "offer_id": original.get("offer_id"),
        "stage_id": original.get("stage_id"),
        "postponed_from_booking_id": original["id"],
        "show_date": replacement_show_date,
        "load_in_start_utc": _shift_instant(original.get("load_in_start_utc"), shift),
        "load_out_end_utc": _shift_instant(original.get("load_out_end_utc"), shift),
        "doors_time_utc": None,
        "booking_status": "DATE_HELD",
        "ticketing_status": "SCALED_PENDING",
        "agreed_guarantee_cents": original.get("agreed_guarantee_cents"),
        "agreed_deal_type": original.get("agreed_deal_type"),
        "agreed_backend_split_pct": original.get("agreed_backend_split_pct"),
        "agreed_breakeven_cents": original.get("agreed_breakeven_cents"),
        "gross_potential_cents": 0,
        "sponsorship_revenue_cents": 0,
        "recoupable_production_cost_cents": 0,
        "paid_attendance": 0,
        "refund_liability_cents": 0,
        "announced_at_utc": None,
    }
    stamp_new(booking)
    db.bookings[booking["id"]] = booking
    create_advance_with_seed(booking)
    return booking


def void_advance(booking):
    """Cancel the booking's advance and void every rider line beneath it."""
    advance = ledgers.advance_of_booking(booking["id"])
    if advance is None:
        return
    if advance.get("status") == "ADVANCE_CANCELLED":
        return
    for item in ledgers.rider_items_of_advance(advance["id"]):
        if item.get("status") in ("REQUESTED", "APPROVED", "SUBSTITUTED", "DENIED"):
            item["status"] = "VOIDED"
            item["approved_cost_cents"] = 0
            touch(item)
    advance["status"] = "ADVANCE_CANCELLED"
    advance["blocked_reason_code"] = None
    ledgers.recompute_advance_ledgers(advance)
    touch(advance)


def cancel_activations(booking):
    """Every proposed or confirmed activation on the show becomes a make-good credit."""
    for activation in ledgers.activations_of_booking(booking["id"]):
        if activation.get("status") in ("PROPOSED", "CONFIRMED"):
            activation["status"] = "CANCELLED"
            activation["make_good_credit_cents"] = int(activation.get("net_fee_cents") or 0)
            touch(activation)
    ledgers.recompute_booking_sponsorship_revenue(booking)


def mark_scales_refund_due(booking):
    for scale in ledgers.scales_of_booking(booking["id"]):
        if scale.get("status") != "REFUND_DUE":
            scale["status"] = "REFUND_DUE"
            touch(scale)


def close_scales(booking):
    for scale in ledgers.scales_of_booking(booking["id"]):
        if scale.get("status") != "CLOSED":
            scale["status"] = "CLOSED"
            touch(scale)


def fulfil_activations(booking):
    for activation in ledgers.activations_of_booking(booking["id"]):
        if activation.get("status") == "CONFIRMED":
            activation["status"] = "FULFILLED"
            touch(activation)
    ledgers.recompute_booking_sponsorship_revenue(booking)


def stamp_now(record, field):
    record[field] = now_str()
