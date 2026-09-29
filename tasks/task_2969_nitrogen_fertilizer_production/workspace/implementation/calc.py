"""Every calculation in the domain, and nothing else.

These functions read the store but never write it: a caller that wants a figure
persisted writes it itself. That split is what lets reads re-derive freely
without ever bumping a version.
"""
from datetime import timedelta

from store import db, by_seq
from util import D, ZERO, clamp, rhu, year_month, whole_days

# --- constants (PRD 3.2 / 3.4 / 3.6 / 3.7 / 3.8 / 3.10) --------------------
GAS_INTENSITY_MMBTU_PER_TON = D("33.0")
FIXED_CONVERSION_USD_PER_TON = D("42.50")

CATALYST_MIN_ACTIVITY_PCT = D("55.00")
SEVERITY_WEIGHT = D("0.45")
REGEN_RECOVERY_PCT = D("12.00")
MAX_REGENERATIONS = 3

STORAGE_HANDLING_USD_PER_TON = D("1.333")
SECURITY_FEE_USD_PER_TON = D("2.755")

MARGIN_FLOOR_USD_PER_TON = D("25.00")
TARGET_MARGIN_PCT = D("0.22")
SPRING_MULTIPLIER = D("1.18")
SPRING_MONTHS = (3, 4, 5)
VOLUME_TIER_25K_FACTOR = D("0.94")
VOLUME_TIER_5K_FACTOR = D("0.97")
VOLUME_TIER_25K_THRESHOLD = D("25000")
VOLUME_TIER_5K_THRESHOLD = D("5000")
RESTRICTED_POSTURE_FACTOR = D("1.06")

MODE_RATE_USD_PER_TON_MILE = {
    "RAIL": D("0.0412"),
    "BARGE": D("0.0189"),
    "TRUCK": D("0.1075"),
}
MODE_MIN_CHARGE_USD = {
    "RAIL": D("2200.00"),
    "BARGE": D("4800.00"),
    "TRUCK": D("450.00"),
}
SURCHARGE_BANDS = ((D("25000.00"), D("0.085")), (D("100000.00"), D("0.062")))
SURCHARGE_TOP_RATE = D("0.041")

POLLUTANTS = ("N2O", "NH3", "NOX", "PM")
LB_PER_TON = D("2000")
ROLLING_WINDOW_DAYS = 30
SEASONAL_RESERVE_MONTHS = (12, 1, 2)
TURNAROUND_BUFFER_DAYS = 14

LIVE_RUN_STATUSES = ("PLANNED", "APPROVED", "RUNNING", "COMPLETED")


# --------------------------------------------------------------------------
# Relationship helpers
# --------------------------------------------------------------------------
def plant_of_train(train):
    return db.plants.get(train["plant_id"]) if train else None


def plant_of_run(run):
    train = db.trains.get(run["train_id"])
    return plant_of_train(train)


def plant_of_order(order):
    run = db.runs.get(order["run_id"])
    return plant_of_run(run) if run else None


def plant_of_asset(asset):
    return db.plants.get(asset["plant_id"]) if asset else None


def active_charge(train_id):
    for charge in by_seq([c for c in db.charges.values()
                          if c["train_id"] == train_id and c["status"] == "ACTIVE"]):
        return charge
    return None


def line_for_product_code(product_code):
    for line in by_seq([l for l in db.lines.values()
                        if l["product_code"] == product_code]):
        return line
    return None


# --------------------------------------------------------------------------
# plant_hedged_blend (PRD 3.3)
# --------------------------------------------------------------------------
def hedge_pool(plant_id):
    return [lot for lot in db.lots.values()
            if lot["plant_id"] == plant_id
            and lot["status"] == "OPEN"
            and remaining_mmbtu(lot) > ZERO]


def remaining_mmbtu(lot):
    return lot["mmbtu_volume"] - lot["consumed_mmbtu"]


def hedged_blend(plant):
    pool = hedge_pool(plant["id"])
    if not pool:
        return None
    numerator = ZERO
    denominator = ZERO
    for lot in pool:
        rem = remaining_mmbtu(lot)
        numerator += rem * lot["strike_price_usd_per_mmbtu"]
        denominator += rem
    if denominator == ZERO:
        return None
    return rhu(numerator / denominator, 4)


