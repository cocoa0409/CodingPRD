"""Record serialization.

Each serializer emits exactly the field set the scaffold declares for that
entity, plus the four common fields (id, created_at, updated_at, version).
Internal bookkeeping keys (those beginning with "_") are never emitted.

Two PRD-only computed additions ride along on their documented reads:
  * `delta_cents` on a clearance schedule read — "the read of a clearance
    schedule exposes the difference between the two as a discount delta,
    delta_cents, equal to the effective price minus the compounded price
    rounded down to a whole cent" (PRD 2.9).
  * `item_active_price_by_region_cents` on the same read (PRD 3.8).
  * `retail_share_cents` on a guest check, the counterpart of
    restaurant_share_cents that PRD 3.2 says "are both exposed by the day's
    revenue-attribution read".
"""

import db
from calculations import (margin_floor_cents, projected_import_need,
                          unit_margin_cents)


def _common(rec, extra=None):
    out = {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }
    for key, value in rec.items():
        if key.startswith("_") or key in out:
            continue
        out[key] = value
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------

def brand(rec):
    return _common(rec)


def location(rec):
    return _common(rec)


def store_day(rec):
    return _common(rec)


def item(rec):
    return _common(rec)


def planogram_version(rec):
    return _common(rec)


def planogram_slot(rec):
    return _common(rec)


def guest_check(rec):
    parts = db.to_dec(rec.get("restaurant_subtotal_cents"))
    parts += db.to_dec(rec.get("retail_subtotal_cents"))
    restaurant_share = db.cents(
        db.to_dec(rec.get("total_cents")) * db.to_dec(rec.get("restaurant_subtotal_cents"))
        / parts) if parts > 0 else 0
    return _common(rec, {"retail_share_cents": rec.get("total_cents", 0) - restaurant_share})


def receipt(rec):
    return _common(rec)


def clearance_schedule(rec):
    item_rec = db.items.get(rec.get("item_id"))
    delta = 0
    active_price = rec.get("liquidation_price_cents", 0)
    if item_rec is not None:
        delta = db.floor_int(
            db.to_dec(item_rec.get("effective_price_cents"))
            - db.to_dec(item_rec.get("compounded_price_cents")))
        active_price = item_rec.get("effective_price_cents", 0)
    return _common(rec, {
        "delta_cents": delta,
        "item_active_price_by_region_cents": active_price,
    })


def staff_shift(rec):
    return _common(rec)


def transfer(rec):
    return _common(rec)


def capacity_reading(rec):
    return _common(rec)


# ---------------------------------------------------------------------------
# Computed read payloads
# ---------------------------------------------------------------------------

def import_plan(item_rec):
    """GET /items/{id}/import-plan — PRD 3.9."""
    return {
        "projected_import_need_units": projected_import_need(item_rec),
        "order_deadline_reached": db.items[item_rec["id"]].get("order_deadline_reached", False),
        "unit_margin_cents": unit_margin_cents(item_rec),
        "margin_floor_cents": margin_floor_cents(item_rec),
    }


def region_fit(version_rec):
    """GET /planogram-versions/{id}/region-fit — PRD 3.9."""
    from calculations import region_fit_values
    return region_fit_values(version_rec)


def transfer_discrepancy(transfer_rec):
    """GET /transfers/{id}/discrepancy — PRD 3.7."""
    brand_rec = db.brands.get(db.locations[transfer_rec["location_id"]]["brand_id"])
    location_rec = db.locations.get(transfer_rec["location_id"])
    tolerance = brand_rec.get("transfer_variance_tolerance_bps", 200) if brand_rec else 200
    return {
        "variance_units": transfer_rec.get("variance_units", 0),
        "variance_bps": transfer_rec.get("variance_bps", 0),
        "tolerance_bps": tolerance,
        "within_tolerance": transfer_rec.get("variance_bps", 0) <= tolerance,
        "conserved_backroom_units": (location_rec.get("backroom_occupancy_units", 0)
                                     + location_rec.get("backroom_committed_units", 0)),
    }


def revenue_attribution(store_day_id, variant=None):
    """GET /revenue-attribution — PRD 3.9 / 3.2."""
    day = db.store_days.get(store_day_id)
    receipts = [r for r in db.receipts.values() if r.get("store_day_id") == store_day_id]
    provisional = sum(r.get("provisional_retail_cents", 0) for r in receipts)
    recognized = sum(r.get("recognized_retail_cents", 0) for r in receipts)
    # PRD 3.9: the read is "the same variant pair that 3.4 defines, presented as
    # one reconciled view of the day rather than as a per-ticket figure", so the
    # delta is carried from the tickets rather than recomputed here — under
    # FINAL_ONLY it is zero even though the two sums differ.
    delta = sum(r.get("recognition_delta_cents", 0) for r in receipts)

    restaurant_share = 0
    retail_share = 0
    for r in receipts:
        check_id = r.get("guest_check_id")
        if not check_id:
            continue
        check = db.guest_checks.get(check_id)
        if check is None:
            continue
        parts = check.get("restaurant_subtotal_cents", 0) + check.get("retail_subtotal_cents", 0)
        if parts <= 0:
            continue
        share = db.cents(db.to_dec(check.get("total_cents")) * db.to_dec(check.get("restaurant_subtotal_cents"))
                         / db.to_dec(parts))
        restaurant_share += share
        retail_share += check.get("total_cents", 0) - share

    return {
        "store_day_id": store_day_id,
        "provisional_retail_cents": provisional,
        "recognized_retail_cents": recognized,
        "recognition_delta_cents": delta,
        "restaurant_share_cents": restaurant_share,
        "retail_share_cents": retail_share,
        "receipt_count": len(receipts),
    }