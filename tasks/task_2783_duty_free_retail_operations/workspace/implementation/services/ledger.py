"""The append-only bonded ledger (PRD section 2.9)."""
from flask import g

import clock
import db
from services.money import apply_bps

RESERVED_TYPES = ("RESERVATION_HOLD", "RESERVATION_RELEASE")


def active_agreement(terminal_id):
    for agreement in db.ordered(db.agreements,
                               lambda r: r["terminal_id"] == terminal_id and r["status"] == "ACTIVE"):
        return agreement
    return None


def movements_of(stock_item_id):
    return db.ordered(db.movements, lambda m: m["stock_item_id"] == stock_item_id)


def derive(item):
    on_hand = 0
    reserved = 0
    for movement in db.movements.values():
        if movement["stock_item_id"] != item["id"]:
            continue
        if movement["affects"] == "ON_HAND":
            on_hand += movement["qty_delta"]
        else:
            reserved += movement["qty_delta"]
    item["on_hand_qty"] = on_hand
    item["reserved_qty"] = reserved
    item["available_qty"] = on_hand - reserved
    product = db.products[item["product_id"]]
    item["duty_suspended_value_cents"] = apply_bps(
        on_hand * product["unit_price_cents"],
        product["duty_rate_bps"] + product["vat_rate_bps"],
    )


def affects_for(movement_type, original=None):
    if movement_type in RESERVED_TYPES:
        return "RESERVED"
    if movement_type == "REVERSAL":
        return original["affects"]
    return "ON_HAND"


def bump_item(item):
    """One version increment per appending request, even with several entries."""
    bumped = getattr(g, "bumped_items", None)
    if bumped is None:
        db.touch(item)
        return
    if item["id"] in bumped:
        item["updated_at"] = clock.now_iso()
        return
    bumped.add(item["id"])
    db.touch(item)


def append(item, movement_type, qty_delta, source_ref_type, source_ref_id,
           posted_by_user_id, original=None):
    agreement = active_agreement(item["terminal_id"])
    movement = db.base(versioned=False)
    movement.update({
        "stock_item_id": item["id"],
        "movement_type": movement_type,
        "qty_delta": qty_delta,
        "affects": affects_for(movement_type, original),
        "reversal_of_movement_id": original["id"] if original is not None else None,
        "source_ref_type": source_ref_type,
        "source_ref_id": source_ref_id,
        "posted_by_user_id": posted_by_user_id,
        "agreement_period_code": agreement["period_code"] if agreement else None,
        "reversed": False,
    })
    db.movements[movement["id"]] = movement
    if original is not None:
        original["reversed"] = True
    derive(item)
    bump_item(item)
    return movement
