"""State machine transitions, readiness gating and deterministic cascades."""
from datetime import timedelta
from decimal import Decimal

import db
from errors import ApiError
from util import dec, rhu, rhu_dec, floor_int
from services import calc

PUBLISHED_POSTURES = ("PUBLISHED_PARTIAL", "PUBLISHED_FULL")
ACTIVE_POSTURES = ("PUBLISHED_PARTIAL", "PUBLISHED_FULL", "WEATHER_HOLD")
LIVE_TASK_STATES = ("PLANNED", "DISPATCHED")


# --------------------------------------------------------- active day plan

def active_day_plan(season_id):
    """PRD 2.10: operating_date DESC then created_at DESC; never by id."""
    candidates = [p for p in db.season_day_plans(season_id)
                  if p["posture"] in ACTIVE_POSTURES]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["operating_date"], p["created_at"], p["_seq"]),
                    reverse=True)
    return candidates[0]


def require_active_day_plan(season_id, require_published=False):
    plan = active_day_plan(season_id)
    if plan is None:
        raise ApiError("ERR_DAY_PLAN_NOT_PUBLISHED")
    if require_published and plan["posture"] not in PUBLISHED_POSTURES:
        raise ApiError("ERR_DAY_PLAN_NOT_PUBLISHED")
    return plan


# --------------------------------------------------------- readiness gates

def readiness_failure(area):
    """First failing opening gate, in the PRD 2.7 priority order, or None."""
    season = db.season_of_area(area)
    depth, _count = calc.terrain_base_depth(area)
    if dec(depth) < dec(area["min_open_base_depth_in"]):
        return "ERR_BASE_DEPTH_INSUFFICIENT"
    if not calc.groom_is_current(area):
        return "ERR_GROOM_NOT_CURRENT"
    if area["avalanche_terrain"] and not calc.mitigation_is_current(area):
        return "ERR_MITIGATION_NOT_CURRENT"
    minimum = season["min_patrollers_per_open_area"] if season else 0
    if calc.assigned_patroller_count(area) < minimum:
        return "ERR_PATROL_STAFFING_INSUFFICIENT"
    if area["terrain_class"] == "PARK":
        if area["park_state"] != "PARK_INSPECTED":
            return "ERR_PARK_NOT_INSPECTED"
        if dec(area["park_risk_score"] or 0.0) > calc.PARK_RISK_MAX_OPEN:
            return "ERR_PARK_RISK_TOO_HIGH"
    return None


def lift_failure(area):
    """Serving lift gates, checked after the terrain gates (priority 31, 32)."""
    lift = db.store.lifts.get(area["serving_lift_id"])
    if lift is None or lift["service_status"] != "OPEN":
        return "ERR_SERVING_LIFT_NOT_OPEN"
    if not inspection_current(lift):
        return "ERR_LIFT_INSPECTION_EXPIRED"
    return None


def inspection_current(lift):
    if lift["mechanical_status"] != "INSPECTION_PASSED":
        return False
    valid_until = lift.get("inspection_valid_until")
    if valid_until is None:
        return False
    return db.now() < valid_until


def readiness_ok(area):
    return readiness_failure(area) is None


def reevaluate_readiness(area):
    """Symmetric PREP <-> READY re-gate. Never auto-reopens a held area."""
    if area["opening_state"] == "PREP" and readiness_ok(area):
        area["opening_state"] = "READY"
        db.mark(area)
    elif area["opening_state"] == "READY" and not readiness_ok(area):
        area["opening_state"] = "PREP"
        db.mark(area)


def regate_held_area(area):
    """PATROL_HOLD -> OPEN only when every opening gate holds again."""
    if area["opening_state"] != "PATROL_HOLD":
        return False
    if readiness_failure(area) is not None or lift_failure(area) is not None:
        return False
    area["opening_state"] = "OPEN"
    db.mark(area)
    return True


# --------------------------------------------------------- water bookkeeping

def add_reserved(season, amount):
    season["water_reserved_af"] = rhu(dec(season["water_reserved_af"]) + dec(amount), 3)
    db.mark(season)


