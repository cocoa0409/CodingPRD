"""Derived state: the three station ledgers, the standing-crop meter, the
operating posture with its freeze/thaw cascade, the quarantine unwind, and the
clock-driven re-evaluation of the whole world.

PRD 2.5: "The service is expected to maintain these identities rather than merely
to report them." Every aggregate here is recomputed by scanning the records it is
defined over, so the conserved-quantity identities hold by construction.
"""

from decimal import Decimal

import calc
import constants as K
from store import clock, days, fmt_instant, parse_instant, values


# --- collection helpers -----------------------------------------------------

def broods_of(hatchery_id):
    return [b for b in values("brood_stocks") if b["hatchery_id"] == hatchery_id]


def spawn_events_of(brood_stock_id):
    return [s for s in values("spawn_events") if s["brood_stock_id"] == brood_stock_id]


def lots_of(hatchery_id):
    return [lot for lot in values("rearing_lots") if lot["hatchery_id"] == hatchery_id]


def readings_of(hatchery_id):
    return [r for r in values("effluent_readings") if r["hatchery_id"] == hatchery_id]


def events_of_lot(lot_id):
    return [e for e in values("stocking_events") if e["lot_id"] == lot_id]


def inspections_of_lot(lot_id):
    return [i for i in values("health_inspections") if i["lot_id"] == lot_id]


def requests_of_water(water_id):
    return [r for r in values("stocking_requests") if r["water_id"] == water_id]


def requests_of_plan(plan_id):
    return [r for r in values("stocking_requests") if r["allocation_plan_id"] == plan_id]


def hatchery_of_lot(lot):
    from store import find
    return find("hatcheries", lot["hatchery_id"])


def hatchery_of_event(event):
    from store import find
    lot = find("rearing_lots", event["lot_id"])
    return find("hatcheries", lot["hatchery_id"]) if lot else None


def water_of_event(event):
    from store import find
    stocking_request = find("stocking_requests", event["stocking_request_id"])
    return find("waters", stocking_request["water_id"]) if stocking_request else None


def events_of_hatchery(hatchery_id):
    lot_ids = set(lot["id"] for lot in lots_of(hatchery_id))
    return [e for e in values("stocking_events") if e["lot_id"] in lot_ids]


def latest_inspection_with_withdrawal(lot_id):
    """The lot's latest inspection carrying a withdrawal window."""
    candidates = [i for i in inspections_of_lot(lot_id) if i["withdrawal_clears_at"]]
    if not candidates:
        return None
    candidates.sort(key=lambda i: (i["updated_at"], i["_seq"]))
    return candidates[-1]


def _assign(tx, record, field, value):
    if record.get(field) != value:
        record[field] = value
        tx.touch(record)


# --- rearing lot ------------------------------------------------------------

def recompute_lot(tx, lot):
    _assign(tx, lot, "biomass_lbs", calc.lot_biomass_lbs(lot))


def recompute_lot_reservation(tx, lot):
    """reserved_count is the fish committed to trips still SCHEDULED or IN_TRANSIT."""
    reserved = sum(event["fish_count"] for event in events_of_lot(lot["id"])
                   if event["status"] in ("SCHEDULED", "IN_TRANSIT"))
    _assign(tx, lot, "reserved_count", reserved)
    recompute_lot(tx, lot)


# --- brood stock ------------------------------------------------------------

def recompute_brood(tx, brood):
    events = spawn_events_of(brood["id"])
    reserved = sum(e["females_spawned"] for e in events if e["status"] == "PLANNED")
    spent = sum(e["females_spawned"] for e in events if e["status"] == "TAKEN")
    taken = sum((e["eggs_taken"] or 0) for e in events if e["status"] == "TAKEN")
    _assign(tx, brood, "females_reserved", reserved)
    _assign(tx, brood, "females_spent", spent)
    _assign(tx, brood, "females_available", brood["female_count"] - reserved - spent)
    _assign(tx, brood, "cumulative_eggs_taken", taken)


# --- water ------------------------------------------------------------------

def recompute_water(tx, water):
    allocated = sum(r["allocated_count"] for r in requests_of_water(water["id"])
                    if r["status"] == "ALLOCATED")
    released = 0
    for event in values("stocking_events"):
        if event["status"] != "RELEASED":
            continue
        destination = water_of_event(event)
        if destination is not None and destination["id"] == water["id"]:
            released += event["released_count"] or 0
    _assign(tx, water, "allocated_count_ytd", allocated)
    _assign(tx, water, "released_count_ytd", released)
    _assign(tx, water, "plan_shortfall_count",
            calc.plan_shortfall(water["plan_target_count"], released, allocated))
    _assign(tx, water, "plan_fill_pct",
            calc.plan_fill_pct(water["plan_target_count"], released, allocated))


