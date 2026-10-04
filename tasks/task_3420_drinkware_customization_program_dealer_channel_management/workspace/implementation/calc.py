"""Calculation rules (SCAFFOLD.yaml §1.3), ledgers, lazy transitions, cascades."""
import math
from calendar import monthrange
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from constants import (
    CHANGEOVER_BUFFER_MINUTES, COLOR_SURCHARGE_CENTS, CORPORATE_TIERS,
    PEAK_MULTIPLIER, PEAK_WINDOW_END, PEAK_WINDOW_START, PER_UNIT_MINUTES,
    PLACEMENT_SURCHARGE_CENTS, SETUP_FEE_CENTS, SETUP_WAIVER_QTY,
    TRAVEL_BUFFER_MINUTES,
)
from envelope import touch
from store import DB, get_clock


def dec(v):
    return Decimal(str(v))


def round_half_up_int(x):
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def in_peak(dt):
    """Half-open peak window membership (PRD §2.9)."""
    return PEAK_WINDOW_START <= dt < PEAK_WINDOW_END


def add_months(dt, months):
    """Calendar-month arithmetic; expiry lands at the same clock time on the
    expiry month-day (clamped to the month's last day when shorter)."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# customization_quote_cents — PROVISIONAL and FINAL share this body; callers
# supply the color/placement evidence and the peak probe result.
# ---------------------------------------------------------------------------

def compute_quote_cents(line, buyer_type, quantity, color_count, placement_count, peak):
    unit = (line["base_custom_price_cents"]
            + max(0, color_count - 1) * COLOR_SURCHARGE_CENTS
            + max(0, placement_count - 1) * PLACEMENT_SURCHARGE_CENTS)
    subtotal = quantity * unit
    rate = Decimal("0")
    if buyer_type == "CORPORATE":
        for threshold, r in CORPORATE_TIERS:
            if quantity >= threshold:
                rate = r
                break
    # ROUNDING ORDER PINNED: tier discount first ...
    discounted = round_half_up_int(dec(subtotal) * (Decimal("1") - rate))
    setup = 0 if quantity >= SETUP_WAIVER_QTY else SETUP_FEE_CENTS
    if peak:
        # ... then the peak multiplier.
        return round_half_up_int(dec(discounted + setup) * PEAK_MULTIPLIER)
    return discounted + setup


# ---------------------------------------------------------------------------
# Dealer standing
# ---------------------------------------------------------------------------

def dealer_infraction_points(dealer_id):
    """Live points: CONFIRMED_VIOLATION cases whose expiry is still ahead."""
    clock = get_clock()
    total = 0
    for c in DB.cases.values():
        if (c["matched_dealer_id"] == dealer_id
                and c["status"] == "CONFIRMED_VIOLATION"
                and c["infraction_expires_at"] is not None
                and clock < c["infraction_expires_at"]):
            total += c["infraction_points"]
    return total


def dealer_outstanding_balance(dealer_id):
    total = 0
    for a in DB.allocations.values():
        if a["dealer_id"] == dealer_id and a["status"] == "ALLOCATED":
            total += a["allocated_units"] * a["unit_price_cents"]
    return total


def dealer_allocation_score(dealer):
    """Season-variant weighted score, 2 decimals round-half-up."""
    sell = dec(dealer["sell_through_pct"])
    brand = dec(dealer["brand_presentation_score"])
    tenure = dec(dealer["tenure_years"])
    points = dealer_infraction_points(dealer["id"])
    if in_peak(get_clock()):
        score = dec("0.35") * sell + dec("0.45") * brand + 2 * tenure - 8 * points
    else:
        score = dec("0.50") * sell + dec("0.30") * brand + 2 * tenure - 5 * points
    return round2(score)


# ---------------------------------------------------------------------------
# Drop unit ledger (computed; invariants per PRD §2.10)
# ---------------------------------------------------------------------------

def dealer_committed_units(drop_id):
    return sum(a["allocated_units"] for a in DB.allocations.values()
               if a["drop_id"] == drop_id and a["status"] == "ALLOCATED")


def warranty_reserved_units(drop_id):
    n = 0
    for c in DB.claims.values():
        if (c["status"] == "APPROVED_REPLACEMENT"
                and c["replacement_colorway_resolution"] == "SAME_COLORWAY"
                and c["order_id"]):
            o = DB.orders.get(c["order_id"])
            if o is not None and o["colorway_drop_id"] == drop_id:
                n += 1
    return n


def drop_unallocated_units(drop):
    return (drop["total_units"] - drop["dtc_reserved_units"]
            - dealer_committed_units(drop["id"])
            - warranty_reserved_units(drop["id"]))


# ---------------------------------------------------------------------------
# Slot capacity ledger (computed)
# ---------------------------------------------------------------------------

def slot_booked_minutes(slot_id):
    return sum(o["reserved_minutes"] for o in DB.orders.values()
               if o["slot_id"] == slot_id
               and o["reservation_status"] in ("HELD", "CONFIRMED", "CONSUMED"))


def slot_available_minutes(slot):
    return slot["capacity_minutes"] - slot_booked_minutes(slot["id"])


# ---------------------------------------------------------------------------
# Lazy clock-driven transitions (PRD §2.4): re-evaluated on every read/write,
# no eager work, no version bumps.
# ---------------------------------------------------------------------------

def refresh_drop(drop):
    clock = get_clock()
    if drop["status"] == "ALLOCATION_LOCKED" and clock >= drop["go_live_at"]:
        drop["status"] = "LIVE"
    if drop["status"] == "LIVE" and clock >= drop["sales_end_at"]:
        drop["status"] = "CLOSED"


def refresh_slot(slot):
    if slot["status"] in ("OPEN", "LOCKED") and get_clock() >= slot["window_end"]:
        slot["status"] = "CLOSED"


# ---------------------------------------------------------------------------
# launch_allocation_distribution — pinned floor-then-cap largest remainder.
# ---------------------------------------------------------------------------

def run_launch_allocation_distribution(drop):
    pool = (drop["total_units"] - drop["dtc_reserved_units"]
            - warranty_reserved_units(drop["id"]))
    requested = [a for a in DB.allocations.values()
                 if a["drop_id"] == drop["id"] and a["status"] == "REQUESTED"]
    eligible = []
    for a in requested:
        dealer = DB.dealers.get(a["dealer_id"])
        if dealer is not None and dealer["status"] == "AUTHORIZED":
            eligible.append(a)
        else:
            a["status"] = "EXPIRED"
            touch(a)
    grants = {}
    if sum(a["requested_units"] for a in eligible) <= pool:
        for a in eligible:
            grants[a["id"]] = a["requested_units"]
    elif pool > 0:
        scores = {}
        weights = {}
        for a in eligible:
            s = dealer_allocation_score(DB.dealers[a["dealer_id"]])
            scores[a["id"]] = s
            weights[a["id"]] = s if s > Decimal("1") else Decimal("1")
        wsum = sum(weights.values())
        raws = {}
        for a in eligible:
            raws[a["id"]] = (Fraction(pool) * Fraction(str(weights[a["id"]]))
                             / Fraction(str(wsum)))
        base = {}
        for a in eligible:
            # ROUNDING ORDER PINNED: floor the raw share first, then cap.
            base[a["id"]] = min(a["requested_units"], math.floor(raws[a["id"]]))
        leftover = pool - sum(base.values())

        def rank_key(a):
            raw = raws[a["id"]]
            frac = raw - math.floor(raw)
            return (-frac, -scores[a["id"]], a["created_at"])

        ranked = sorted(eligible, key=rank_key)
        while leftover > 0:
            granted_this_pass = False
            for a in ranked:
                if leftover <= 0:
                    break
                if base[a["id"]] < a["requested_units"]:
                    base[a["id"]] += 1
                    leftover -= 1
                    granted_this_pass = True
            if not granted_this_pass:
                break
        grants = base
    for a in eligible:
        grant = grants.get(a["id"], 0)
        if grant > 0:
            a["allocated_units"] = grant
            a["status"] = "ALLOCATED"
        else:
            a["status"] = "EXPIRED"
        touch(a)


# ---------------------------------------------------------------------------
# Dealer suspension / termination allocation-forfeiture cascade.
# ---------------------------------------------------------------------------

def forfeit_allocations_for_dealer(dealer_id, reason):
    """REQUESTED/ALLOCATED allocations on drops not yet LIVE are forfeited.
    Every forfeiture increments the drop's version (PRD §2.6/§3.4)."""
    for a in list(DB.allocations.values()):
        if a["dealer_id"] != dealer_id or a["status"] not in ("REQUESTED", "ALLOCATED"):
            continue
        drop = DB.drops.get(a["drop_id"])
        if drop is None:
            continue
        refresh_drop(drop)
        if drop["status"] not in ("ANNOUNCED", "ALLOCATION_OPEN", "ALLOCATION_LOCKED"):
            continue
        a["status"] = "FORFEITED"
        a["forfeit_reason"] = reason
        touch(a)
        touch(drop)


