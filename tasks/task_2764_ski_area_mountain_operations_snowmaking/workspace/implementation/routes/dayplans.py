"""The operating day: publication, weather cascade, admission (PRD 3.8, 3.9)."""
from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import (auth, ALL_ROLES, GUEST_SERVICES_AGENT, LIFT_OPS_MANAGER,
                        MOUNTAIN_OPS_DIRECTOR)
from services import calc, cascade, serialize

bp = Blueprint("dayplans", __name__)

WEATHER_HOLD_WIND_MPH = 60.0
NEW_SNOW_INVALIDATION_IN = 12.0
PASS_TYPES = ("SEASON", "EMPLOYEE", "RECIPROCAL", "DAY_TICKET")
CLOSEABLE_POSTURES = ("PUBLISHED_PARTIAL", "PUBLISHED_FULL", "WEATHER_HOLD")


@bp.route("/day-plans", methods=["POST"])
def create_day_plan():
    auth(MOUNTAIN_OPS_DIRECTOR)
    body = validate.body()
    # Priority 4.
    season = validate.fk(body, "season_id", db.store.seasons, "ERR_SEASON_NOT_FOUND")
    # Priority 5.
    validate.get_str(body, "season_id")
    operating_date = validate.get_date(body, "operating_date")
    stalls = validate.get_int(body, "parking_stalls_total", minimum=0)
    # Priority 10.
    for peer in db.season_day_plans(season["id"]):
        if peer["operating_date"] == operating_date:
            raise ApiError("ERR_DUPLICATE_CODE")
    # Priority 11.
    cascade.require_season_writable(season)
    row = db.new_row({
        "season_id": season["id"],
        "operating_date": operating_date,
        "parking_stalls_total": stalls,
        "posture": "DRAFT",
        "wind_speed_mph": 0.0,
        "wet_bulb_f": 32.0,
        "new_snow_in": 0.0,
        "open_terrain_count": 0,
        "terrain_open_acres": 0.0,
        "open_lift_capacity_pph": 0,
        "raw_ccc": 0,
        "guest_capacity": 0,
        "non_season_pool": 0,
        "admitted_guest_count": 0,
        "non_season_admitted_count": 0,
        "waitlisted_guest_count": 0,
        "parking_stalls_used": 0,
        "weather_updated_at": None,
        "published_at": None,
        "closed_at": None,
    })
    db.store.day_plans[row["id"]] = row
    return response.object_response(serialize.day_plan(row), 201)


@bp.route("/day-plans/<plan_id>", methods=["GET"])
def get_day_plan(plan_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.day_plans, plan_id, "ERR_DAY_PLAN_NOT_FOUND")
    return response.object_response(serialize.day_plan(row), 200)


@bp.route("/day-plans", methods=["GET"])
def list_day_plans():
    auth(*ALL_ROLES)
    limit, offset = validate.pagination()
    rows = db.ordered(db.store.day_plans)
    season_id = validate.query_value("season_id")
    operating_date = validate.query_value("operating_date")
    posture = validate.query_value("posture")
    if season_id:
        rows = [r for r in rows if r["season_id"] == season_id]
    if operating_date:
        rows = [r for r in rows if r["operating_date"] == operating_date]
    if posture:
        rows = [r for r in rows if r["posture"] == posture]
    return response.list_response(rows, serialize.day_plan, limit, offset)


@bp.route("/day-plans/<plan_id>/publish", methods=["POST"])
def publish_day_plan(plan_id):
    auth(MOUNTAIN_OPS_DIRECTOR)
    plan = validate.path_row(db.store.day_plans, plan_id, "ERR_DAY_PLAN_NOT_FOUND")
    season = db.store.seasons.get(plan["season_id"])
    # Priority 11: publish is legal from PRESEASON as well as OPERATING.
    cascade.require_publishable_season(season)
    # Priority 15.
    if plan["posture"] != "DRAFT":
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    areas = db.season_areas(season["id"])
    if not [a for a in areas if a["opening_state"] in calc.OPENABLE_STATES]:
        raise ApiError("ERR_TERRAIN_STATE_INVALID")
    lifts = db.season_lifts(season["id"])
    if not [l for l in lifts if l["service_status"] in ("OPEN", "STANDBY")]:
        raise ApiError("ERR_LIFT_STATE_INVALID")
    plan["posture"] = "PUBLISHED_PARTIAL"
    plan["published_at"] = db.now()
    cascade.recompute_day_plan(plan, force=True)
    if season["season_state"] == "PRESEASON":
        season["season_state"] = "OPERATING"
        db.mark(season)
    return response.object_response(serialize.day_plan(plan), 200)


@bp.route("/day-plans/<plan_id>/opening-report", methods=["GET"])
def opening_report(plan_id):
    auth(*ALL_ROLES)
    plan = validate.path_row(db.store.day_plans, plan_id, "ERR_DAY_PLAN_NOT_FOUND")
    return response.object_response(calc.opening_report(plan), 200)


