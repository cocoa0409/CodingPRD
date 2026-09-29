"""Derived aggregates: the two conserved ledgers (PRD 2.9), station and wave
counters, order flags and wave posture (PRD 2.11).

Every one of these is recomputed inside the request that moved any of its
inputs; reconcile() is called once at the end of every mutating request.
"""

import db as store
from db import db

ACTIVE_TASK_STATUSES = ("QUEUED", "RETRIEVING")
TOTE_LINE_STATUSES = ("QUEUED", "RETRIEVING", "COMPLETED", "SHORT")
TERMINAL_TASK_STATUSES = ("COMPLETED", "SHORT", "CANCELLED")
LIVE_TOTE_STATUSES = ("OPEN", "SEALED", "CONSOLIDATED", "LOADED")
LIVE_BOOKING_STATUSES = ("HELD", "CONFIRMED", "WAITLISTED")
ZONE_HOLD_STATUSES = ("MAINTENANCE", "AUDIT_HOLD")


# --------------------------------------------------------------------------
# Relationship helpers
# --------------------------------------------------------------------------
def order_lines(order):
    return [l for l in db.lines.values() if l["order_id"] == order["id"]]


def line_tasks(line):
    return [t for t in db.tasks.values() if t["order_line_id"] == line["id"]]


def order_tasks(order):
    ids = set(l["id"] for l in order_lines(order))
    return [t for t in db.tasks.values() if t["order_line_id"] in ids]


def line_proposals(line):
    return [p for p in db.proposals.values() if p["order_line_id"] == line["id"]]


def order_proposals(order):
    ids = set(l["id"] for l in order_lines(order))
    return [p for p in db.proposals.values() if p["order_line_id"] in ids]


def order_bookings(order):
    return [b for b in db.bookings.values() if b["customer_order_id"] == order["id"]]


def slot_bookings(slot):
    return [b for b in db.bookings.values() if b["delivery_slot_id"] == slot["id"]]


def wave_orders(wave):
    return [o for o in db.orders.values() if o["wave_id"] == wave["id"]]


def wave_member_orders(wave):
    return [o for o in wave_orders(wave) if o["fulfillment_status"] != "CANCELLED"]


def wave_totes(wave):
    return [t for t in db.totes.values() if t["wave_id"] == wave["id"]]


def wave_tasks(wave):
    ids = set()
    for order in wave_orders(wave):
        for line in order_lines(order):
            ids.add(line["id"])
    return [t for t in db.tasks.values() if t["order_line_id"] in ids]


def tote_tasks(tote):
    return [t for t in db.tasks.values() if t["tote_id"] == tote["id"]]


def station_totes(station):
    return [t for t in db.totes.values() if t["pick_station_id"] == station["id"]]


def task_line(task):
    return db.lines[task["order_line_id"]]


def line_order(line):
    return db.orders[line["order_id"]]


def order_wave(order):
    if order["wave_id"] is None:
        return None
    return db.waves.get(order["wave_id"])


def line_wave(line):
    return order_wave(line_order(line))


def live_booking_of(order):
    """PRD 3.2 step 2, widened by PRD 3.3: a WAITLISTED booking counts too."""
    rank = {"HELD": 0, "CONFIRMED": 0, "WAITLISTED": 1}
    live = [b for b in order_bookings(order) if b["status"] in LIVE_BOOKING_STATUSES]
    if not live:
        return None
    live.sort(key=lambda b: (rank[b["status"]], store.created_key(b)))
    return live[0]


def zone_skus(zone):
    return [s for s in db.skus.values() if s["grid_zone_id"] == zone["id"]]


# --------------------------------------------------------------------------
# Ledgers and counters
# --------------------------------------------------------------------------
def recompute_slot_ledger(slot):
    held = 0
    confirmed = 0
    for booking in slot_bookings(slot):
        if booking["status"] == "HELD":
            held += booking["units"]
        elif booking["status"] == "CONFIRMED":
            confirmed += booking["units"]
    slot["held_units"] = held
    slot["confirmed_units"] = confirmed
    slot["available_units"] = (
        slot["total_capacity_units"] - slot["withheld_units"] - held - confirmed
    )


def recompute_sku_ledger(sku):
    allocated = 0
    for task in db.tasks.values():
        if task["sku_id"] == sku["id"] and task["status"] in ACTIVE_TASK_STATUSES:
            allocated += task["allocated_units"]
    sku["allocated_units"] = allocated
    sku["on_hand_units"] = sku["physical_units"] - allocated


def recompute_all_sku_ledgers():
    for sku in db.skus.values():
        recompute_sku_ledger(sku)


def recompute_tote(tote):
    tote["assigned_line_count"] = len(
        [t for t in tote_tasks(tote) if t["status"] in TOTE_LINE_STATUSES]
    )


def recompute_station(station):
    count = len([t for t in station_totes(station) if t["status"] == "OPEN"])
    station["current_tote_count"] = count
    station["status"] = "IDLE" if count == 0 else "ACTIVE"


def recompute_order_flags(order):
    lines = order_lines(order)
    order["dispatch_blocked"] = any(
        l["substitution_resolution"] == "PENDING" for l in lines
    )
    order["open_substitution_count"] = len(
        [p for p in order_proposals(order) if p["status"] in ("DRAFT", "PROPOSED")]
    )


def recompute_wave_counters(wave):
    wave["order_count"] = len(wave_member_orders(wave))
    wave["tote_count"] = len(
        [t for t in wave_totes(wave) if t["status"] in LIVE_TOTE_STATUSES]
    )


def recompute_wave_posture(wave):
    zone_ids = set()
    for task in wave_tasks(wave):
        if task["status"] in ACTIVE_TASK_STATUSES:
            zone_ids.add(task["grid_zone_id"])
    zone_hold_count = 0
    for zone_id in zone_ids:
        zone = db.zones.get(zone_id)
        if zone is not None and zone["status"] in ZONE_HOLD_STATUSES:
            zone_hold_count += 1
    blocked = len([o for o in wave_member_orders(wave) if o["dispatch_blocked"]])
    if zone_hold_count > 0:
        wave["posture"] = "FROZEN"
    elif blocked > 0:
        wave["posture"] = "RESTRICTED"
    else:
        wave["posture"] = "OPEN"


def reconcile():
    """Recompute every derived aggregate, in dependency order."""
    for order in db.orders.values():
        recompute_order_flags(order)
    for sku in db.skus.values():
        recompute_sku_ledger(sku)
    for tote in db.totes.values():
        recompute_tote(tote)
    for station in db.stations.values():
        recompute_station(station)
    for slot in db.slots.values():
        recompute_slot_ledger(slot)
    for wave in db.waves.values():
        recompute_wave_counters(wave)
        recompute_wave_posture(wave)