def release_reserved(season, amount):
    season["water_reserved_af"] = rhu(dec(season["water_reserved_af"]) - dec(amount), 3)
    db.mark(season)


# --------------------------------------------------------- session lifecycle

def recompute_pump_peak(pump):
    peak = calc.pump_house_peak(pump["id"])
    if peak != pump["peak_committed_gpm"]:
        pump["peak_committed_gpm"] = peak
        db.mark(pump)


def abort_session(session, reason):
    """Aborted sessions zero every metered figure and release their water."""
    previous = session["state"]
    pump = db.store.pumps.get(session["pump_house_id"])
    season = db.season_of_session(session)
    session["state"] = "ABORTED"
    session["abort_reason"] = reason
    session["ended_at"] = db.now()
    session["last_running_since"] = None
    session["water_af_actual"] = 0.0
    session["snow_swe_af"] = 0.0
    session["energy_kwh"] = 0.0
    session["energy_cost_usd"] = 0.0
    session["demand_surcharge_applied"] = False
    db.mark(session)
    if season is not None:
        release_reserved(season, session["water_af_reserved"])
    if pump is not None:
        if previous == "RUNNING":
            pump["active_session_count"] = max(0, pump["active_session_count"] - 1)
            db.mark(pump)
        recompute_pump_peak(pump)


def complete_session(session):
    pump = db.store.pumps.get(session["pump_house_id"])
    season = db.season_of_session(session)
    area = db.area_of_session(session)
    if session["state"] == "RUNNING" and session.get("last_running_since"):
        elapsed = db.now() - session["last_running_since"]
        session["accumulated_run_minutes"] += floor_int(
            dec(elapsed.total_seconds()) / Decimal("60"))
    session["state"] = "COMPLETED"
    session["ended_at"] = db.now()
    session["last_running_since"] = None
    actual = calc.water_af(session["gpm"], session["accumulated_run_minutes"])
    session["water_af_actual"] = actual
    yield_factor = dec(session["snow_yield_factor"] or 0.0)
    session["snow_swe_af"] = rhu(dec(actual) * yield_factor, 3)
    kwh, cost, surcharge = calc.energy_cost(session, pump, season)
    session["energy_kwh"] = kwh
    session["energy_cost_usd"] = cost
    session["demand_surcharge_applied"] = surcharge
    db.mark(session)
    release_reserved(season, session["water_af_reserved"])
    season["water_used_af"] = rhu(dec(season["water_used_af"]) + dec(actual), 3)
    season["snow_produced_swe_af"] = rhu(
        dec(season["snow_produced_swe_af"]) + dec(session["snow_swe_af"]), 3)
    db.mark(season)
    if area is not None:
        area["machine_swe_af"] = rhu(
            dec(area["machine_swe_af"]) + dec(session["snow_swe_af"]), 3)
        db.mark(area)
    if pump is not None:
        pump["active_session_count"] = max(0, pump["active_session_count"] - 1)
        db.mark(pump)
        recompute_pump_peak(pump)


# --------------------------------------------------------- terrain cascades

def defer_tasks(area):
    for task in db.area_tasks(area["id"]):
        if task["state"] in LIVE_TASK_STATES:
            task["state"] = "DEFERRED"
            db.mark(task)


def abort_area_sessions(area, reason):
    for session in db.area_sessions(area["id"]):
        if session["state"] in calc.ACTIVE_SESSION_STATES:
            abort_session(session, reason)


def hold_area(area):
    """OPEN -> PATROL_HOLD with its grooming and snowmaking cascade."""
    if area["opening_state"] != "OPEN":
        return False
    area["opening_state"] = "PATROL_HOLD"
    db.mark(area)
    defer_tasks(area)
    abort_area_sessions(area, "TERRAIN_HOLD")
    return True


def close_area(area, defer=True):
    area["opening_state"] = "CLOSED"
    db.mark(area)
    if defer:
        defer_tasks(area)


def season_close_area(area):
    area["opening_state"] = "SEASON_CLOSED"
    db.mark(area)


# --------------------------------------------------------- lift cascades