@bp.route("/day-plans/<plan_id>/weather", methods=["POST"])
def post_weather(plan_id):
    auth(MOUNTAIN_OPS_DIRECTOR, LIFT_OPS_MANAGER)
    plan = validate.path_row(db.store.day_plans, plan_id, "ERR_DAY_PLAN_NOT_FOUND")
    body = validate.body()
    wind = validate.get_num(body, "wind_speed_mph", minimum=0)
    wet_bulb = validate.get_num(body, "wet_bulb_f")
    new_snow = validate.get_num(body, "new_snow_in", required=False, default=0.0,
                                minimum=0)
    season = db.store.seasons.get(plan["season_id"])
    cascade.require_season_writable(season)
    plan["wind_speed_mph"] = wind
    plan["wet_bulb_f"] = wet_bulb
    plan["new_snow_in"] = new_snow
    plan["weather_updated_at"] = db.now()
    db.mark(plan)
    # First consequence: per-lift wind holds, ascending lift_code.
    for lift in db.lifts_by_code(season["id"]):
        if (lift["service_status"] == "OPEN"
                and float(lift["wind_hold_threshold_mph"]) < wind):
            cascade.wind_hold_lift(lift)
    # Second consequence: a foot of new snow invalidates avalanche clearance.
    if new_snow >= NEW_SNOW_INVALIDATION_IN:
        for area in db.areas_by_code(season["id"]):
            if not area["avalanche_terrain"]:
                continue
            area["mitigation_clearance_expires_at"] = None
            db.mark(area)
            if area["opening_state"] == "OPEN":
                cascade.hold_area(area)
            else:
                cascade.reevaluate_readiness(area)
    # Third consequence: the plant-wide weather hold posture.
    if wind >= WEATHER_HOLD_WIND_MPH:
        if plan["posture"] in cascade.PUBLISHED_POSTURES:
            plan["posture"] = "WEATHER_HOLD"
            db.mark(plan)
        for lift in db.lifts_by_code(season["id"]):
            if lift["service_status"] in ("OPEN", "STANDBY"):
                cascade.wind_hold_lift(lift)
    elif plan["posture"] == "WEATHER_HOLD":
        # A reading back under the ceiling restores the posture but releases
        # no lift: each held lift must be released under the hysteresis band.
        plan["posture"] = "PUBLISHED_PARTIAL"
        db.mark(plan)
    cascade.recompute_season_counts(season)
    cascade.recompute_day_plan(plan, force=True)
    cascade.promote_waitlist(plan)
    return response.object_response(serialize.day_plan(plan), 200)


@bp.route("/day-plans/<plan_id>/close-day", methods=["POST"])
def close_day(plan_id):
    auth(MOUNTAIN_OPS_DIRECTOR)
    plan = validate.path_row(db.store.day_plans, plan_id, "ERR_DAY_PLAN_NOT_FOUND")
    body = validate.body()
    season_final = validate.get_bool(body, "season_final", required=False,
                                    default=False)
    season = db.store.seasons.get(plan["season_id"])
    cascade.require_season_writable(season)
    # Priority 15.
    if plan["posture"] not in CLOSEABLE_POSTURES:
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    plan["posture"] = "DAY_CLOSED"
    plan["closed_at"] = db.now()
    for row in db.plan_reservations(plan["id"]):
        if row["state"] in ("CONFIRMED", "CHECKED_IN", "WAITLISTED"):
            row["state"] = "RELEASED"
            row["released_at"] = db.now()
            row["allocated_stalls"] = 0
            db.mark(row)
    plan.update(calc.reservation_counters(plan))
    db.mark(plan)
    # The mountain is put to bed: terrain first, in ascending trail_code order.
    for area in db.areas_by_code(season["id"]):
        if area["opening_state"] in ("OPEN", "PATROL_HOLD"):
            cascade.close_area(area, defer=True)
    for lift in db.lifts_by_code(season["id"]):
        if lift["service_status"] in ("OPEN", "STANDBY", "WIND_HOLD"):
            lift["service_status"] = "CLOSED"
            lift["wind_hold_since"] = None
            db.mark(lift)
    if season_final:
        _close_season(season)
    cascade.recompute_season_counts(season)
    plan.update(calc.day_capacity_figures(plan))
    return response.object_response(serialize.day_plan(plan), 200)


def _close_season(season):
    """PRD 3.9: season_final tears the whole season down for good."""
    season["season_state"] = "CLOSED"
    db.mark(season)
    for area in db.areas_by_code(season["id"]):
        for task in db.area_tasks(area["id"]):
            if task["state"] in ("PLANNED", "DISPATCHED", "DEFERRED"):
                task["state"] = "CANCELLED"
                db.mark(task)
        for session in db.area_sessions(area["id"]):
            if session["state"] in calc.ACTIVE_SESSION_STATES:
                cascade.abort_session(session, "SEASON_CLOSE")
        if area["opening_state"] != "SEASON_CLOSED":
            cascade.season_close_area(area)
    for mission in db.season_missions(season["id"]):
        if mission["state"] in ("PLANNED", "EXECUTED"):
            mission["state"] = "ABORTED"
            db.mark(mission)


