"""Energy routes: interruptible windows, energy events, power waivers."""
import uuid
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import err
from response import (ok, list_response, require_role, require_auth, get_body,
                      req_str, req_enum, req_int, parse_dt)
from services import (get_mill, get_window, get_event, get_heat, new_common,
                      bump, refresh_posture, open_scorecard, abort_heat,
                      recompute_scorecard_profit, EVENT_MIN_GAP_MINUTES)

bp = Blueprint("energy", __name__)


@bp.route("/mills/<millId>/interruptible-windows", methods=["POST"])
def create_window(millId):
    require_role("EnergyDispatcher")
    get_mill(millId)
    body = get_body()
    label = req_str(body, "label")
    start = parse_dt(req_str(body, "start_at"), "start_at")
    end = parse_dt(req_str(body, "end_at"), "end_at")
    credit = req_int(body, "curtailment_credit_cents", ge=0)
    if end <= start:
        raise err("ERR_INVALID_REQUEST", "end_at must be after start_at")
    win = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "label": label,
        "start_at": start,
        "end_at": end,
        "curtailment_credit_cents": credit,
        "linked_event_id": None,
        "status": "SCHEDULED",
        **new_common(),
    }
    db.windows[win["id"]] = win
    return ok(win, 201)


@bp.route("/mills/<millId>/interruptible-windows", methods=["GET"])
def list_windows(millId):
    require_auth()
    get_mill(millId)
    rows = [w for w in db.windows.values() if w["mill_id"] == millId]
    return list_response(rows, {"status": "status", "linked_event_id": "linked_event_id"})


@bp.route("/mills/<millId>/interruptible-windows/by-id/<windowId>", methods=["GET"])
def get_window_route(millId, windowId):
    require_auth()
    get_mill(millId)
    return ok(get_window(windowId, millId))


@bp.route("/mills/<millId>/interruptible-windows/<windowId>/honor", methods=["POST"])
def honor_window(millId, windowId):
    require_role("EnergyDispatcher")
    get_mill(millId)
    win = get_window(windowId, millId)
    if win["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "window is not SCHEDULED")
    ev = None
    if win.get("linked_event_id"):
        ev = db.events.get(win["linked_event_id"])
    if ev is None or ev["status"] != "RELEASED":
        raise err("ERR_INVALID_STATE",
                  "window has no linked RELEASED event")
    month = win["start_at"].strftime("%Y-%m")
    sc = open_scorecard(millId, month)
    if sc is not None:
        sc["curtailment_credits_cents"] += win["curtailment_credit_cents"]
        sc["energy_cost_cents"] = max(
            0, sc["energy_cost_cents"] - win["curtailment_credit_cents"])
        recompute_scorecard_profit(sc)
    win["status"] = "HONORED"
    bump(win)
    return ok(win)


# --- energy events ---------------------------------------------------------------

@bp.route("/mills/<millId>/energy-events", methods=["POST"])
def create_event(millId):
    require_role("EnergyDispatcher")
    get_mill(millId)
    body = get_body()
    operator = req_str(body, "grid_operator")
    called = parse_dt(req_str(body, "called_at"), "called_at")
    released = parse_dt(req_str(body, "released_at"), "released_at")
    if released <= called:
        raise err("ERR_INVALID_REQUEST", "released_at must be after called_at")
    ev = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "grid_operator": operator,
        "called_at": called,
        "released_at": released,
        "waiver_count": 0,
        "status": "DECLARED",
        **new_common(),
    }
    db.events[ev["id"]] = ev
    return ok(ev, 201)


@bp.route("/mills/<millId>/energy-events", methods=["GET"])
def list_events(millId):
    require_auth()
    get_mill(millId)
    rows = [e for e in db.events.values() if e["mill_id"] == millId]
    return list_response(rows, {"status": "status"})


@bp.route("/mills/<millId>/energy-events/by-id/<eventId>", methods=["GET"])
def get_event_route(millId, eventId):
    require_auth()
    get_mill(millId)
    return ok(get_event(eventId, millId))


