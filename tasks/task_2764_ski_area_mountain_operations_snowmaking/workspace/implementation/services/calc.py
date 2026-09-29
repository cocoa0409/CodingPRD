"""Every calculation rule from PRD section 3 / SCAFFOLD calculations."""
from datetime import timedelta
from decimal import Decimal

import db
from util import dec, rhu, rhu_dec, rhu_int, floor_int

# --- terrain_base_depth
BASE_DEPTH_LOOKBACK_HOURS = 48

# --- groom_coverage_pct
CAT_SWATH_ACRES_PER_PASS = Decimal("0.75")
WINCH_EFFICIENCY_FACTOR = Decimal("0.8")
BLACK_CLASS_FACTOR = Decimal("0.9")
GROOM_READY_MIN_COVERAGE_PCT = Decimal("70.0")

# --- park_risk_score
FEATURE_BASE_WEIGHT = {
    "JUMP": Decimal("6.0"),
    "RAIL": Decimal("4.0"),
    "JIB": Decimal("3.0"),
    "HALFPIPE": Decimal("12.0"),
}
SIZE_MULTIPLIER = {"S": Decimal("1.0"), "M": Decimal("1.5"), "L": Decimal("2.0")}
EXPOSURE_FREE_FEATURES = 5
EXPOSURE_STEP = Decimal("0.1")
PARK_RISK_MAX_OPEN = Decimal("60.0")

# --- snowmaking_wet_bulb_yield
WET_BULB_MAX_F = Decimal("27.0")
WET_BULB_MARGINAL_F = Decimal("24.0")
WET_BULB_GOOD_F = Decimal("20.0")
YIELD_MARGINAL = Decimal("0.60")
YIELD_GOOD = Decimal("0.85")
YIELD_IDEAL = Decimal("1.00")

# --- snowmaking_water_volume
GALLONS_PER_ACRE_FOOT = Decimal("325851")

# --- snowmaking_energy_cost
DEMAND_SURCHARGE_GPM_SHARE = Decimal("0.80")
DEMAND_SURCHARGE_MULTIPLIER = Decimal("1.12")

# --- day_guest_capacity
CCC_UTILIZATION_FACTOR = Decimal("0.60")
CROWDING_DENSITY_THRESHOLD = Decimal("25.0")
CROWDING_REDUCTION_FACTOR = Decimal("0.85")
NON_SEASON_POOL_SHARE = Decimal("0.70")

# --- lift staffing
OPERATOR_TURNAROUND_MINUTES = 30

ACTIVE_SESSION_STATES = ("SCHEDULED", "RUNNING", "PAUSED")
OPENABLE_STATES = ("READY", "OPEN", "PATROL_HOLD")


# ----------------------------------------------------------- terrain depth

def terrain_base_depth(area):
    """Collapse in-window stake readings to one per stake, then apply policy."""
    season = db.season_of_area(area)
    cutoff = db.now() - timedelta(hours=BASE_DEPTH_LOOKBACK_HOURS)
    latest = {}
    for reading in db.area_readings(area["id"]):
        if reading["measured_at"] < cutoff:
            continue
        stake = reading["stake_code"]
        current = latest.get(stake)
        if current is None:
            latest[stake] = reading
            continue
        if reading["measured_at"] > current["measured_at"]:
            latest[stake] = reading
        elif (reading["measured_at"] == current["measured_at"]
              and (reading["created_at"], reading["_seq"])
              > (current["created_at"], current["_seq"])):
            latest[stake] = reading
    depths = [dec(r["depth_in"]) for r in latest.values()]
    count = len(depths)
    if count == 0:
        return 0.0, 0
    policy = season["base_depth_policy"] if season else "MEAN_OF_STAKES"
    if policy == "MIN_OF_STAKES":
        return rhu(min(depths), 1), count
    total = sum(depths, Decimal("0"))
    return rhu(total / Decimal(count), 1), count


# ----------------------------------------------------------- groom coverage

def groom_coverage_pct(passes_completed, acres, winch_required, terrain_class):
    winch = WINCH_EFFICIENCY_FACTOR if winch_required else Decimal("1.0")
    klass = BLACK_CLASS_FACTOR if terrain_class == "BLACK" else Decimal("1.0")
    groomed = dec(passes_completed) * CAT_SWATH_ACRES_PER_PASS * winch * klass
    raw = groomed / dec(acres) * Decimal("100")
    rounded = rhu_dec(raw, 1)
    if rounded > Decimal("100.0"):
        rounded = Decimal("100.0")
    return float(rounded)