@bp.route("/access-reservations", methods=["POST"])
def create_reservation():
    auth(GUEST_SERVICES_AGENT)
    body = validate.body()
    # Priority 4.
    plan = validate.fk(body, "day_plan_id", db.store.day_plans,
                       "ERR_DAY_PLAN_NOT_FOUND")
    # Priority 5.
    validate.get_str(body, "day_plan_id")
    party_code = validate.get_str(body, "party_code", max_len=32)
    pass_type = validate.get_enum(body, "pass_type", PASS_TYPES)
    party_size = validate.get_int(body, "party_size", minimum=1)
    vehicle_count = validate.get_int(body, "vehicle_count", required=False,
                                    default=0, minimum=0)
    expected_version = validate.get_int(body, "expected_day_plan_version",
                                       minimum=0)
    # Priority 10: party_code is unique inside its day plan.
    for peer in db.plan_reservations(plan["id"]):
        if peer["party_code"] == party_code:
            raise ApiError("ERR_DUPLICATE_CODE")
    # Priority 11: admission additionally requires OPERATING.
    season = db.store.seasons.get(plan["season_id"])
    cascade.require_season_writable(season, require_operating=True)
    # Priority 16: WEATHER_HOLD blocks admission.
    if plan["posture"] not in cascade.PUBLISHED_POSTURES:
        raise ApiError("ERR_DAY_PLAN_NOT_PUBLISHED")
    # Priority 18.
    if expected_version != plan["version"]:
        raise ApiError("ERR_STALE_DAY_PLAN_VERSION")
    state, reason, stalls = calc.allocate_admission(plan, pass_type, party_size,
                                                    vehicle_count)
    row = db.new_row({
        "day_plan_id": plan["id"],
        "party_code": party_code,
        "pass_type": pass_type,
        "party_size": party_size,
        "vehicle_count": vehicle_count,
        "state": state,
        "allocated_stalls": stalls,
        "waitlist_reason": reason,
        "confirmed_at": db.now() if state == "CONFIRMED" else None,
        "checked_in_at": None,
        "released_at": None,
    })
    db.store.reservations[row["id"]] = row
    cascade.recompute_day_plan(plan, force=True)
    return response.object_response(serialize.reservation(row), 201)


@bp.route("/access-reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.reservations, reservation_id,
                            "ERR_RESERVATION_NOT_FOUND")
    return response.object_response(serialize.reservation(row), 200)


@bp.route("/day-plans/<plan_id>/access-reservations", methods=["GET"])
def list_plan_reservations(plan_id):
    auth(*ALL_ROLES)
    plan = validate.path_row(db.store.day_plans, plan_id, "ERR_DAY_PLAN_NOT_FOUND")
    limit, offset = validate.pagination()
    rows = db.plan_reservations(plan["id"])
    state = validate.query_value("state")
    pass_type = validate.query_value("pass_type")
    reason = validate.query_value("waitlist_reason")
    if state:
        rows = [r for r in rows if r["state"] == state]
    if pass_type:
        rows = [r for r in rows if r["pass_type"] == pass_type]
    if reason:
        rows = [r for r in rows if r["waitlist_reason"] == reason]
    return response.list_response(rows, serialize.reservation, limit, offset)


@bp.route("/access-reservations/<reservation_id>/check-in", methods=["POST"])
def check_in(reservation_id):
    auth(GUEST_SERVICES_AGENT)
    row = validate.path_row(db.store.reservations, reservation_id,
                            "ERR_RESERVATION_NOT_FOUND")
    plan = db.store.day_plans.get(row["day_plan_id"])
    season = db.store.seasons.get(plan["season_id"]) if plan else None
    cascade.require_season_writable(season)
    # Priority 15.
    if row["state"] != "CONFIRMED":
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    # Priority 16.
    if plan["posture"] not in cascade.PUBLISHED_POSTURES:
        raise ApiError("ERR_DAY_PLAN_NOT_PUBLISHED")
    row["state"] = "CHECKED_IN"
    row["checked_in_at"] = db.now()
    db.mark(row)
    return response.object_response(serialize.reservation(row), 200)


@bp.route("/access-reservations/<reservation_id>/release", methods=["POST"])
def release_reservation(reservation_id):
    auth(GUEST_SERVICES_AGENT)
    row = validate.path_row(db.store.reservations, reservation_id,
                            "ERR_RESERVATION_NOT_FOUND")
    plan = db.store.day_plans.get(row["day_plan_id"])
    season = db.store.seasons.get(plan["season_id"]) if plan else None
    cascade.require_season_writable(season)
    # Priority 15.
    if row["state"] not in ("CONFIRMED", "CHECKED_IN", "WAITLISTED"):
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    row["state"] = "RELEASED"
    row["released_at"] = db.now()
    row["allocated_stalls"] = 0
    db.mark(row)
    plan.update(calc.reservation_counters(plan))
    db.mark(plan)
    cascade.promote_waitlist(plan)
    return response.object_response(serialize.reservation(row), 200)
