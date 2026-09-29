"""Pasteurization run control, thermal verification, the culture cascade and
bottling identity (PRD 3.6 - 3.7)."""

from datetime import timedelta
from decimal import Decimal

import domain_donor
import domain_pool
from store import db, find, insert, set_field
from util import add_days, dec, fmt_date, parse_date, parse_instant

MIN_HOLD_CELSIUS = Decimal("62.5")
MAX_HOLD_CELSIUS = Decimal("65.0")
MIN_HOLD_SECONDS = 1800
MAX_READING_GAP_SECONDS = 600
MIN_READINGS_TO_COMPLETE = 2
CLEANING_BUFFER_MINUTES = 15
CULTURE_FAIL_CFU = 10
PASTEURIZED_SHELF_LIFE_DAYS = 180
RAW_MILK_MAX_AGE_DAYS = 365
RECEIVED_MILK_SHELF_DAYS = 240

OCCUPYING_RUN_STATES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "BOTTLED")


def readings_of(run_id):
    rows = [r for r in db.rows("readings") if r["run_id"] == run_id]
    rows.sort(key=lambda r: r["offset_seconds"])
    return rows


def lots_of(run_id):
    return [l for l in db.rows("lots") if l["run_id"] == run_id]


def qualifies(celsius):
    return MIN_HOLD_CELSIUS <= dec(celsius) <= MAX_HOLD_CELSIUS


def interval_of(run):
    start = parse_instant(run["scheduled_start_at"])
    end = start + timedelta(minutes=run["cycle_minutes"] + CLEANING_BUFFER_MINUTES)
    return start, end


def slot_conflict(pasteurizer_id, start, end):
    for run in db.rows("runs"):
        if run["pasteurizer_id"] != pasteurizer_id:
            continue
        if run["run_status"] not in OCCUPYING_RUN_STATES:
            continue
        other_start, other_end = interval_of(run)
        if start < other_end and other_start < end:
            return True
    return False


def refresh_release_eligibility(run):
    eligible = (
        run["thermal_status"] == "PASSED" and run["culture_status"] == "PASSED"
    )
    set_field(run, "release_eligibility", "ELIGIBLE" if eligible else "BLOCKED")


def refresh_peak(run):
    rows = readings_of(run["id"])
    if not rows:
        set_field(run, "peak_celsius", None)
        return
    set_field(run, "peak_celsius", max(dec(r["celsius"]) for r in rows))


def thermal_hold_seconds(run):
    """Longest contiguous certified hold across the temperature curve."""
    longest = 0
    seg_start = None
    previous = None
    for reading in readings_of(run["id"]):
        if not reading["qualifies"]:
            seg_start = None
        elif seg_start is None:
            seg_start = reading["offset_seconds"]
        elif reading["offset_seconds"] - previous["offset_seconds"] > MAX_READING_GAP_SECONDS:
            seg_start = reading["offset_seconds"]
        else:
            span = reading["offset_seconds"] - seg_start
            if span > longest:
                longest = span
        previous = reading
    return longest


# --- culture failure: the four-hop destruction cascade ---------------------
def run_culture_failure(run):
    # hop 2 - every lot of the run is written off at its current volume
    for lot in lots_of(run["id"]):
        if lot["release_status"] in ("HOLD", "RELEASED", "EXHAUSTED"):
            set_field(lot, "release_status", "DISCARDED")

    # hop 3 - the pool and its surviving components are lost, not returned
    pool = find("pools", run["pool_id"])
    lost_components = []
    if pool is not None:
        if pool["status"] in ("COMMITTED", "PASTEURIZED"):
            set_field(pool, "status", "SCRAPPED_CULTURE")
        for component in domain_pool.components_of(pool["id"]):
            if component["status"] in ("ALLOCATED", "CONSUMED_PASTEURIZED"):
                set_field(component, "status", "CONSUMED_LOST")
                lost_components.append(component)

    # hop 4 - the donations behind those components are discarded
    seen = set()
    for component in lost_components:
        donation = find("donations", component["donation_id"])
        if donation is None or donation["id"] in seen:
            continue
        seen.add(donation["id"])
        if donation["status"] == "RECALLED":
            continue
        set_field(donation, "status", "DISCARDED")
        set_field(donation, "remaining_ml", 0)
        owner = find("donors", donation["donor_id"])
        if owner is not None:
            domain_donor.refresh_lifetime_volume(owner)


# --- bottling --------------------------------------------------------------
def contributing_components(pool_id):
    return [
        c for c in domain_pool.components_of(pool_id)
        if c["status"] in ("ALLOCATED", "CONSUMED_PASTEURIZED")
    ]


def lot_expiration_date(run, pool):
    completed = parse_instant(run["completed_at"])
    pasteurization_date = completed.date()
    ceilings = [add_days(pasteurization_date, PASTEURIZED_SHELF_LIFE_DAYS)]

    expressed_dates = []
    received_dates = []
    for component in contributing_components(pool["id"]):
        donation = find("donations", component["donation_id"])
        if donation is None:
            continue
        expressed = parse_date(donation["expressed_on"])
        if expressed is not None:
            expressed_dates.append(expressed)
        shipment = find("shipments", donation["shipment_id"])
        if shipment is not None and shipment["received_at"]:
            received = parse_instant(shipment["received_at"])
            if received is not None:
                received_dates.append(received.date())
    if expressed_dates:
        ceilings.append(add_days(min(expressed_dates), RAW_MILK_MAX_AGE_DAYS))
    if received_dates:
        ceilings.append(add_days(min(received_dates), RECEIVED_MILK_SHELF_DAYS))
    return min(ceilings), pasteurization_date


def bottle_lot(run, pool, bottle_count, bottle_volume_ml):
    expiration, pasteurization_date = lot_expiration_date(run, pool)
    lot_sequence = len(lots_of(run["id"])) + 1
    lot_code = "%04d%02d%02d-%03d-%02d" % (
        pasteurization_date.year, pasteurization_date.month,
        pasteurization_date.day, pool["pool_sequence"], lot_sequence,
    )
    total_volume = bottle_count * bottle_volume_ml
    lot = insert("lots", {
        "run_id": run["id"],
        "lot_code": lot_code,
        "lot_sequence": lot_sequence,
        "milk_class": pool["target_milk_class"],
        "bottle_count": bottle_count,
        "bottle_volume_ml": bottle_volume_ml,
        "total_volume_ml": total_volume,
        "dispensed_ml": 0,
        "available_ml": total_volume,
        "kcal_per_oz": pool["projected_kcal_per_oz"],
        "pasteurization_date": fmt_date(pasteurization_date),
        "expiration_date": fmt_date(expiration),
        "release_status": "HOLD",
        "released_at": None,
        "released_by_user_id": None,
    })

    first_lot = lot_sequence == 1
    if first_lot:
        set_field(run, "run_status", "BOTTLED")
        if pool["status"] == "COMMITTED":
            set_field(pool, "status", "PASTEURIZED")
        for component in domain_pool.components_of(pool["id"]):
            if component["status"] == "ALLOCATED":
                set_field(component, "status", "CONSUMED_PASTEURIZED")
        for donation in db.rows("donations"):
            components = domain_pool.components_of_donation(donation["id"])
            if not components:
                continue
            if donation["status"] != "ALLOCATED":
                continue
            if all(c["status"] == "CONSUMED_PASTEURIZED" for c in components) \
                    and donation["remaining_ml"] == 0:
                set_field(donation, "status", "PASTEURIZED")
    domain_pool.recompute_bottled_volume(pool)
    return lot