def groom_is_current(area):
    """groom_ready: coverage floor met and inside the freshness window."""
    season = db.season_of_area(area)
    stamped = area.get("last_groomed_at")
    if stamped is None or season is None:
        return False
    if dec(area.get("groom_coverage_pct") or 0.0) < GROOM_READY_MIN_COVERAGE_PCT:
        return False
    expires = stamped + timedelta(hours=season["groom_freshness_hours"])
    return db.now() < expires


# ----------------------------------------------------------- park risk

def park_risk_score(features):
    raw = Decimal("0")
    for feature in features:
        weight = FEATURE_BASE_WEIGHT[feature["feature_type"]]
        raw += weight * SIZE_MULTIPLIER[feature["size_class"]]
    count = len(features)
    extra = count - EXPOSURE_FREE_FEATURES
    if extra < 0:
        extra = 0
    factor = Decimal("1.0") + EXPOSURE_STEP * Decimal(extra)
    rounded = rhu_dec(raw * factor, 1)
    if rounded > Decimal("100.0"):
        rounded = Decimal("100.0")
    return float(rounded)


# ----------------------------------------------------------- derived counts

def assigned_patroller_count(area):
    return len([p for p in db.store.patrollers.values()
                if p.get("assigned_terrain_area_id") == area["id"]
                and p["status"] == "AVAILABLE"])


def staffed_operator_count(lift):
    clock = db.now()
    total = 0
    for row in db.store.staff.values():
        if row["lift_id"] != lift["id"] or row["state"] != "ASSIGNED":
            continue
        if row["shift_start"] <= clock < row["shift_end"]:
            total += 1
    return total


def mitigation_is_current(area):
    expires = area.get("mitigation_clearance_expires_at")
    if expires is None:
        return False
    return db.now() < expires


# ----------------------------------------------------------- snowmaking

def wet_bulb_yield_factor(wet_bulb_f):
    """Returns None when the wet bulb is too warm to make snow at all."""
    wb = dec(wet_bulb_f)
    if wb > WET_BULB_MAX_F:
        return None
    if wb > WET_BULB_MARGINAL_F:
        return YIELD_MARGINAL
    if wb > WET_BULB_GOOD_F:
        return YIELD_GOOD
    return YIELD_IDEAL


def water_af(gpm, run_minutes):
    return rhu(dec(gpm) * dec(run_minutes) / GALLONS_PER_ACRE_FOOT, 3)


# ----------------------------------------------------------- capacity sweep

def _spans(intervals):
    points = set()
    for start, end, _gpm in intervals:
        points.add(start)
        points.add(end)
    ordered = sorted(points)
    return [(ordered[i], ordered[i + 1]) for i in range(len(ordered) - 1)]


def _occupancy(intervals, span_start, span_end):
    total = 0
    for start, end, gpm in intervals:
        if start < span_end and end > span_start:
            total += gpm
    return total


def _intervals(sessions, extra=None):
    out = [(s["window_start"], s["window_end"], s["gpm"]) for s in sessions]
    if extra is not None:
        out.append(extra)
    return out


def active_pump_sessions(pump_id, exclude_id=None):
    return [s for s in db.pump_sessions(pump_id)
            if s["state"] in ACTIVE_SESSION_STATES and s["id"] != exclude_id]


def pump_house_peak(pump_id):
    intervals = _intervals(active_pump_sessions(pump_id))
    if not intervals:
        return 0
    return max(_occupancy(intervals, a, b) for a, b in _spans(intervals))


def pump_capacity_would_exceed(pump, new_start, new_end, new_gpm):
    """True when any boundary span inside the new window breaches max_gpm."""
    peers = active_pump_sessions(pump["id"])
    intervals = _intervals(peers, (new_start, new_end, new_gpm))
    for span_start, span_end in _spans(intervals):
        if span_start >= new_end or span_end <= new_start:
            continue
        if _occupancy(intervals, span_start, span_end) > pump["max_gpm"]:
            return True
    return False


def plant_capacity_would_exceed(season, new_start, new_end, new_gpm):
    peers = [s for s in db.season_sessions(season["id"])
             if s["state"] in ACTIVE_SESSION_STATES]
    intervals = _intervals(peers, (new_start, new_end, new_gpm))
    for span_start, span_end in _spans(intervals):
        if _occupancy(intervals, span_start, span_end) > season["plant_max_gpm"]:
            return True
    return False


# ----------------------------------------------------------- energy pricing