# --------------------------------------------------------------------------
# run_ammonia_unit_cost (PRD 3.4)
# --------------------------------------------------------------------------
def _eligible_lots(run, plant, variant):
    lots = [lot for lot in db.lots.values()
            if lot["plant_id"] == plant["id"]
            and lot["status"] == "OPEN"
            and remaining_mmbtu(lot) > ZERO]
    if variant == "PROVISIONAL":
        month = year_month(run["window_start"])
        lots = [lot for lot in lots if lot["delivery_month"] == month]
        lots.sort(key=lambda l: (l["strike_price_usd_per_mmbtu"], l["_seq"]))
    else:
        month = year_month(run["window_end"])
        lots = [lot for lot in lots if lot["delivery_month"] <= month]
        lots.sort(key=lambda l: (l["delivery_month"],
                                 l["strike_price_usd_per_mmbtu"],
                                 l["_seq"]))
    return lots


def run_unit_cost(run, plant, variant, ammonia_tons):
    """The feedstock waterfall. Returns (unit_cost, draws, hedged_drawn).

    `draws` maps lot id to the volume drawn; the caller applies it only for the
    FINAL variant, because the PROVISIONAL variant mutates nothing.
    """
    required = ammonia_tons * GAS_INTENSITY_MMBTU_PER_TON
    need = required
    gas_cost = ZERO
    draws = {}
    hedged_drawn = ZERO
    for lot in _eligible_lots(run, plant, variant):
        if need <= ZERO:
            break
        rem = remaining_mmbtu(lot)
        draw = rem if rem < need else need
        if draw <= ZERO:
            continue
        gas_cost += draw * lot["strike_price_usd_per_mmbtu"]
        need -= draw
        draws[lot["id"]] = draw
        hedged_drawn += draw
    if need > ZERO:
        gas_cost += need * plant["spot_gas_index_usd_per_mmbtu"]
    unit_cost = rhu(gas_cost / ammonia_tons + FIXED_CONVERSION_USD_PER_TON, 2)
    return unit_cost, draws, hedged_drawn


# --------------------------------------------------------------------------
# catalyst_activity_pct (PRD 3.2)
# --------------------------------------------------------------------------
def cumulative_operating_hours(charge):
    total = charge["baseline_operating_hours"]
    for run in db.runs.values():
        if (run.get("catalyst_charge_id") == charge["id"]
                and run["status"] == "COMPLETED"
                and run.get("actual_operating_hours") is not None):
            total += run["actual_operating_hours"]
    return rhu(total, 1)


def activity_figures(charge):
    """Returns (cumulative_operating_hours, calendar_activity_pct, activity_pct)."""
    cumulative = cumulative_operating_hours(charge)
    design = charge["design_life_hours"]
    calendar = rhu(D(100) - (D(100) * cumulative / design), 2)
    severity_hours = cumulative * (D(1) + SEVERITY_WEIGHT * charge["poisoning_index"])
    severity = rhu(
        D(100) - (D(100) * severity_hours / design)
        + REGEN_RECOVERY_PCT * D(charge["regeneration_count"]),
        2,
    )
    severity = clamp(severity, D("0.00"), D("100.00"))
    return cumulative, calendar, severity


def charge_activity_pct(charge):
    return activity_figures(charge)[2]


# --------------------------------------------------------------------------
# storage_position (PRD 3.6)
# --------------------------------------------------------------------------
def storage_position(asset):
    """on_hand / reserved / seasonal_reserve / available, derived from scratch."""
    asset_id = asset["id"]
    on_hand = asset["opening_balance_tons"]
    for order in db.orders.values():
        if (order["destination_asset_id"] == asset_id
                and order["allocation_status"] == "CONSUMED"
                and order.get("produced_tons") is not None):
            on_hand += order["produced_tons"]
    for ship in db.shipments.values():
        if ship["status"] != "DELIVERED":
            continue
        if ship["dest_asset_id"] == asset_id and ship.get("received_tons") is not None:
            on_hand += ship["received_tons"]
        if ship["origin_asset_id"] == asset_id:
            on_hand -= ship["tons"]
    reserved = ZERO
    for ship in db.shipments.values():
        if (ship["origin_asset_id"] == asset_id
                and ship["status"] in ("BOOKED", "IN_TRANSIT")):
            reserved += ship["tons"]
    if db.clock.month in SEASONAL_RESERVE_MONTHS:
        seasonal = rhu(asset["capacity_tons"] * asset["seasonal_reserve_pct"], 3)
    else:
        seasonal = D("0.000")
    on_hand = rhu(on_hand, 3)
    reserved = rhu(reserved, 3)
    available = on_hand - reserved - seasonal
    return {
        "on_hand_tons": on_hand,
        "reserved_tons": reserved,
        "seasonal_reserve_tons": seasonal,
        "available_tons": available,
    }


def reserved_tons_of_other_orders(asset_id, exclude_order_id):
    """Finished tons already reserved into an asset by other RESERVED orders."""
    total = ZERO
    for order in db.orders.values():
        if order["id"] == exclude_order_id:
            continue
        if (order["destination_asset_id"] == asset_id
                and order["allocation_status"] == "RESERVED"):
            total += order["reserved_tons"]
    return total