def cascade_lift_lost_open(lift):
    """Every OPEN area served by this lift drops to PATROL_HOLD, trail_code ASC."""
    for area in db.areas_by_code(lift["season_id"]):
        if area["serving_lift_id"] == lift["id"]:
            hold_area(area)


def wind_hold_lift(lift):
    previous = lift["service_status"]
    lift["service_status"] = "WIND_HOLD"
    lift["wind_hold_since"] = db.now()
    db.mark(lift)
    if previous == "OPEN":
        cascade_lift_lost_open(lift)


def mech_hold_lift(lift):
    previous = lift["service_status"]
    lift["service_status"] = "MECH_HOLD"
    db.mark(lift)
    if previous == "OPEN":
        cascade_lift_lost_open(lift)


# --------------------------------------------------------- recomputations

def recompute_season_counts(season):
    count = len([a for a in db.season_areas(season["id"])
                 if a["opening_state"] == "OPEN"])
    if count != season["open_area_count"]:
        season["open_area_count"] = count
        db.mark(season)


def apply_capacity(plan):
    figures = calc.day_capacity_figures(plan)
    plan.update(figures)
    plan.update(calc.reservation_counters(plan))


def recompute_posture(plan):
    if plan["posture"] not in PUBLISHED_POSTURES:
        return
    areas = db.season_areas(plan["season_id"])
    live = [a for a in areas if a["opening_state"] != "SEASON_CLOSED"]
    if live and plan["open_terrain_count"] == len(live):
        plan["posture"] = "PUBLISHED_FULL"
    else:
        plan["posture"] = "PUBLISHED_PARTIAL"


DERIVED_PLAN_KEYS = (
    "open_lift_capacity_pph", "open_terrain_count", "terrain_open_acres",
    "raw_ccc", "guest_capacity", "non_season_pool", "admitted_guest_count",
    "non_season_admitted_count", "waitlisted_guest_count", "parking_stalls_used",
    "posture",
)


def recompute_day_plan(plan, force=False):
    """Recompute the derived day-plan figures; version moves only on a change."""
    if plan is None:
        return
    before = dict((key, plan.get(key)) for key in DERIVED_PLAN_KEYS)
    apply_capacity(plan)
    recompute_posture(plan)
    if force or any(plan.get(key) != before[key] for key in DERIVED_PLAN_KEYS):
        db.mark(plan)


def recompute_active_day_plan(season_id, force=False):
    plan = active_day_plan(season_id)
    if plan is not None:
        recompute_day_plan(plan, force=force)
    return plan


def refresh_after_terrain_change(season, force=False):
    recompute_season_counts(season)
    return recompute_active_day_plan(season["id"], force=force)


# --------------------------------------------------------- waitlist sweep

def promote_waitlist(plan):
    """Sweep the whole waitlist in created_at ASC; skip and continue on misses."""
    if plan["posture"] not in PUBLISHED_POSTURES:
        return []
    promoted = []
    candidates = [r for r in db.plan_reservations(plan["id"])
                  if r["state"] == "WAITLISTED"]
    for row in candidates:
        state, _reason, stalls = calc.allocate_admission(
            plan, row["pass_type"], row["party_size"], row["vehicle_count"])
        if state != "CONFIRMED":
            continue
        row["state"] = "CONFIRMED"
        row["waitlist_reason"] = "NONE"
        row["allocated_stalls"] = stalls
        row["confirmed_at"] = db.now()
        db.mark(row)
        promoted.append(row)
        plan.update(calc.reservation_counters(plan))
    if promoted:
        plan.update(calc.reservation_counters(plan))
        db.mark(plan)
    return promoted


# --------------------------------------------------------- season guards

def require_season_writable(season, require_operating=False):
    """Priority 11: CLOSED forbids every write; some flows demand OPERATING."""
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    if season["season_state"] == "CLOSED":
        raise ApiError("ERR_SEASON_NOT_OPERATING")
    if require_operating and season["season_state"] != "OPERATING":
        raise ApiError("ERR_SEASON_NOT_OPERATING")
    return season


def require_publishable_season(season):
    if season["season_state"] not in ("PRESEASON", "OPERATING"):
        raise ApiError("ERR_SEASON_NOT_OPERATING")
    return season
