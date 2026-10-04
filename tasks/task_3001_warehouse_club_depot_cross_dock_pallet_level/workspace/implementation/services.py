"""Business logic: calculations, cascades, state-machine side effects.

All constants come from SCAFFOLD.yaml / PRD.md.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from helpers import (
    now_ts, current_date, touch, round_half_up_int, round_half_up_2,
)

# ---- constants (scaffold calculations tables) ----
STANDARD_SLOT_LENGTH_IN = 48
STANDARD_SLOT_WIDTH_IN = 40

MEMBER_BASE_CAP = 200000
DEMO_WEIGHT = 0.5
INCOME_CAP_CENTS = 20000000
INCOME_WEIGHT = 0.3
VELOCITY_BASE = 10
WINDOW_DAYS_REGULAR = 7
WINDOW_DAYS_TREASURE_HUNT = 3

PER_PALLET_FEE_CENTS = 4500
SMALL_LOAD_THRESHOLD = 10
MID_LOAD_THRESHOLD = 25

CHARGEBACK_BASE = {"LATE_CHECKIN": 15000, "NO_SHOW": 75000, "OVER_PALLET_COUNT": 25000}
PER_EXTRA_PALLET_CENTS = 6000
REPEAT_CAP = 4
REPEAT_STEP = 0.25
LATE_GRACE_MINUTES = 15
APPEAL_WINDOW_DAYS = 7

CONSTRAINED_THRESHOLD_PCT = 80

WEIGHT_BY_CATEGORY = {"SAFETY": 4.0, "QUALITY": 2.0, "AVAILABILITY": 1.5, "PRICING": 1.0}
COMPLAINT_WINDOW_DAYS = 30
COMPLAINT_DISCONTINUE_THRESHOLD = 25.0

COMPLIANCE_SUSPEND_THRESHOLD_BP = 8500
PERFECT_SCORE_BP = 10000
PENALTY_BY_REASON = {"LATE_CHECKIN": 250, "NO_SHOW": 600, "OVER_PALLET_COUNT": 400}


# ---------------------------------------------------------------- items
def compute_pallet_fields(item):
    item["pallet_qty_units"] = item["case_pack_qty"] * item["cases_per_layer"] * item["max_layers"]
    slot_area = Decimal(STANDARD_SLOT_LENGTH_IN * STANDARD_SLOT_WIDTH_IN)
    footprint = (Decimal(str(item["pallet_length_in"])) * Decimal(str(item["pallet_width_in"]))).quantize(
        Decimal("0.01"))
    item["pallets_per_slot"] = 1 if footprint <= slot_area else 2


# ---------------------------------------------------------------- clubs
def recompute_club_posture(club):
    threshold = (club["floor_slot_capacity"] * CONSTRAINED_THRESHOLD_PCT) // 100
    if club["allocated_slot_count"] >= club["floor_slot_capacity"]:
        new = "FROZEN"
    elif club["allocated_slot_count"] > threshold:
        new = "CONSTRAINED"
    else:
        new = "NORMAL"
    if new != club["posture"]:
        club["posture"] = new


# ---------------------------------------------------------------- chargebacks
def _trailing_confirmed_chargebacks(vendor_id, days=90):
    """CONFIRMED chargebacks for vendor assessed within trailing `days` inclusive
    of the current logical date."""
    today = current_date()
    out = []
    for cb in db.stores["chargebacks"].values():
        if cb["vendor_id"] != vendor_id or cb["status"] != "CONFIRMED":
            continue
        cb_date = date.fromisoformat(cb["assessed_at"][:10])
        age = (today - cb_date).days
        if 0 <= age <= days:
            out.append(cb)
    return out


def compute_chargeback_amount(reason, appointment, received_count):
    base = CHARGEBACK_BASE[reason]
    per_pallet = 0
    if reason == "OVER_PALLET_COUNT":
        extra = max(0, received_count - appointment["pallet_count"])
        per_pallet = extra * PER_EXTRA_PALLET_CENTS
    prior_confirmed = len(_trailing_confirmed_chargebacks(appointment["vendor_id"], 90))
    repeat_multiplier = 1 + min(prior_confirmed, REPEAT_CAP) * REPEAT_STEP
    return round_half_up_int(Decimal(str(base + per_pallet)) * Decimal(str(repeat_multiplier)))


def create_chargeback(vendor_id, appointment_id, reason, amount):
    from helpers import new_entity
    cb = new_entity({
        "vendor_id": vendor_id,
        "appointment_id": appointment_id,
        "amount_cents": amount,
        "reason": reason,
        "status": "ASSESSED",
        "assessed_at": now_ts(),
    })
    db.stores["chargebacks"][cb["id"]] = cb
    return cb


def recompute_vendor_compliance(vendor):
    today = current_date()
    total_decay = 0
    for cb in _trailing_confirmed_chargebacks(vendor["id"], 90):
        cb_date = date.fromisoformat(cb["assessed_at"][:10])
        age = (today - cb_date).days
        bucket = 0 if age <= 30 else (1 if age <= 60 else 2)
        total_decay += PENALTY_BY_REASON[cb["reason"]] >> bucket
    vendor["compliance_score_bp"] = max(0, PERFECT_SCORE_BP - total_decay)
    touch(vendor)


def confirm_chargeback(cb):
    """Shared side effects for a chargeback reaching CONFIRMED."""
    cb["status"] = "CONFIRMED"
    touch(cb)
    vendor = db.stores["vendors"][cb["vendor_id"]]
    vendor["total_chargeback_cents"] += cb["amount_cents"]
    recompute_vendor_compliance(vendor)
    if vendor["compliance_score_bp"] < COMPLIANCE_SUSPEND_THRESHOLD_BP and vendor["status"] == "ACTIVE":
        vendor["status"] = "SUSPENDED"
        touch(vendor)


# ---------------------------------------------------------------- unload fee
def compute_unload_fee(pallet_count):
    base = pallet_count * PER_PALLET_FEE_CENTS
    if pallet_count <= SMALL_LOAD_THRESHOLD:
        mult = Decimal("1.00")
    elif pallet_count <= MID_LOAD_THRESHOLD:
        mult = Decimal("1.15")
    else:
        mult = Decimal("1.30")
    return round_half_up_int(Decimal(base) * mult)


# ---------------------------------------------------------------- allocations
def compute_allocation_score(club, item, run_date_str):
    run_date = date.fromisoformat(run_date_str)
    window = WINDOW_DAYS_REGULAR if item["item_type"] == "REGULAR" else WINDOW_DAYS_TREASURE_HUNT
    start = run_date - timedelta(days=window)
    end = run_date - timedelta(days=1)
    velocity = 0
    for p in db.stores["purchases"].values():
        if p["status"] != "COMPLETED":
            continue
        if p["club_id"] != club["id"] or p["item_id"] != item["id"]:
            continue
        cw = date.fromisoformat(p["cap_window"])
        if start <= cw <= end:
            velocity += p["unit_qty"]
    region = db.stores["regions"][club["region_id"]]
    # Exact-decimal math so the final half-up rounding at 4dp sees the true
    # intermediate, not a float approximation (e.g. 11.64375 -> 11.6438).
    demo_factor = (Decimal(1) + Decimal(min(club["member_base"], MEMBER_BASE_CAP))
                   / Decimal(MEMBER_BASE_CAP) * Decimal(str(DEMO_WEIGHT)))
    income_factor = (Decimal(1) + Decimal(min(region["avg_member_income_cents"], INCOME_CAP_CENTS))
                     / Decimal(INCOME_CAP_CENTS) * Decimal(str(INCOME_WEIGHT)))
    score = Decimal(velocity + VELOCITY_BASE) * demo_factor * income_factor
    return float(score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def void_allocation(allocation, reason, strand_pallet=False, bump_run=True):
    """PROPOSED -> VOIDED cascade."""
    allocation["status"] = "VOIDED"
    allocation["void_reason"] = reason
    touch(allocation)
    club = db.stores["clubs"][allocation["club_id"]]
    club["allocated_slot_count"] -= allocation["floor_slots_reserved"]
    recompute_club_posture(club)
    touch(club)
    pallet = db.stores["pallets"][allocation["pallet_id"]]
    if strand_pallet:
        pallet["status"] = "STRANDED"
    else:
        pallet["status"] = "RECEIVED"
    touch(pallet)
    if bump_run:
        run = db.stores["runs"][allocation["cross_dock_run_id"]]
        touch(run)


def discontinue_item_cascade(item):
    """Item -> DISCONTINUED: strand unshipped pallets, void their PROPOSED allocations."""
    for pallet in list(db.stores["pallets"].values()):
        if pallet["item_id"] != item["id"] or pallet["status"] not in ("RECEIVED", "ALLOCATED"):
            continue
        was_allocated = pallet["status"] == "ALLOCATED"
        if was_allocated:
            # void its PROPOSED allocation first; cascade strands the pallet
            for al in list(db.stores["allocations"].values()):
                if al["pallet_id"] == pallet["id"] and al["status"] == "PROPOSED":
                    void_allocation(al, "ITEM_DISCONTINUED", strand_pallet=True, bump_run=True)
                    break
        if pallet["status"] != "STRANDED":
            pallet["status"] = "STRANDED"
            touch(pallet)


# ---------------------------------------------------------------- complaints
def recompute_item_complaints(item):
    today = current_date()
    window_start = today - timedelta(days=COMPLAINT_WINDOW_DAYS)
    total = Decimal("0")
    count = 0
    for c in db.stores["complaints"].values():
        if c["item_id"] != item["id"] or c["status"] != "OPEN":
            continue
        c_date = date.fromisoformat(c["created_on"])
        if window_start <= c_date <= today:
            total += Decimal(str(c["weight"]))
            count += 1
    item["complaint_weighted_score"] = round_half_up_2(total)
    item["complaint_count"] = count


# ---------------------------------------------------------------- sell-through
def compute_sell_through_pct(item_id):
    received = sum(p["unit_qty"] for p in db.stores["pallets"].values()
                   if p["item_id"] == item_id and p["status"] in ("RECEIVED", "ALLOCATED", "SHIPPED"))
    sold = sum(p["unit_qty"] for p in db.stores["purchases"].values()
               if p["item_id"] == item_id and p["status"] == "COMPLETED")
    denom = max(1, received)
    return round_half_up_int(Decimal(100 * sold) / Decimal(denom))


def has_markdown_decision(item_id):
    return any(d["item_id"] == item_id and d["decision"] == "MARKDOWN"
               for d in db.stores["markdown_decisions"].values())


# ---------------------------------------------------------------- clock transitions
def fire_due_transitions():
    """Auto-transitions fired when the logical clock advances. Returns count."""
    count = 0
    today = current_date()

    # 1. Appointment no-show rollover: BOOKED with delivery_date end-of-day passed
    for appt in list(db.stores["appointments"].values()):
        if appt["status"] != "BOOKED":
            continue
        if date.fromisoformat(appt["delivery_date"]) < today:
            appt["status"] = "NO_SHOW"
            touch(appt)
            amount = compute_chargeback_amount("NO_SHOW", appt, 0)
            cb = create_chargeback(appt["vendor_id"], appt["id"], "NO_SHOW", amount)
            appt["chargeback_cents"] += amount
            touch(appt)
            count += 1

    # 2. Pallet stranding: still RECEIVED with received_date earlier than today
    for pallet in list(db.stores["pallets"].values()):
        if pallet["status"] != "RECEIVED":
            continue
        if date.fromisoformat(pallet["received_date"]) < today:
            pallet["status"] = "STRANDED"
            touch(pallet)
            count += 1

    # 3. Chargeback auto-confirm: ASSESSED, assessed more than 7 days ago
    for cb in list(db.stores["chargebacks"].values()):
        if cb["status"] != "ASSESSED":
            continue
        assessed_date = date.fromisoformat(cb["assessed_at"][:10])
        if (today - assessed_date).days > APPEAL_WINDOW_DAYS:
            confirm_chargeback(cb)
            count += 1

    return count