def inbound_committed_tons(asset_id, exclude_shipment_id=None):
    total = ZERO
    for ship in db.shipments.values():
        if ship["id"] == exclude_shipment_id:
            continue
        if (ship["dest_asset_id"] == asset_id
                and ship["status"] in ("BOOKED", "IN_TRANSIT")):
            total += ship["tons"]
    return total


def outbound_overlap_peak(asset_id, window_start, window_end, extra_tons,
                          exclude_shipment_id=None):
    """The heaviest instant of the proposed half-open window.

    Every already-committed outbound movement whose own half-open window covers
    an instant of this one contributes its tons at that instant; the check is
    aggregate, not pairwise, so the peak is taken over the window's boundary
    instants (tonnage only changes where some window starts).
    """
    live = [s for s in db.shipments.values()
            if s["origin_asset_id"] == asset_id
            and s["status"] in ("BOOKED", "IN_TRANSIT")
            and s["id"] != exclude_shipment_id
            and s["window_start"] < window_end
            and s["window_end"] > window_start]
    instants = [window_start] + [s["window_start"] for s in live
                                 if window_start <= s["window_start"] < window_end]
    peak = ZERO
    for instant in instants:
        total = extra_tons
        for ship in live:
            if ship["window_start"] <= instant < ship["window_end"]:
                total += ship["tons"]
        if total > peak:
            peak = total
    return peak


# --------------------------------------------------------------------------
# emissions_rolling_30d and plant_operating_posture (PRD 3.10 / 2.8)
# --------------------------------------------------------------------------
def reading_tons(rate_lb_per_hour, interval_hours):
    return rhu(rate_lb_per_hour * interval_hours / LB_PER_TON, 3)


def rolling_30d_tons(plant_id, pollutant, extra=None):
    """The plant-and-pollutant rolling mass in the (clock-30d, clock] window."""
    floor = db.clock - timedelta(days=ROLLING_WINDOW_DAYS)
    total = ZERO
    for reading in db.readings.values():
        if reading["plant_id"] != plant_id or reading["pollutant"] != pollutant:
            continue
        if reading["reading_at"] > floor and reading["reading_at"] <= db.clock:
            total += reading["tons"]
    if extra is not None:
        total += extra
    return rhu(total, 3)


def exceeded_pollutants(plant):
    limit = plant["permit_limit_tons_30d"]
    present = set()
    for reading in db.readings.values():
        if reading["plant_id"] == plant["id"]:
            present.add(reading["pollutant"])
    exceeded = [p for p in sorted(present)
                if rolling_30d_tons(plant["id"], p) > limit]
    return sorted(exceeded)


def operating_posture(plant, exceeded=None):
    if exceeded is None:
        exceeded = exceeded_pollutants(plant)
    if plant["permit_status"] == "SUSPENDED" or len(exceeded) >= 2:
        return "FROZEN"
    if len(exceeded) == 1 or plant["psm_program_status"] == "OVERDUE":
        return "RESTRICTED"
    return "NORMAL"


# --------------------------------------------------------------------------
# turnaround_task_schedule (PRD 3.9)
# --------------------------------------------------------------------------
def tasks_of(turnaround_id):
    return by_seq([t for t in db.tasks.values()
                   if t["turnaround_id"] == turnaround_id])


def task_schedule(turnaround_id):
    """Returns (earliest_start_day per task id, critical_path_days).

    The dependency structure is a forest, so a task's earliest start is simply
    its predecessor's earliest start plus that predecessor's duration. Every
    task counts toward the critical path whatever its status.
    """
    tasks = tasks_of(turnaround_id)
    esd = {}
    pending = list(tasks)
    guard = 0
    while pending and guard <= len(tasks) + 1:
        guard += 1
        progressed = False
        still = []
        for task in pending:
            pred_id = task.get("predecessor_task_id")
            if pred_id is None:
                esd[task["id"]] = 0
                progressed = True
                continue
            pred = db.tasks.get(pred_id)
            if pred is None or pred["turnaround_id"] != turnaround_id:
                esd[task["id"]] = 0
                progressed = True
                continue
            if pred["id"] in esd:
                esd[task["id"]] = esd[pred["id"]] + int(pred["duration_days"])
                progressed = True
            else:
                still.append(task)
        pending = still
        if not progressed:
            break
    for task in pending:
        esd.setdefault(task["id"], 0)
    critical = 0
    for task in tasks:
        finish = esd.get(task["id"], 0) + int(task["duration_days"])
        if finish > critical:
            critical = finish
    return esd, critical


