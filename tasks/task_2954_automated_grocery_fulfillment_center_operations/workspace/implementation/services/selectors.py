"""Deterministic selectors and sequences (PRD 3.3, 3.5, 3.6, 3.7, 3.8)."""

from fractions import Fraction

import db as store
from db import db
from services import derive, money


# --------------------------------------------------------------------------
# Retrieval sequence (PRD 3.5)
# --------------------------------------------------------------------------
def _line_sequence_keys(line, sku_id=None):
    sku = db.skus[sku_id or line["sku_id"]]
    zone = db.zones[sku["grid_zone_id"]]
    return (
        store.ZONE_RANK[sku["temperature_zone"]],
        zone["zone_code"],
        sku["sku_code"],
        store.created_key(line),
    )


def retrieval_sequence(wave):
    """Every PENDING line of every WAVED member order, in retrieval order."""
    population = []
    for order in derive.wave_orders(wave):
        if order["fulfillment_status"] != "WAVED":
            continue
        for line in derive.order_lines(order):
            if line["line_status"] == "PENDING":
                population.append(line)
    population.sort(key=_line_sequence_keys)
    return population


def next_sequence_index(wave):
    """A task created after picking started extends the wave's retrieval order."""
    highest = 0
    for task in derive.wave_tasks(wave):
        if task["sequence_index"] > highest:
            highest = task["sequence_index"]
    return highest + 1


# --------------------------------------------------------------------------
# Pick station assignment (PRD 3.5)
# --------------------------------------------------------------------------
def select_station(sku):
    pool = []
    for station in db.stations.values():
        if station["status"] not in ("IDLE", "ACTIVE"):
            continue
        if sku["temperature_zone"] not in station["temperature_zone_capability"]:
            continue
        if station["current_tote_count"] >= station["max_concurrent_totes"]:
            continue
        pool.append(station)
    if not pool:
        return None
    pool.sort(key=lambda s: (
        s["current_tote_count"],
        -s["max_concurrent_totes"],
        s["station_code"],
        store.created_key(s),
    ))
    return pool[0]


# --------------------------------------------------------------------------
# Substitute selector (PRD 3.6)
# --------------------------------------------------------------------------
def select_substitute(line, original_sku):
    candidates = []
    for sku in db.skus.values():
        if sku["id"] == original_sku["id"]:
            continue
        if sku["temperature_zone"] != original_sku["temperature_zone"]:
            continue
        if sku["substitution_group_code"] != original_sku["substitution_group_code"]:
            continue
        zone = db.zones.get(sku["grid_zone_id"])
        if zone is None or zone["status"] != "OPERATIONAL":
            continue
        if sku["on_hand_units"] < line["ordered_qty"]:
            continue
        candidates.append(sku)
    if not candidates:
        return None
    candidates.sort(key=lambda s: (
        abs(s["unit_price_cents"] - original_sku["unit_price_cents"]),
        s["unit_price_cents"],
        s["sku_code"],
        store.created_key(s),
    ))
    return candidates[0]