@bp.route("/mills/<millId>/energy-events/<eventId>/activate", methods=["POST"])
def activate_event(millId, eventId):
    require_role("EnergyDispatcher")
    get_mill(millId)
    ev = get_event(eventId, millId)
    if ev["status"] != "DECLARED":
        raise err("ERR_INVALID_STATE", "event is not DECLARED")
    for other in db.events.values():
        if other["mill_id"] == millId and other["id"] != eventId \
                and other["status"] == "ACTIVE":
            raise err("ERR_EVENT_OVERLAP", "another event is ACTIVE")
    prior = [o for o in db.events.values()
             if o["mill_id"] == millId and o["id"] != eventId
             and o["status"] == "RELEASED"]
    for o in prior:
        gap = ev["called_at"] - o["released_at"]
        if gap >= timedelta(0) and gap < timedelta(minutes=EVENT_MIN_GAP_MINUTES):
            raise err("ERR_EVENT_OVERLAP",
                      "less than 15 minutes since previous event release")
    ev["status"] = "ACTIVE"
    for w in db.windows.values():
        if (w["mill_id"] == millId and w["status"] == "SCHEDULED"
                and w["start_at"] <= ev["called_at"] <= w["end_at"]):
            w["linked_event_id"] = eventId
    bump(ev)
    refresh_posture(millId)
    return ok(ev)


@bp.route("/mills/<millId>/energy-events/<eventId>/release", methods=["POST"])
def release_event(millId, eventId):
    require_role("EnergyDispatcher")
    get_mill(millId)
    ev = get_event(eventId, millId)
    if ev["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "event is not ACTIVE")
    ev["status"] = "RELEASED"
    bump(ev)
    refresh_posture(millId)
    from services import heat_waiver_covered
    for heat in list(db.heats.values()):
        if (heat["mill_id"] == millId
                and heat["status"] in ("CHARGED", "MELTDOWN_LOCKED")
                and not heat_waiver_covered(heat)):
            abort_heat(heat)
    refresh_posture(millId)
    return ok(ev)


# --- power waivers ------------------------------------------------------------

@bp.route("/mills/<millId>/power-waivers", methods=["POST"])
def create_waiver(millId):
    uid, _role = require_role("EnergyDispatcher")
    get_mill(millId)
    body = get_body()
    scope = req_enum(body, "scope", {"HEAT", "EVENT"})
    scope_id = req_str(body, "scope_id")
    reason = req_str(body, "reason")
    if scope == "HEAT":
        get_heat(scope_id, millId)
    else:
        get_event(scope_id, millId)
    for w in db.waivers.values():
        if w["scope"] == scope and w["scope_id"] == scope_id:
            raise err("ERR_WAIVER_DUPLICATE", "waiver already exists for this target")
    waiver = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "scope": scope,
        "scope_id": scope_id,
        "granted_by": uid,
        "reason": reason,
        "created_at": db.ts_now(),
    }
    db.waivers[waiver["id"]] = waiver
    if scope == "EVENT":
        db.events[scope_id]["waiver_count"] += 1
    return ok(waiver, 201)


@bp.route("/mills/<millId>/power-waivers", methods=["GET"])
def list_waivers(millId):
    require_auth()
    get_mill(millId)
    rows = [w for w in db.waivers.values() if w["mill_id"] == millId]
    return list_response(rows, {"scope": "scope", "scope_id": "scope_id"})


@bp.route("/mills/<millId>/power-waivers/by-id/<waiverId>", methods=["GET"])
def get_waiver_route(millId, waiverId):
    require_auth()
    get_mill(millId)
    w = db.waivers.get(waiverId)
    if w is None or w["mill_id"] != millId:
        raise err("ERR_INVALID_REQUEST", "waiver not found")
    return ok(w)


# --- flat reads ---------------------------------------------------------------

@bp.route("/mills/interruptible-windows", methods=["GET"])
def flat_list_windows():
    require_auth()
    return list_response(list(db.windows.values()),
                         {"mill_id": "mill_id", "linked_event_id": "linked_event_id",
                          "status": "status"})


@bp.route("/mills/interruptible-windows/<windowId>", methods=["GET"])
def flat_get_window(windowId):
    require_auth()
    return ok(get_window(windowId))


@bp.route("/mills/energy-events", methods=["GET"])
def flat_list_events():
    require_auth()
    return list_response(list(db.events.values()),
                         {"mill_id": "mill_id", "status": "status"})


@bp.route("/mills/energy-events/<eventId>", methods=["GET"])
def flat_get_event(eventId):
    require_auth()
    return ok(get_event(eventId))


@bp.route("/mills/power-waivers", methods=["GET"])
def flat_list_waivers():
    require_auth()
    return list_response(list(db.waivers.values()),
                         {"mill_id": "mill_id", "scope": "scope",
                          "scope_id": "scope_id"})


@bp.route("/mills/power-waivers/<waiverId>", methods=["GET"])
def flat_get_waiver(waiverId):
    require_auth()
    w = db.waivers.get(waiverId)
    if w is None:
        raise err("ERR_INVALID_REQUEST", "waiver not found")
    return ok(w)