# --- hatchery ledgers and posture ------------------------------------------

def _recompute_ledgers(tx, hatchery):
    reserved_af = Decimal(0)
    used_af = Decimal(0)
    for brood in broods_of(hatchery["id"]):
        for event in spawn_events_of(brood["id"]):
            if event["status"] == "PLANNED":
                reserved_af += Decimal(event["water_reserved_af"])
            elif event["status"] == "TAKEN":
                used_af += calc.water_af_for_eggs(event["eggs_taken"] or 0)
    for reading in readings_of(hatchery["id"]):
        used_af += Decimal(reading["flow_af"])
    reserved_af = calc.q4(reserved_af)
    used_af = calc.q4(used_af)
    available_af = calc.q4(Decimal(hatchery["annual_water_right_af"]) - reserved_af - used_af)
    _assign(tx, hatchery, "water_reserved_af", reserved_af)
    _assign(tx, hatchery, "water_used_af", used_af)
    _assign(tx, hatchery, "water_available_af", available_af)

    biomass = Decimal(0)
    for lot in lots_of(hatchery["id"]):
        if lot["rearing_stage"] not in ("RELEASED", "TERMINATED"):
            biomass += Decimal(lot["biomass_lbs"])
    biomass = calc.q2(biomass)
    _assign(tx, hatchery, "biomass_on_hand_lbs", biomass)
    _assign(tx, hatchery, "density_index",
            calc.density_index(biomass, hatchery["rearing_capacity_lbs"]))

    committed = 0
    spent = 0
    for event in events_of_hatchery(hatchery["id"]):
        if event["status"] in ("SCHEDULED", "IN_TRANSIT"):
            committed += event["transport_cost_cents"]
        elif event["status"] == "RELEASED":
            spent += event["transport_cost_cents"]
    _assign(tx, hatchery, "budget_committed_cents", committed)
    _assign(tx, hatchery, "budget_spent_cents", spent)
    _assign(tx, hatchery, "budget_available_cents",
            hatchery["annual_budget_cents"] - committed - spent)

    edge = clock() - days(K.EXCEEDANCE_WINDOW_DAYS)
    count = 0
    for reading in readings_of(hatchery["id"]):
        if reading["status"] == "EXCEEDANCE" and parse_instant(reading["sampled_at"]) > edge:
            count += 1
    _assign(tx, hatchery, "exceedance_count_rolling", count)


def recompute_hatchery(tx, hatchery):
    """Ledgers, standing crop and posture, with the freeze/thaw cascade."""
    _recompute_ledgers(tx, hatchery)
    previous = hatchery["operating_posture"]
    posture = calc.operating_posture(hatchery["exceedance_count_rolling"],
                                    hatchery["water_available_af"],
                                    hatchery["density_index"])
    if posture == previous:
        return
    _assign(tx, hatchery, "operating_posture", posture)
    if posture == "FROZEN":
        _freeze_cascade(tx, hatchery)
        # The cancellations return acre-feet, but the station stays FROZEN: the
        # posture that triggered the cascade is not re-evaluated by it.
        _recompute_ledgers(tx, hatchery)
        hatchery["operating_posture"] = "FROZEN"
    elif previous == "FROZEN":
        _thaw_cascade(tx, hatchery)


def _freeze_cascade(tx, hatchery):
    """"every brood group of that station in SPAWNING status transitions to
    SUSPENDED, and ... each of its spawn events still in PLANNED status
    transitions to CANCELLED"."""
    for brood in broods_of(hatchery["id"]):
        if brood["status"] != "SPAWNING":
            continue
        brood["status"] = "SUSPENDED"
        tx.touch(brood)
        for event in spawn_events_of(brood["id"]):
            if event["status"] == "PLANNED":
                event["status"] = "CANCELLED"
                tx.touch(event)
        recompute_brood(tx, brood)


def _thaw_cascade(tx, hatchery):
    """"every brood group of that station in SUSPENDED status whose spawning
    window still contains the clock transitions back to SPAWNING"."""
    now = clock()
    for brood in broods_of(hatchery["id"]):
        if brood["status"] != "SUSPENDED":
            continue
        start = parse_instant(brood["spawning_window_start"])
        end = parse_instant(brood["spawning_window_end"])
        if start <= now < end:
            brood["status"] = "SPAWNING"
            tx.touch(brood)