# ---------------------------------------------------------------------------
# Waitlist promotion (selector policy)
# ---------------------------------------------------------------------------

def promote_waitlist(slot):
    candidates = [o for o in DB.orders.values()
                  if o["slot_id"] == slot["id"]
                  and o["reservation_status"] == "WAITLISTED"
                  and o["order_state"] == "ACTIVE"
                  and (not slot["peak_overlap"] or o["artwork_status"] == "ART_APPROVED")]
    candidates.sort(key=lambda o: (o["requested_ship_date"], o["created_at"]))
    for o in candidates:
        if o["reserved_minutes"] <= slot_available_minutes(slot):
            o["reservation_status"] = "HELD"
            o["schedule_status"] = "RESERVED"
            if o["artwork_status"] == "ART_APPROVED":
                o["reservation_status"] = "CONFIRMED"
                o["schedule_status"] = "CONFIRMED"
            touch(o)


# ---------------------------------------------------------------------------
# Interval checks
# ---------------------------------------------------------------------------

def slot_overlap_conflict(station_code, technology, start, end):
    """Half-open [start, end) windows on one station: same technology rejects
    genuine intersection (touching endpoints allowed); different technologies
    additionally need a 20-minute changeover gap on both sides."""
    buffer = timedelta(minutes=CHANGEOVER_BUFFER_MINUTES)
    for s in DB.slots.values():
        if s["station_code"] != station_code:
            continue
        if s["technology"] == technology:
            if start < s["window_end"] and s["window_start"] < end:
                return True
        else:
            if start < s["window_end"] + buffer and s["window_start"] < end + buffer:
                return True
    return False


def inspector_schedule_conflict(inspector_user_id, start, end, exclude_app_id=None):
    """Closed intervals [start, end]: shared endpoints conflict outright, and
    consecutive windows need a 60-minute travel buffer. Only SCHEDULED
    applications occupy the inspector's calendar."""
    buffer = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    for app in DB.applications.values():
        if app["inspector_user_id"] != inspector_user_id:
            continue
        if app["inspection_status"] != "SCHEDULED":
            continue
        if exclude_app_id is not None and app["id"] == exclude_app_id:
            continue
        ws = app["inspection_window_start"]
        we = app["inspection_window_end"]
        if start <= we and ws <= end:
            return True
        if start > we:
            if start - we < buffer:
                return True
        else:
            if ws - end < buffer:
                return True
    return False


# ---------------------------------------------------------------------------
# Peak probes for the two quote variants
# ---------------------------------------------------------------------------

def peak_probe_provisional(order):
    return in_peak(order["requested_ship_date"])


def peak_probe_final(order):
    if order["reservation_status"] in ("HELD", "WAITLISTED", "CONFIRMED") and order["slot_id"]:
        slot = DB.slots.get(order["slot_id"])
        if slot is not None:
            return slot["peak_overlap"]
    return peak_probe_provisional(order)