def energy_cost(session, pump, season):
    """Tiered per-window energy pricing; returns (kwh, cost, surcharge_flag)."""
    minutes_total = session["accumulated_run_minutes"]
    kwh_total = rhu_dec(dec(session["water_af_actual"])
                        * dec(season["snowmaking_kwh_per_af"]), 3)
    threshold = DEMAND_SURCHARGE_GPM_SHARE * dec(season["plant_max_gpm"])
    surcharge = dec(pump["peak_committed_gpm"]) >= threshold
    if minutes_total <= 0:
        return float(kwh_total), 0.0, bool(surcharge)
    windows = sorted(season["energy_windows"], key=lambda w: w["start_hour_utc"])
    tally = [0] * len(windows)
    start = session["window_start"]
    for offset in range(minutes_total):
        hour = (start + timedelta(minutes=offset)).hour
        for index, window in enumerate(windows):
            if window["start_hour_utc"] <= hour < window["end_hour_utc"]:
                tally[index] += 1
                break
    base_cost = Decimal("0")
    for index, window in enumerate(windows):
        window_minutes = tally[index]
        if window_minutes == 0:
            continue
        kwh_window = rhu_dec(kwh_total * Decimal(window_minutes)
                             / Decimal(minutes_total), 3)
        base_cost += rhu_dec(kwh_window * dec(window["price_usd_per_kwh"]), 2)
    if surcharge:
        cost = rhu_dec(base_cost * DEMAND_SURCHARGE_MULTIPLIER, 2)
    else:
        cost = rhu_dec(base_cost, 2)
    return float(kwh_total), float(cost), bool(surcharge)


# ----------------------------------------------------------- day capacity

def day_capacity_figures(plan):
    """Single pass comfortable carrying capacity chain (PRD 3.9)."""
    season_id = plan["season_id"]
    open_pph = sum(l["hourly_capacity_pph"] for l in db.season_lifts(season_id)
                   if l["service_status"] == "OPEN")
    open_areas = [a for a in db.season_areas(season_id)
                  if a["opening_state"] == "OPEN"]
    acres_total = Decimal("0")
    for area in open_areas:
        acres_total += dec(area["acres"])
    open_acres = rhu_dec(acres_total, 1)
    raw_ccc = floor_int(dec(open_pph) * CCC_UTILIZATION_FACTOR)
    if open_acres == 0:
        density = Decimal("0.0")
    else:
        density = dec(raw_ccc) / open_acres
    factor = (CROWDING_REDUCTION_FACTOR if density > CROWDING_DENSITY_THRESHOLD
              else Decimal("1.00"))
    guest_capacity = floor_int(dec(raw_ccc) * factor)
    non_season_pool = floor_int(dec(guest_capacity) * NON_SEASON_POOL_SHARE)
    return {
        "open_lift_capacity_pph": open_pph,
        "open_terrain_count": len(open_areas),
        "terrain_open_acres": float(open_acres),
        "raw_ccc": raw_ccc,
        "guest_capacity": guest_capacity,
        "non_season_pool": non_season_pool,
    }


def reservation_counters(plan):
    """Counters are always recomputed from the reservation set (PRD 3.9)."""
    admitted = 0
    non_season = 0
    waitlisted = 0
    stalls = 0
    for row in db.plan_reservations(plan["id"]):
        if row["state"] in ("CONFIRMED", "CHECKED_IN"):
            admitted += row["party_size"]
            stalls += row["allocated_stalls"]
            if row["pass_type"] in ("DAY_TICKET", "RECIPROCAL"):
                non_season += row["party_size"]
        elif row["state"] == "WAITLISTED":
            waitlisted += row["party_size"]
    return {
        "admitted_guest_count": admitted,
        "non_season_admitted_count": non_season,
        "waitlisted_guest_count": waitlisted,
        "parking_stalls_used": stalls,
    }


def allocate_admission(plan, pass_type, party_size, vehicle_count):
    """Four bucket waterfall; the first failing bucket decides (PRD 3.9)."""
    counters = reservation_counters(plan)
    if party_size > plan["guest_capacity"]:
        return "DENIED", "NONE", 0
    free_stalls = plan["parking_stalls_total"] - counters["parking_stalls_used"]
    if vehicle_count > free_stalls:
        return "WAITLISTED", "PARKING", 0
    if pass_type in ("DAY_TICKET", "RECIPROCAL"):
        if counters["non_season_admitted_count"] + party_size > plan["non_season_pool"]:
            return "WAITLISTED", "CAPACITY", 0
    if counters["admitted_guest_count"] + party_size > plan["guest_capacity"]:
        return "WAITLISTED", "CAPACITY", 0
    return "CONFIRMED", "NONE", vehicle_count


# ----------------------------------------------------------- season ledger