# --------------------------------------------------------------------------
# Waitlist promotion and bumping (PRD 3.3, 3.9)
# --------------------------------------------------------------------------
def promote_one_waitlisted(slot):
    """At most one promotion per request; returns the promoted booking or None."""
    candidates = [
        b for b in derive.slot_bookings(slot)
        if b["status"] == "WAITLISTED" and b["units"] <= slot["available_units"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda b: -b["quoted_fee_cents"])
    candidates.sort(key=lambda b: -b["units"])
    candidates.sort(key=lambda b: store.created_key(b))
    winner = candidates[0]
    winner["status"] = "CONFIRMED"
    order = db.orders[winner["customer_order_id"]]
    if order["fulfillment_status"] == "DRAFT":
        order["fulfillment_status"] = "SLOTTED"
    money.authorize(order)
    store.bump(order)
    derive.recompute_slot_ledger(slot)
    return winner


def bump_confirmed_bookings(slot):
    """Repair a negative ledger by bumping CONFIRMED bookings one at a time."""
    while slot["available_units"] < 0:
        candidates = []
        for booking in derive.slot_bookings(slot):
            if booking["status"] != "CONFIRMED":
                continue
            order = db.orders[booking["customer_order_id"]]
            if order["fulfillment_status"] not in ("DRAFT", "SLOTTED"):
                continue  # a waved order is past the point of no return
            candidates.append(booking)
        if not candidates:
            return
        candidates.sort(key=lambda b: b["units"])
        candidates.sort(key=lambda b: b["created_at"], reverse=True)
        victim = candidates[0]
        victim["status"] = "BUMPED"
        order = db.orders[victim["customer_order_id"]]
        if order["fulfillment_status"] == "SLOTTED":
            order["fulfillment_status"] = "DRAFT"
        if order["billing_status"] == "AUTHORIZED":
            order["billing_status"] = "PENDING_AUTH"
        order["authorized_amount_cents"] = None
        money.run_waterfall(order, apply_billing=False)
        store.bump(order)
        derive.recompute_slot_ledger(slot)


# --------------------------------------------------------------------------
# Van loading sequence (PRD 3.7)
# --------------------------------------------------------------------------
def stop_orders_of(wave):
    stops = [
        o for o in derive.wave_orders(wave)
        if o["fulfillment_status"] == "CONSOLIDATED"
    ]
    stops.sort(key=lambda o: (o["stop_distance_km"], store.created_key(o)))
    return stops


def loading_sequence(wave, stops):
    stop_position = {}
    for index, order in enumerate(stops):
        stop_position[order["id"]] = index + 1
    totes = [t for t in derive.wave_totes(wave) if t["status"] == "CONSOLIDATED"]
    attributed = {}
    for tote in totes:
        best = 0
        for task in derive.tote_tasks(tote):
            line = db.lines.get(task["order_line_id"])
            if line is None:
                continue
            position = stop_position.get(line["order_id"], 0)
            if position > best:
                best = position
        attributed[tote["id"]] = best
    totes.sort(key=lambda t: store.created_key(t))
    totes.sort(key=lambda t: t["tote_code"])
    totes.sort(key=lambda t: store.ZONE_RANK[t["temperature_zone"]])
    totes.sort(key=lambda t: attributed[t["id"]], reverse=True)
    return [t["id"] for t in totes]


# --------------------------------------------------------------------------
# Inventory accuracy audit (PRD 3.8)
# --------------------------------------------------------------------------
def apply_audit(zone, rows):
    for row in rows:
        sku = db.skus[row["sku_id"]]
        system_units = sku["physical_units"]
        sku["last_count_system_units"] = system_units
        sku["last_count_counted_units"] = row["counted_units"]
        sku["last_count_variance_units"] = row["counted_units"] - system_units
        sku["physical_units"] = row["counted_units"]
        derive.recompute_sku_ledger(sku)

    population = [
        s for s in derive.zone_skus(zone)
        if s["last_count_system_units"] is not None and s["last_count_system_units"] > 0
    ]
    if population:
        total_variance = sum(abs(s["last_count_variance_units"]) for s in population)
        total_system = sum(s["last_count_system_units"] for s in population)
        unit_weighted = store.fraction_to_decimal(
            1 - Fraction(total_variance, total_system), 4
        )
        ratio_sum = Fraction(0)
        for sku in population:
            ratio_sum += 1 - Fraction(
                abs(sku["last_count_variance_units"]), sku["last_count_system_units"]
            )
        sku_weighted = store.fraction_to_decimal(
            ratio_sum / Fraction(len(population)), 4
        )
        zone["accuracy_score_unit_weighted"] = unit_weighted
        zone["accuracy_score_sku_weighted"] = sku_weighted
        if unit_weighted < store.ACCURACY_HOLD_THRESHOLD:
            zone["status"] = "AUDIT_HOLD"
        else:
            zone["status"] = "OPERATIONAL"
    zone["last_audited_at"] = db.clock
