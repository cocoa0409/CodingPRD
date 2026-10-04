"""Business logic: calculations, cascades, serialization (PRD §2.6-§3)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import errors

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TARE_TABLE = {"BAG_50": 2, "DRUM": 20, "TOTE": 60, "CYLINDER_20": 17}
FEED_TIER1_LIMIT, FEED_TIER1_RATE = 50, 40
FEED_TIER2_LIMIT, FEED_TIER2_RATE = 150, 35
FEED_TIER3_RATE = 30
PROPANE_LBS_PER_GAL = Decimal("4.24")
PROPANE_MAX_GAL = Decimal("20.0")
PROPANE_FLAT_CENTS = 1999
PROPANE_PER_GAL_CENTS = 349
HAZMAT_DAILY_CAP_GAL = Decimal("40")

MORTALITY_QUARANTINE_RATE = Decimal("0.05")
QUARANTINE_GOODWILL_POINTS = 500

TIER_MULT = {"NEIGHBOR": Decimal("1.0"), "RANCH_HAND": Decimal("1.25"), "HOMESTEAD": Decimal("1.5")}
TIER_RANCH_HAND_THRESHOLD = 2500
TIER_HOMESTEAD_THRESHOLD = 7500
TIER_WINDOW_DAYS = 365

FUEL_POINTS_STEP = 500
FUEL_CENTS_PER_STEP = 5
FUEL_MAX_CENTS_PER_GAL = 50
FEED_COUPON_CENTS = 1000

SIZE_ORDER = {"M": 0, "L": 1, "XL": 2}
SANITIZATION_GAP = timedelta(days=7)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def parse_iso(value, field):
    if not isinstance(value, str):
        raise errors.err_invalid_request(f"{field} must be an ISO8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
    except ValueError:
        raise errors.err_invalid_request(f"{field} is not a valid ISO8601 timestamp")
    return dt


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.err_invalid_request(f"{field} is required and must be a string")
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise errors.err_invalid_request(f"{field} must be a string")
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if not isinstance(v, str) or v not in values:
        raise errors.err_invalid_request(f"{field} must be one of {sorted(values)}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_int(data, field, minimum=None):
    v = data.get(field)
    if not _is_int(v):
        raise errors.err_invalid_request(f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err_invalid_request(f"{field} must be >= {minimum}")
    return v


def req_num(data, field, gt=None):
    v = data.get(field)
    if not _is_num(v):
        raise errors.err_invalid_request(f"{field} is required and must be a number")
    if gt is not None and not v > gt:
        raise errors.err_invalid_request(f"{field} must be > {gt}")
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise errors.err_invalid_request(f"{field} is required and must be a boolean")
    return v


def opt_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise errors.err_invalid_request(f"{field} must be a boolean")
    return v


def round_half_up_int(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def decimal_of(v):
    return Decimal(str(v))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def serialize_store(s):
    return {
        "id": s["id"],
        "store_name": s["store_name"],
        "region_code": s["region_code"],
        "posture": s["posture"],
        "active_campaign_id": s["active_campaign_id"],
        "hazmat_gallons_used_today": hazmat_gallons_used_today(s),
        "created_at": db.fmt_ts(s["created_at"]),
        "updated_at": db.fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def serialize_campaign(c):
    return {
        "id": c["id"],
        "store_id": c["store_id"],
        "season": c["season"],
        "planogram_map": c["planogram_map"],
        "aisle_count": c["aisle_count"],
        "aisles_reset_count": c["aisles_reset_count"],
        "activated_at": db.fmt_ts(c["activated_at"]),
        "status": c["status"],
        "created_at": db.fmt_ts(c["created_at"]),
        "updated_at": db.fmt_ts(c["updated_at"]),
        "version": c["version"],
    }


def serialize_bay(b):
    return {
        "id": b["id"],
        "store_id": b["store_id"],
        "bay_no": b["bay_no"],
        "size_class": b["size_class"],
        "status": b["status"],
        "created_at": db.fmt_ts(b["created_at"]),
        "updated_at": db.fmt_ts(b["updated_at"]),
        "version": b["version"],
    }


def serialize_schedule(s):
    return {
        "id": s["id"],
        "store_id": s["store_id"],
        "species": s["species"],
        "breed": s["breed"],
        "hatch_date": db.fmt_ts(s["hatch_date"]),
        "sale_window_start": db.fmt_ts(s["sale_window_start"]),
        "sale_window_end": db.fmt_ts(s["sale_window_end"]),
        "daily_capacity": s["daily_capacity"],
        "min_purchase_qty": s["min_purchase_qty"],
        "base_price_cents_per_bird": s["base_price_cents_per_bird"],
        "status": s["status"],
        "created_at": db.fmt_ts(s["created_at"]),
        "updated_at": db.fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def serialize_lot(l):
    return {
        "id": l["id"],
        "store_id": l["store_id"],
        "hatchery_schedule_id": l["hatchery_schedule_id"],
        "quantity_received": l["quantity_received"],
        "received_at": db.fmt_ts(l["received_at"]),
        "quantity_on_hand": l["quantity_on_hand"],
        "quantity_sold": l["quantity_sold"],
        "mortality_count": l["mortality_count"],
        "quantity_quarantined": l["quantity_quarantined"],
        "mortality_rate": float(l["mortality_rate"]),
        "health_flag": l["health_flag"],
        "status": l["status"],
        "created_at": db.fmt_ts(l["created_at"]),
        "updated_at": db.fmt_ts(l["updated_at"]),
        "version": l["version"],
    }


def serialize_care_log(e):
    return {
        "id": e["id"],
        "lot_id": e["lot_id"],
        "entry_type": e["entry_type"],
        "measured_temp_f": e["measured_temp_f"],
        "mortality_count": e["mortality_count"],
        "note": e["note"],
        "created_at": db.fmt_ts(e["created_at"]),
    }


def serialize_chick_order(o):
    return {
        "id": o["id"],
        "store_id": o["store_id"],
        "livestock_lot_id": o["livestock_lot_id"],
        "loyalty_account_id": o["loyalty_account_id"],
        "quantity": o["quantity"],
        "pickup_date": db.fmt_ts(o["pickup_date"]),
        "unit_price_cents": o["unit_price_cents"],
        "discount_pct": float(o["discount_pct"]),
        "total_cents": o["total_cents"],
        "brooder_verified_at": db.fmt_ts(o["brooder_verified_at"]),
        "fulfilled_at": db.fmt_ts(o["fulfilled_at"]),
        "claim_status": o["claim_status"],
        "claimed_mortality_count": o["claimed_mortality_count"],
        "approved_claim_count": o["approved_claim_count"],
        "refund_cents": o["refund_cents"],
        "status": o["status"],
        "created_at": db.fmt_ts(o["created_at"]),
        "updated_at": db.fmt_ts(o["updated_at"]),
        "version": o["version"],
    }


def serialize_weighted_sale(s):
    return {
        "id": s["id"],
        "store_id": s["store_id"],
        "loyalty_account_id": s["loyalty_account_id"],
        "sale_kind": s["sale_kind"],
        "container_class": s["container_class"],
        "gross_weight_lbs": s["gross_weight_lbs"],
        "provisional_tare_lbs": s["provisional_tare_lbs"],
        "measured_tare_lbs": s["measured_tare_lbs"],
        "provisional_total_cents": s["provisional_total_cents"],
        "final_total_cents": s["final_total_cents"],
        "propane_gallons": float(s["propane_gallons"]),
        "redeem_points": s["redeem_points"],
        "points_redeemed": s["points_redeemed"],
        "finalized_at": db.fmt_ts(s["finalized_at"]),
        "status": s["status"],
        "created_at": db.fmt_ts(s["created_at"]),
        "updated_at": db.fmt_ts(s["updated_at"]),
        "version": s["version"],
    }


def serialize_account(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "phone": a["phone"],
        "email": a["email"],
        "status": a["status"],
        "tier": a["tier"],
        "points_balance": a["points_balance"],
        "tier_qualifying_points": a["tier_qualifying_points"],
        "created_at": db.fmt_ts(a["created_at"]),
        "updated_at": db.fmt_ts(a["updated_at"]),
        "version": a["version"],
    }


def serialize_ledger_entry(e):
    return {
        "id": e["id"],
        "account_id": e["account_id"],
        "entry_type": e["entry_type"],
        "store_id": e["store_id"],
        "base_amount_cents": e["base_amount_cents"],
        "earn_context": e["earn_context"],
        "points_delta": e["points_delta"],
        "related_entry_id": e["related_entry_id"],
        "counts_toward_tier": e["counts_toward_tier"],
        "posture_at_entry": e["posture_at_entry"],
        "created_at": db.fmt_ts(e["created_at"]),
    }


def serialize_pickup_order(o):
    return {
        "id": o["id"],
        "store_id": o["store_id"],
        "loyalty_account_id": o["loyalty_account_id"],
        "item_sku": o["item_sku"],
        "item_size_class": o["item_size_class"],
        "requires_loadout_assistance": o["requires_loadout_assistance"],
        "staging_bay_id": o["staging_bay_id"],
        "ready_at": db.fmt_ts(o["ready_at"]),
        "pickup_deadline": db.fmt_ts(o["pickup_deadline"]),
        "fulfillment_status": o["fulfillment_status"],
        "loadout_status": o["loadout_status"],
        "created_at": db.fmt_ts(o["created_at"]),
        "updated_at": db.fmt_ts(o["updated_at"]),
        "version": o["version"],
    }


def derive_event_status(e):
    """Read-time derivation: PUBLISHED event completes once past window end
    with no BOOKED or CHECKED_IN bookings remaining (PRD §3.9)."""
    if e["status"] != "PUBLISHED":
        return e["status"]
    now = db.now()
    if now > e["slot_window_end"]:
        for b in db.event_bookings.values():
            if b["service_event_id"] == e["id"] and b["status"] in ("BOOKED", "CHECKED_IN"):
                return e["status"]
        return "COMPLETED"
    return e["status"]


def serialize_event(e):
    return {
        "id": e["id"],
        "store_id": e["store_id"],
        "event_kind": e["event_kind"],
        "resource_name": e["resource_name"],
        "event_date": db.fmt_ts(e["event_date"]),
        "slot_window_start": db.fmt_ts(e["slot_window_start"]),
        "slot_window_end": db.fmt_ts(e["slot_window_end"]),
        "slot_length_minutes": e["slot_length_minutes"],
        "cleanup_buffer_minutes": e["cleanup_buffer_minutes"],
        "capacity_per_slot": e["capacity_per_slot"],
        "requires_vaccine_record": e["requires_vaccine_record"],
        "status": derive_event_status(e),
        "created_at": db.fmt_ts(e["created_at"]),
        "updated_at": db.fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def serialize_booking(b):
    return {
        "id": b["id"],
        "service_event_id": b["service_event_id"],
        "loyalty_account_id": b["loyalty_account_id"],
        "slot_start": db.fmt_ts(b["slot_start"]),
        "slot_end": db.fmt_ts(b["slot_end"]),
        "vaccine_record_confirmed": b["vaccine_record_confirmed"],
        "status": b["status"],
        "created_at": db.fmt_ts(b["created_at"]),
        "updated_at": db.fmt_ts(b["updated_at"]),
        "version": b["version"],
    }


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_store(sid):
    s = db.stores.get(sid)
    if s is None:
        raise errors.err_not_found("ERR_STORE_NOT_FOUND", "store")
    return s


def get_campaign(cid):
    c = db.campaigns.get(cid)
    if c is None:
        raise errors.err_not_found("ERR_CAMPAIGN_NOT_FOUND", "campaign")
    return c


def get_bay(bid):
    b = db.bays.get(bid)
    if b is None:
        raise errors.err_not_found("ERR_BAY_NOT_FOUND", "staging bay")
    return b


def get_schedule(sid):
    s = db.schedules.get(sid)
    if s is None:
        raise errors.err_not_found("ERR_SCHEDULE_NOT_FOUND", "hatchery schedule")
    return s


def get_lot(lid):
    l = db.lots.get(lid)
    if l is None:
        raise errors.err_not_found("ERR_LOT_NOT_FOUND", "livestock lot")
    return l


def get_chick_order(oid):
    o = db.chick_orders.get(oid)
    if o is None:
        raise errors.err_not_found("ERR_ORDER_NOT_FOUND", "chick order")
    return o


def get_sale(sid):
    s = db.weighted_sales.get(sid)
    if s is None:
        raise errors.err_not_found("ERR_SALE_NOT_FOUND", "weighted sale")
    return s


def get_account(aid):
    a = db.loyalty_accounts.get(aid)
    if a is None:
        raise errors.err_not_found("ERR_ACCOUNT_NOT_FOUND", "loyalty account")
    return a


def get_entry(eid):
    e = db.ledger_entries.get(eid)
    if e is None:
        raise errors.err_not_found("ERR_ENTRY_NOT_FOUND", "ledger entry")
    return e


def get_pickup_order(oid):
    o = db.pickup_orders.get(oid)
    if o is None:
        raise errors.err_not_found("ERR_PICKUP_NOT_FOUND", "pickup order")
    return o


def get_event(eid):
    e = db.service_events.get(eid)
    if e is None:
        raise errors.err_not_found("ERR_EVENT_NOT_FOUND", "service event")
    return e


def get_booking(bid):
    b = db.event_bookings.get(bid)
    if b is None:
        raise errors.err_not_found("ERR_BOOKING_NOT_FOUND", "event booking")
    return b


# ---------------------------------------------------------------------------
# Store computed state
# ---------------------------------------------------------------------------
def hazmat_gallons_used_today(store):
    today = db.now().date()
    total = Decimal("0")
    for s in db.weighted_sales.values():
        if (s["store_id"] == store["id"]
                and s["sale_kind"] == "PROPANE_EXCHANGE"
                and s["status"] == "FINALIZED"
                and s["finalized_at"] is not None
                and s["finalized_at"].date() == today):
            total += s["propane_gallons"]
    return float(total)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def _release_order_reservation(order, lot, cause):
    """Release a RESERVED|BROODER_VERIFIED order. cause: 'closure' | 'quarantine'."""
    lot_changed = False
    if cause == "quarantine":
        order["status"] = "CANCELLED"
        lot["quantity_quarantined"] += order["quantity"]
        lot_changed = True
        acct = db.loyalty_accounts.get(order["loyalty_account_id"])
        if acct is not None:
            post_ledger_entry(
                account=acct,
                entry_type="ADJUSTMENT",
                points_delta=QUARANTINE_GOODWILL_POINTS,
                store_id=None,
            )
    else:  # closure -> EXPIRED, back to on-hand
        order["status"] = "EXPIRED"
        lot["quantity_on_hand"] += order["quantity"]
        lot_changed = True
    db.touch(order)
    if lot_changed:
        db.touch(lot)


def close_lot_cascade(lot, disposition=False):
    """ON_SALE -> SALE_CLOSED (orders expire) or SALE_CLOSED -> DISPOSITIONED."""
    if lot["status"] == "ON_SALE":
        for o in db.chick_orders.values():
            if o["livestock_lot_id"] == lot["id"] and o["status"] in ("RESERVED", "BROODER_VERIFIED"):
                _release_order_reservation(o, lot, cause="closure")
        lot["status"] = "SALE_CLOSED"
        db.touch(lot)
    elif lot["status"] == "SUSPENDED":
        if disposition:
            raise errors.err_invalid_state_transition(
                "disposition requires lot SALE_CLOSED")
        lot["status"] = "SALE_CLOSED"
        db.touch(lot)
    elif lot["status"] == "SALE_CLOSED":
        if disposition:
            lot["status"] = "DISPOSITIONED"
            db.touch(lot)
        else:
            raise errors.err_invalid_state_transition("lot is already SALE_CLOSED")
    else:
        raise errors.err_invalid_state_transition("lot cannot be closed from its state")


def close_schedule_cascade(schedule):
    """PUBLISHED -> CLOSED; cascade lots -> SALE_CLOSED -> orders EXPIRED."""
    schedule["status"] = "CLOSED"
    db.touch(schedule)
    for lot in db.lots.values():
        if lot["hatchery_schedule_id"] == schedule["id"] and lot["status"] == "ON_SALE":
            close_lot_cascade(lot)


def posture_cascade_on_activation(store, campaign):
    """PRD §3.1 five-hop cascade (atomic in this request)."""
    # hop1: supersede prior ACTIVE campaign
    for c in db.campaigns.values():
        if c["store_id"] == store["id"] and c["status"] == "ACTIVE" and c["id"] != campaign["id"]:
            c["status"] = "COMPLETED"
            db.touch(c)
    # hop2: recompute store posture
    store["posture"] = campaign["season"]
    store["active_campaign_id"] = campaign["id"]
    db.touch(store)
    # hop3-5: non-spring posture tears down live poultry sales
    if campaign["season"] != "SPRING_PLANTING":
        for s in list(db.schedules.values()):
            if s["store_id"] == store["id"] and s["status"] == "PUBLISHED":
                close_schedule_cascade(s)


# ---------------------------------------------------------------------------
# Loyalty
# ---------------------------------------------------------------------------
def compute_accrual_points(account, base_amount_cents, earn_context, store):
    """PRD §3.7 pinned order: base -> tier snapshot -> posture mult -> round."""
    base_points = base_amount_cents // 100
    if base_points <= 0:
        # PRD §3.7 requires base_amount_cents > 0 for ACCRUAL; a system-driven
        # accrual whose floored base is 0 points earns nothing.
        return 0
    tier_mult = TIER_MULT[account["tier"]]
    posture_mult = Decimal("2.0") if (
        earn_context == "FEED" and store is not None and store["posture"] == "FALL_FEED"
    ) else Decimal("1.0")
    points = Decimal(base_points) * tier_mult * posture_mult
    return round_half_up_int(points)


def recompute_account(account):
    """Recompute points_balance and rolling-365 tier after a ledger write."""
    entries = [e for e in db.ledger_entries.values() if e["account_id"] == account["id"]]
    account["points_balance"] = sum(e["points_delta"] for e in entries)
    now = db.now()
    window_start = now - timedelta(days=TIER_WINDOW_DAYS)
    qualifying = sum(
        e["points_delta"] for e in entries
        if e["counts_toward_tier"] and window_start <= e["created_at"] <= now
    )
    account["tier_qualifying_points"] = qualifying
    if qualifying >= TIER_HOMESTEAD_THRESHOLD:
        account["tier"] = "HOMESTEAD"
    elif qualifying >= TIER_RANCH_HAND_THRESHOLD:
        account["tier"] = "RANCH_HAND"
    else:
        account["tier"] = "NEIGHBOR"
    db.touch(account)


def post_ledger_entry(account, entry_type, points_delta=None, store_id=None,
                      base_amount_cents=None, earn_context=None, related_entry_id=None):
    """Append a LoyaltyLedgerEntry and re-evaluate the account. Internal use:
    fields are already validated/computed by the caller."""
    store = db.stores.get(store_id) if store_id else None
    if entry_type == "ACCRUAL":
        points_delta = compute_accrual_points(account, base_amount_cents, earn_context, store)
    entry = {
        "id": db.new_id(),
        "account_id": account["id"],
        "entry_type": entry_type,
        "store_id": store_id,
        "base_amount_cents": base_amount_cents,
        "earn_context": earn_context,
        "points_delta": points_delta,
        "related_entry_id": related_entry_id,
        "counts_toward_tier": entry_type in ("ACCRUAL", "REVERSAL"),
        "posture_at_entry": store["posture"] if store else "OFFSEASON",
        "created_at": db.now(),
    }
    db.ledger_entries[entry["id"]] = entry
    recompute_account(account)
    return entry


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def weighted_sale_price(sale_kind, gross_weight_lbs, tare_lbs):
    """Tier/gallon pricing shared by provisional and final variants.
    Returns (price_cents:int, propane_gallons:Decimal)."""
    net_lbs = decimal_of(gross_weight_lbs) - decimal_of(tare_lbs)
    gallons = Decimal("0")
    if sale_kind == "FEED_BULK":
        t1 = min(net_lbs, Decimal(FEED_TIER1_LIMIT)) * FEED_TIER1_RATE
        t2 = min(max(net_lbs - Decimal(FEED_TIER1_LIMIT), Decimal(0)),
                 Decimal(FEED_TIER2_LIMIT)) * FEED_TIER2_RATE
        t3 = max(net_lbs - Decimal(FEED_TIER1_LIMIT + FEED_TIER2_LIMIT), Decimal(0)) * FEED_TIER3_RATE
        price = t1 + t2 + t3
    else:  # PROPANE_EXCHANGE
        gallons = min(net_lbs / PROPANE_LBS_PER_GAL, PROPANE_MAX_GAL)
        gallons = gallons.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        price = Decimal(PROPANE_FLAT_CENTS) + (gallons * PROPANE_PER_GAL_CENTS).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
    return round_half_up_int(price), gallons


def chick_order_total(quantity, unit_price_cents):
    if quantity >= 50:
        discount = Decimal("0.15")
    elif quantity >= 25:
        discount = Decimal("0.10")
    else:
        discount = Decimal("0.00")
    total = Decimal(quantity) * Decimal(unit_price_cents) * (Decimal(1) - discount)
    return discount, round_half_up_int(total)


def staging_bay_selection(store_id, item_size_class):
    """Smallest sufficient AVAILABLE bay; tie-break bay_no ASC."""
    need = SIZE_ORDER[item_size_class]
    eligible = [
        b for b in db.bays.values()
        if b["store_id"] == store_id
        and b["status"] == "AVAILABLE"
        and SIZE_ORDER[b["size_class"]] >= need
    ]
    if not eligible:
        raise errors.err_no_staging_bay()
    eligible.sort(key=lambda b: (SIZE_ORDER[b["size_class"]], b["bay_no"]))
    return eligible[0]


def schedule_window_gap_check(candidate):
    for other in db.schedules.values():
        if (other["id"] != candidate["id"]
                and other["store_id"] == candidate["store_id"]
                and other["species"] == candidate["species"]
                and other["status"] == "PUBLISHED"):
            ok = (candidate["sale_window_start"] >= other["sale_window_end"] + SANITIZATION_GAP
                  or candidate["sale_window_end"] + SANITIZATION_GAP <= other["sale_window_start"])
            if not ok:
                raise errors.err_schedule_window_overlap()


def event_booking_overlap_check(event, slot_start, slot_end):
    """Overlap across all same-store events sharing resource_name."""
    relevant_event_ids = {
        e["id"] for e in db.service_events.values()
        if e["store_id"] == event["store_id"] and e["resource_name"] == event["resource_name"]
    }
    occupying = [
        b for b in db.event_bookings.values()
        if b["service_event_id"] in relevant_event_ids
        and b["status"] in ("BOOKED", "CHECKED_IN")
    ]
    if event["event_kind"] == "PET_WASH":
        overlapping = [
            b for b in occupying
            if b["slot_start"] < slot_end and slot_start < b["slot_end"]
        ]
        if len(overlapping) >= event["capacity_per_slot"]:
            raise errors.err_booking_overlap()
    else:  # VET_CLINIC: buffered occupancy, capacity 1
        buf = timedelta(minutes=event["cleanup_buffer_minutes"])
        c_start, c_end = slot_start - buf, slot_end + buf
        for b in occupying:
            b_start = b["slot_start"] - buf
            b_end = b["slot_end"] + buf
            if b_start < c_end and c_start < b_end:
                raise errors.err_booking_overlap()