def season_accounting(season):
    sessions = db.season_sessions(season["id"])
    used = Decimal("0")
    reserved = Decimal("0")
    produced = Decimal("0")
    energy_total = Decimal("0")
    completed = 0
    aborted = 0
    for row in sessions:
        if row["state"] == "COMPLETED":
            completed += 1
            used += dec(row["water_af_actual"])
            produced += dec(row["snow_swe_af"])
            energy_total += dec(row["energy_cost_usd"])
        elif row["state"] == "ABORTED":
            aborted += 1
        if row["state"] in ACTIVE_SESSION_STATES:
            reserved += dec(row["water_af_reserved"])
    areas = db.season_areas(season["id"])
    open_acres = Decimal("0")
    openable_acres = Decimal("0")
    live_acres = Decimal("0")
    open_count = 0
    for area in areas:
        acres = dec(area["acres"])
        if area["opening_state"] == "OPEN":
            open_count += 1
            open_acres += acres
        if area["opening_state"] in OPENABLE_STATES:
            openable_acres += acres
        if area["opening_state"] != "SEASON_CLOSED":
            live_acres += acres
    right = dec(season["water_right_seasonal_af"])
    remaining = rhu_dec(right - used - reserved, 3)
    open_acres_r = rhu_dec(open_acres, 1)
    if live_acres == 0:
        open_pct = Decimal("0.0")
    else:
        open_pct = rhu_dec(open_acres / live_acres * Decimal("100"), 1)
    return {
        "season_id": season["id"],
        "water_right_seasonal_af": float(rhu_dec(right, 3)),
        "water_used_af": float(rhu_dec(used, 3)),
        "water_reserved_af": float(rhu_dec(reserved, 3)),
        "water_right_remaining_af": float(remaining),
        "snow_produced_swe_af": float(rhu_dec(produced, 3)),
        "energy_cost_total_usd": float(rhu_dec(energy_total, 2)),
        "completed_session_count": completed,
        "aborted_session_count": aborted,
        "open_area_count": open_count,
        "open_acres": float(open_acres_r),
        "openable_acres": float(rhu_dec(openable_acres, 1)),
        "terrain_open_pct": float(open_pct),
        "machine_swe_by_area": [
            {
                "terrain_area_id": area["id"],
                "trail_code": area["trail_code"],
                "machine_swe_af": float(rhu_dec(dec(area["machine_swe_af"]), 3)),
            }
            for area in sorted(areas, key=lambda a: a["trail_code"])
        ],
    }


def opening_report(plan):
    season_id = plan["season_id"]
    areas = db.season_areas(season_id)
    lifts = db.season_lifts(season_id)
    open_acres = Decimal("0")
    openable_acres = Decimal("0")
    live_acres = Decimal("0")
    held = 0
    for area in areas:
        acres = dec(area["acres"])
        if area["opening_state"] == "OPEN":
            open_acres += acres
        if area["opening_state"] in OPENABLE_STATES:
            openable_acres += acres
        if area["opening_state"] != "SEASON_CLOSED":
            live_acres += acres
        if area["opening_state"] == "PATROL_HOLD":
            held += 1
    if live_acres == 0:
        open_pct = Decimal("0.0")
    else:
        open_pct = rhu_dec(open_acres / live_acres * Decimal("100"), 1)
    return {
        "day_plan_id": plan["id"],
        "operating_date": plan["operating_date"],
        "posture": plan["posture"],
        "wind_speed_mph": plan["wind_speed_mph"],
        "wet_bulb_f": plan["wet_bulb_f"],
        "open_terrain_count": plan["open_terrain_count"],
        "terrain_open_acres": plan["terrain_open_acres"],
        "openable_acres": float(rhu_dec(openable_acres, 1)),
        "terrain_open_pct": float(open_pct),
        "open_lift_capacity_pph": plan["open_lift_capacity_pph"],
        "raw_ccc": plan["raw_ccc"],
        "guest_capacity": plan["guest_capacity"],
        "non_season_pool": plan["non_season_pool"],
        "admitted_guest_count": plan["admitted_guest_count"],
        "non_season_admitted_count": plan["non_season_admitted_count"],
        "waitlisted_guest_count": plan["waitlisted_guest_count"],
        "parking_stalls_total": plan["parking_stalls_total"],
        "parking_stalls_used": plan["parking_stalls_used"],
        "held_area_count": held,
        "wind_held_lift_count": len([l for l in lifts
                                     if l["service_status"] == "WIND_HOLD"]),
        "mech_held_lift_count": len([l for l in lifts
                                     if l["service_status"] == "MECH_HOLD"]),
    }