def turnaround_counters(turnaround_id):
    tasks = tasks_of(turnaround_id)
    done = len([t for t in tasks if t["status"] == "DONE"])
    return len(tasks), done


def window_days(window_start, window_end):
    return whole_days(window_end, window_start)


# --------------------------------------------------------------------------
# quote_price_per_ton (PRD 3.8)
# --------------------------------------------------------------------------
def quote_gas_basis(quote, plant):
    if quote["pass_through_basis"] == "SPOT_INDEX":
        return plant["spot_gas_index_usd_per_mmbtu"]
    blend = hedged_blend(plant)
    if blend is None:
        return plant["spot_gas_index_usd_per_mmbtu"]
    return blend


def quote_price(quote, plant, line, posture, gas_basis):
    ammonia_cash = gas_basis * GAS_INTENSITY_MMBTU_PER_TON + FIXED_CONVERSION_USD_PER_TON
    feedstock = ammonia_cash * line["ammonia_tons_per_product_ton"]
    cash = feedstock + line["conversion_cost_usd_per_ton"]
    margin = cash * TARGET_MARGIN_PCT
    if margin < MARGIN_FLOOR_USD_PER_TON:
        margin = MARGIN_FLOOR_USD_PER_TON
    list_price = cash + margin
    seasonal = (SPRING_MULTIPLIER
                if quote["expires_at"].astimezone(db.clock.tzinfo).month in SPRING_MONTHS
                else D("1.00"))
    tons = quote["tons"]
    if tons >= VOLUME_TIER_25K_THRESHOLD:
        tier = VOLUME_TIER_25K_FACTOR
    elif tons >= VOLUME_TIER_5K_THRESHOLD:
        tier = VOLUME_TIER_5K_FACTOR
    else:
        tier = D("1.00")
    posture_factor = RESTRICTED_POSTURE_FACTOR if posture == "RESTRICTED" else D("1.00")
    return rhu(list_price * seasonal * tier * posture_factor, 2)


# --------------------------------------------------------------------------
# production_order_landed_cost (PRD 3.6)
# --------------------------------------------------------------------------
def landed_cost(produced_tons, line, final_unit_cost):
    ammonia_tons = rhu(produced_tons * line["ammonia_tons_per_product_ton"], 3)
    feedstock = rhu(ammonia_tons * final_unit_cost, 2)
    conversion = rhu(produced_tons * line["conversion_cost_usd_per_ton"], 2)
    handling = rhu(produced_tons * STORAGE_HANDLING_USD_PER_TON, 2)
    security = (rhu(produced_tons * SECURITY_FEE_USD_PER_TON, 2)
                if line["regulated"] else D("0.00"))
    return feedstock + conversion + handling + security


# --------------------------------------------------------------------------
# shipment_freight_total (PRD 3.7)
# --------------------------------------------------------------------------
def freight(mode, tons, distance_miles):
    rate = MODE_RATE_USD_PER_TON_MILE[mode]
    linehaul = tons * distance_miles * rate
    minimum = MODE_MIN_CHARGE_USD[mode]
    base = rhu(linehaul if linehaul > minimum else minimum, 2)
    surcharge_rate = SURCHARGE_TOP_RATE
    for ceiling, band_rate in SURCHARGE_BANDS:
        if base < ceiling:
            surcharge_rate = band_rate
            break
    fuel = rhu(base * surcharge_rate, 2)
    total = base + fuel
    return {
        "base_freight_usd": base,
        "fuel_surcharge_usd": fuel,
        "freight_total_usd": total,
        "freight_per_ton_usd": rhu(total / tons, 4),
    }


# --------------------------------------------------------------------------
# The campaign ammonia pool (PRD 3.4)
# --------------------------------------------------------------------------
def promised_ammonia_tons(run_id):
    total = ZERO
    for order in db.orders.values():
        if (order["run_id"] == run_id
                and order["allocation_status"] in ("RESERVED", "CONSUMED")):
            total += order["allocated_ammonia_tons"]
    return rhu(total, 3)


def ammonia_basis(run):
    if run["status"] == "COMPLETED" and run.get("actual_ammonia_tons") is not None:
        return run["actual_ammonia_tons"]
    return run["target_ammonia_tons"]


def unallocated_ammonia_tons(run):
    """The pool a reservation draws on.

    A campaign that has not been approved yet has no pool at all -- PRD 3.4 says
    a new campaign opens with `unallocated_ammonia_tons` at 0 -- so the basis
    only becomes available from APPROVED onward, at which point it is the basis
    less everything already promised to RESERVED and CONSUMED orders.
    """
    if run["status"] == "PLANNED":
        return D("0.000")
    return rhu(ammonia_basis(run) - promised_ammonia_tons(run["id"]), 3)
