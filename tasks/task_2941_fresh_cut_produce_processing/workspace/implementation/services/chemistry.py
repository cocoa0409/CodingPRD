"""Wash-water chemistry: the strictly ordered load -> tier -> dwell -> top-up rule."""

from decimal import Decimal

import db
from util import ceil_int, q1, q2, q3

LOAD_FACTOR = {
    "LEAFY": Decimal("1.0"),
    "ROOT": Decimal("1.8"),
    "FRUIT": Decimal("0.5"),
}
LOAD_NORMALIZER = Decimal(10)
CHANGEOUT_LOAD_INDEX_MAX = Decimal("3.000")
TIER_HIGH = Decimal("1.500")
TIER_MID = Decimal("0.500")
BASE_DWELL_SECONDS = 90
ZERO_1 = Decimal("0.0")


def readings_of(system):
    return [r for r in db.rows("readings") if r["wash_system_id"] == system["id"]]


def latest_reading(system):
    best = None
    for r in readings_of(system):
        key = (db.dt_of(r, "reading_at"), r["sequence_no"])
        if best is None or key > (db.dt_of(best, "reading_at"), best["sequence_no"]):
            best = r
    return best


def window_readings(system_id, start_dt, end_dt):
    """Readings whose reading_at lies in the inclusive window [start, end]."""
    out = []
    for r in db.rows("readings"):
        if r["wash_system_id"] != system_id:
            continue
        at = db.dt_of(r, "reading_at")
        if at is None:
            continue
        if at >= start_dt and at <= end_dt:
            out.append(r)
    return out


def in_window_consumptions(system):
    """ACTIVE consumptions on RUNNING or CLOSED runs of this system since change-out."""
    floor_dt = db.dt_of(system, "last_changeout_at")
    out = []
    for c in db.rows("lot_consumptions"):
        if c["status"] != "ACTIVE":
            continue
        run = db.find("process_runs", c["process_run_id"])
        if run is None or run["wash_system_id"] != system["id"]:
            continue
        if run["run_status"] not in ("RUNNING", "CLOSED"):
            continue
        if floor_dt is not None and db.dt_of(c, "created_at") < floor_dt:
            continue
        out.append(c)
    return out


def tier_target(index):
    if index >= CHANGEOUT_LOAD_INDEX_MAX:
        return None
    if index >= TIER_HIGH:
        return Decimal("55.0")
    if index >= TIER_MID:
        return Decimal("35.0")
    return Decimal("20.0")


def topup_for(target, ppm):
    if target is None or ppm is None:
        return None
    gap = q1(target - ppm)
    if gap < ZERO_1:
        return ZERO_1
    return gap


def compute_chemistry(system):
    """Pure evaluation of the four steps; writes nothing."""
    total = Decimal(0)
    for c in in_window_consumptions(system):
        run = db.find("process_runs", c["process_run_id"])
        product = db.find("products", run["product_id"]) if run else None
        if product is None:
            continue
        total = total + c["consumed_lb"] * LOAD_FACTOR[product["commodity_class"]]
    weighted = q2(total)
    index = q3(weighted / (system["water_volume_gal"] * LOAD_NORMALIZER))
    target = tier_target(index)
    latest = latest_reading(system)
    dwell = None
    if target is not None and latest is not None:
        measured = latest["free_chlorine_ppm"]
        if measured is not None and measured > 0:
            dwell = max(
                BASE_DWELL_SECONDS,
                ceil_int(Decimal(BASE_DWELL_SECONDS) * target / measured),
            )
        else:
            dwell = BASE_DWELL_SECONDS
    topup = None
    if latest is not None:
        topup = topup_for(target, latest["free_chlorine_ppm"])
    return {
        "weighted_load_lb": weighted,
        "organic_load_index": index,
        "target_free_chlorine_ppm": target,
        "required_dwell_seconds": dwell,
        "topup_ppm_required": topup,
        "dump_required": index >= CHANGEOUT_LOAD_INDEX_MAX,
    }


def apply_chemistry(system):
    """Recompute and persist the wash system's derived load figures."""
    result = compute_chemistry(system)
    changed = False
    for field in ("weighted_load_lb", "organic_load_index", "target_free_chlorine_ppm"):
        if system.get(field) != result[field]:
            system[field] = result[field]
            changed = True
    if result["dump_required"] and system["status"] == "IN_SERVICE":
        system["status"] = "DUMP_REQUIRED"
        changed = True
    if changed:
        db.touch(system)
    return result


def force_dump_required(system):
    """Sanitation-failure cascade hop 4: IN_SERVICE -> DUMP_REQUIRED."""
    if system["status"] == "IN_SERVICE":
        system["status"] = "DUMP_REQUIRED"
        db.touch(system)
        return True
    return False


def changeout(system, now):
    db.stamp(system, "last_changeout_at", now)
    system["changeout_count"] = system["changeout_count"] + 1
    system["status"] = "IN_SERVICE"
    result = compute_chemistry(system)
    system["weighted_load_lb"] = result["weighted_load_lb"]
    system["organic_load_index"] = result["organic_load_index"]
    system["target_free_chlorine_ppm"] = result["target_free_chlorine_ppm"]
    db.touch(system)
    return system