# --- quarantine unwind ------------------------------------------------------

def quarantine_lot(tx, lot):
    """The longest cascade in the system (PRD 3.5)."""
    from store import find

    lot["health_status"] = "QUARANTINED"
    lot["certificate_expires_at"] = None
    tx.touch(lot)

    stamp = fmt_instant(clock())
    touched_waters = []
    for event in events_of_lot(lot["id"]):
        if event["status"] not in ("SCHEDULED", "IN_TRANSIT"):
            continue
        event["status"] = "ABORTED"
        event["aborted_at"] = stamp
        event["abort_reason"] = "LOT_QUARANTINED"
        event["released_count"] = 0
        tx.touch(event)

        unit = find("transport_units", event["transport_unit_id"])
        if unit is not None and unit["current_event_id"] == event["id"]:
            unit["status"] = "AVAILABLE"
            unit["current_event_id"] = None
            tx.touch(unit)

        stocking_request = find("stocking_requests", event["stocking_request_id"])
        if stocking_request is not None:
            stocking_request["status"] = "DEFERRED"
            stocking_request["allocated_count"] = 0
            stocking_request["deferral_reason"] = "EVENT_ABORTED"
            tx.touch(stocking_request)
            water = find("waters", stocking_request["water_id"])
            if water is not None and water not in touched_waters:
                touched_waters.append(water)

    lot["reserved_count"] = sum(
        e["fish_count"] for e in events_of_lot(lot["id"])
        if e["status"] in ("SCHEDULED", "IN_TRANSIT"))
    recompute_lot(tx, lot)
    for water in touched_waters:
        recompute_water(tx, water)
    hatchery = hatchery_of_lot(lot)
    if hatchery is not None:
        recompute_hatchery(tx, hatchery)


# --- allocation plan closure ------------------------------------------------

TERMINAL_REQUEST_STATUSES = ("FULFILLED", "DENIED", "WITHDRAWN")


def close_plan_if_complete(tx, plan):
    """"a plan in ALLOCATED status every one of whose attached requests has
    reached a terminal status ... transitions to CLOSED"."""
    if plan is None or plan["status"] != "ALLOCATED":
        return
    attached = requests_of_plan(plan["id"])
    if not attached:
        return
    for stocking_request in attached:
        if stocking_request["status"] not in TERMINAL_REQUEST_STATUSES:
            return
    plan["status"] = "CLOSED"
    tx.touch(plan)


# --- lot stage settlement ---------------------------------------------------

def settle_lot_after_feeding(tx, lot):
    if (lot["count_on_hand"] == 0 and lot["reserved_count"] == 0
            and lot["cumulative_mortality_count"] >= lot["initial_count"]
            and lot["rearing_stage"] not in ("RELEASED", "TERMINATED")):
        lot["rearing_stage"] = "TERMINATED"
        tx.touch(lot)


def settle_lot_after_release(tx, lot):
    if (lot["rearing_stage"] in ("FRY", "FINGERLING", "YEARLING")
            and lot["count_on_hand"] == 0 and lot["reserved_count"] == 0):
        lot["rearing_stage"] = "RELEASED"
        tx.touch(lot)


# --- the clock --------------------------------------------------------------

def apply_clock(tx):
    """PRD 2.4, in this order: postures (with their cascades), certificate
    lapses, brood-window closures, transport-unit certification lapses."""
    now = clock()

    for hatchery in values("hatcheries"):
        recompute_hatchery(tx, hatchery)

    for lot in values("rearing_lots"):
        expiry = lot["certificate_expires_at"]
        if lot["health_status"] == "CERTIFIED" and expiry and now > parse_instant(expiry):
            # The lapsed expiry instant is retained on the lot.
            lot["health_status"] = "UNSCREENED"
            tx.touch(lot)

    for brood in values("brood_stocks"):
        if brood["status"] in ("SPAWNING", "SUSPENDED"):
            if now >= parse_instant(brood["spawning_window_end"]):
                brood["status"] = "CLOSED"
                tx.touch(brood)

    for unit in values("transport_units"):
        if unit["status"] == "AVAILABLE":
            if now >= parse_instant(unit["certification_expires_at"]):
                unit["status"] = "OUT_OF_SERVICE"
                tx.touch(unit)
