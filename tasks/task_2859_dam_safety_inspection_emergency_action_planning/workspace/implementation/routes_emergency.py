"""High-water events, elevation readings and coordinated drawdown (PRD Section 3.7)."""

from flask import Blueprint, request

import calc
import guards
import services
from common import (
    ApiError, INVALID, body_dict, dec, ok, ok_list, pagination, q_enum, q_str,
    v_dt, v_int, v_num, v_string,
)
from derive import (
    dam_available_storage_acre_ft, dam_hazard_class, dam_latest_eap_status,
    paginate, serialize_drawdown, serialize_event, serialize_reading,
)
from store import (
    db, event_drawdowns, event_readings, insert, insertion_order, pick_greatest,
    reach_drawdowns, touch,
)

bp = Blueprint("emergency", __name__)

NON_TERMINAL_DRAWDOWN = ("REQUESTED", "COORDINATED", "ACTIVE")


# ---------------------------------------------------------------------------
# High-water events
# ---------------------------------------------------------------------------

@bp.route("/high-water-events", methods=["POST"])
def declare_event():
    guards.authenticate(request, ("ProgramAdmin", "EmergencyCoordinator"))
    body = body_dict()
    dam_id = v_string(body, "dam_id", min_len=1)
    declared_at = v_dt(body, "declared_at")
    trigger_description = v_string(body, "trigger_description", min_len=1)
    declared_inflow_cfs = v_num(body, "declared_inflow_cfs", minimum=0)
    dam = guards.get_dam(dam_id)
    guards.check_dam_operable(dam)
    event = insert(db.events, {
        "dam_id": dam["id"],
        "declared_at": declared_at,
        "trigger_description": trigger_description,
        "declared_inflow_cfs": declared_inflow_cfs,
        "status": "MONITORING",
        "escalated_at": None,
        "stood_down_at": None,
        "final_pool_elevation_ft": None,
    })
    return ok(serialize_event(event), 201)


@bp.route("/high-water-events/<event_id>", methods=["GET"])
def read_event(event_id):
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    event = guards.get_event(event_id)
    guards.check_identity(user_id, role)
    return ok(serialize_event(event))


@bp.route("/high-water-events", methods=["GET"])
def list_events():
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    limit, offset = pagination()
    dam_id = q_str("dam_id")
    status = q_enum("status", calc.EVENT_STATUSES)
    guards.check_identity(user_id, role)
    rows = list(db.events.values())
    if dam_id is not None:
        rows = [r for r in rows if r["dam_id"] == dam_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    data, total = paginate(rows, limit, offset, serialize_event)
    return ok_list(data, limit, offset, total)


@bp.route("/high-water-events/<event_id>/readings", methods=["POST"])
def record_reading(event_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "EmergencyCoordinator"))
    body = body_dict()
    reading_at = v_dt(body, "reading_at")
    pool_elevation_ft = v_num(body, "pool_elevation_ft")
    observed_inflow_cfs = v_num(body, "observed_inflow_cfs", minimum=0)
    if reading_at > db.clock:
        raise ApiError(INVALID, "reading_at must be at or before the current logical clock")
    event = guards.get_event(event_id)
    guards.check_identity(user_id, role)
    guards.check_event_state(event, ("MONITORING", "EMERGENCY"))
    dam = guards.get_dam(event["dam_id"])

    freeboard = calc.freeboard_ft(dam["crest_elevation_ft"], pool_elevation_ft)
    level = calc.alert_level(freeboard)
    earlier = [r for r in event_readings(event["id"]) if r["reading_at"] < reading_at]
    predecessor = pick_greatest(earlier, "reading_at")
    rising = bool(predecessor is not None
                  and dec(pool_elevation_ft) > dec(predecessor["pool_elevation_ft"]))
    reading = insert(db.readings, {
        "high_water_event_id": event["id"],
        "reading_at": reading_at,
        "pool_elevation_ft": pool_elevation_ft,
        "observed_inflow_cfs": observed_inflow_cfs,
        "freeboard_ft": freeboard,
        "alert_level": level,
        "rising": rising,
        "recorded_by_user_id": user_id,
    }, versioned=False)
    # Auto-escalation: a deteriorating trend, not a bad instantaneous number.
    if event["status"] == "MONITORING" and level in ("CRITICAL", "OVERTOPPING") and rising:
        event["status"] = "EMERGENCY"
        event["escalated_at"] = db.clock
        touch(event)
    else:
        touch(event, bump=False)
    return ok(serialize_reading(reading), 201)


@bp.route("/high-water-events/<event_id>/readings", methods=["GET"])
def list_readings(event_id):
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    limit, offset = pagination()
    level = q_enum("alert_level", calc.ALERT_LEVELS)
    event = guards.get_event(event_id)
    guards.check_identity(user_id, role)
    rows = event_readings(event["id"])
    if level is not None:
        rows = [r for r in rows if r["alert_level"] == level]
    data, total = paginate(rows, limit, offset, serialize_reading)
    return ok_list(data, limit, offset, total)


@bp.route("/high-water-events/<event_id>/stand-down", methods=["POST"])
def stand_down_event(event_id):
    guards.authenticate(request, ("EmergencyCoordinator",))
    body = body_dict()
    final_pool_elevation_ft = v_num(body, "final_pool_elevation_ft")
    event = guards.get_event(event_id)
    guards.check_event_state(event, ("MONITORING", "EMERGENCY"))
    event["status"] = "STOOD_DOWN"
    event["stood_down_at"] = db.clock
    event["final_pool_elevation_ft"] = final_pool_elevation_ft
    touch(event)
    for order in insertion_order(event_drawdowns(event["id"])):
        if order["status"] not in NON_TERMINAL_DRAWDOWN:
            continue
        released = services.cancel_drawdown(order, "EVENT_STOOD_DOWN")
        if released:
            reach = db.reaches.get(order["river_reach_id"])
            if reach is not None:
                touch(reach)
            dam = db.dams.get(order["dam_id"])
            if dam is not None:
                touch(dam)
    return ok(serialize_event(event))


# ---------------------------------------------------------------------------
# Drawdown orders
# ---------------------------------------------------------------------------

@bp.route("/drawdown-orders", methods=["POST"])
def request_drawdown():
    guards.authenticate(request, ("ProgramAdmin", "EmergencyCoordinator"))
    body = body_dict()
    dam_id = v_string(body, "dam_id", min_len=1)
    high_water_event_id = v_string(body, "high_water_event_id", min_len=1)
    requested_release_cfs = v_int(body, "requested_release_cfs", minimum=1)
    window_start = v_dt(body, "window_start")
    window_end = v_dt(body, "window_end")
    if window_end <= window_start:
        raise ApiError(INVALID, "window_end must be strictly after window_start")
    dam = guards.get_dam(dam_id)
    event = guards.get_event(high_water_event_id)
    guards.check_event_state(event, ("MONITORING", "EMERGENCY"))
    guards.check_dam_operable(dam)
    # Rung 23: a HIGH-hazard dam needs an approved emergency action plan.
    if dam_hazard_class(dam) == "HIGH" and dam_latest_eap_status(dam["id"]) != "APPROVED":
        raise ApiError("ERR_EAP_NOT_APPROVED",
                       "a HIGH-hazard dam requires an approved emergency action plan")
    guards.check_dam_classified(dam)
    # Rung 41: the named event must belong to the same dam as the order.
    if event["dam_id"] != dam["id"]:
        raise ApiError("ERR_EVENT_DAM_MISMATCH", "the high-water event belongs to a different dam")
    order = insert(db.drawdowns, {
        "dam_id": dam["id"],
        "river_reach_id": dam["river_reach_id"],
        "high_water_event_id": event["id"],
        "requested_release_cfs": requested_release_cfs,
        "window_start": window_start,
        "window_end": window_end,
        "planned_release_acre_ft": calc.planned_release_acre_ft(
            requested_release_cfs, window_start, window_end),
        "actual_release_acre_ft": None,
        "status": "REQUESTED",
        "coordinated_at": None,
        "activated_at": None,
        "completed_at": None,
        "cancelled_at": None,
        "cancel_reason": None,
    })
    return ok(serialize_drawdown(order), 201)


@bp.route("/drawdown-orders/<drawdown_id>", methods=["GET"])
def read_drawdown(drawdown_id):
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    order = guards.get_drawdown(drawdown_id)
    guards.check_identity(user_id, role)
    return ok(serialize_drawdown(order))


@bp.route("/drawdown-orders", methods=["GET"])
def list_drawdowns():
    user_id, role = guards.authenticate(
        request, ("ProgramAdmin", "Engineer", "DamOwner", "EmergencyCoordinator"))
    limit, offset = pagination()
    dam_id = q_str("dam_id")
    river_reach_id = q_str("river_reach_id")
    high_water_event_id = q_str("high_water_event_id")
    status = q_enum("status", calc.DRAWDOWN_STATUSES)
    guards.check_identity(user_id, role)
    rows = list(db.drawdowns.values())
    if dam_id is not None:
        rows = [r for r in rows if r["dam_id"] == dam_id]
    if river_reach_id is not None:
        rows = [r for r in rows if r["river_reach_id"] == river_reach_id]
    if high_water_event_id is not None:
        rows = [r for r in rows if r["high_water_event_id"] == high_water_event_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    data, total = paginate(rows, limit, offset, serialize_drawdown)
    return ok_list(data, limit, offset, total)


@bp.route("/drawdown-orders/<drawdown_id>/coordinate", methods=["POST"])
def coordinate_drawdown(drawdown_id):
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    expected_reach_version = v_int(body, "expected_reach_version")
    order = guards.get_drawdown(drawdown_id)
    guards.check_drawdown_state(order, ("REQUESTED",))
    reach = guards.get_reach(order["river_reach_id"])
    dam = guards.get_dam(order["dam_id"])
    guards.check_reach_version(reach, expected_reach_version)
    # Rung 28: channel capacity, with release windows treated as closed intervals.
    committed = 0
    for other in reach_drawdowns(reach["id"]):
        if other["id"] == order["id"] or other["status"] not in ("COORDINATED", "ACTIVE"):
            continue
        if other["window_start"] <= order["window_end"] and other["window_end"] >= order["window_start"]:
            committed += other["requested_release_cfs"]
    if committed + order["requested_release_cfs"] > reach["channel_capacity_cfs"]:
        raise ApiError("ERR_REACH_CAPACITY_EXCEEDED",
                       "the reach's channel capacity would be exceeded in this window")
    # Rung 29: reservoir storage sufficiency.
    if dec(order["planned_release_acre_ft"]) > dam_available_storage_acre_ft(dam):
        raise ApiError("ERR_INSUFFICIENT_STORAGE",
                       "planned release exceeds the dam's available conservation storage")
    order["status"] = "COORDINATED"
    order["coordinated_at"] = db.clock
    touch(order)
    touch(reach)
    touch(dam)
    return ok(serialize_drawdown(order))


@bp.route("/drawdown-orders/<drawdown_id>/activate", methods=["POST"])
def activate_drawdown(drawdown_id):
    guards.authenticate(request, ("EmergencyCoordinator",))
    order = guards.get_drawdown(drawdown_id)
    guards.check_drawdown_state(order, ("COORDINATED",))
    event = guards.get_event(order["high_water_event_id"])
    # Rung 24: capacity may be reserved on a watch, but water moves only in an emergency.
    if event["status"] != "EMERGENCY":
        raise ApiError("ERR_EVENT_NOT_IN_EMERGENCY", "the governing event has not reached EMERGENCY")
    order["status"] = "ACTIVE"
    order["activated_at"] = db.clock
    touch(order)
    return ok(serialize_drawdown(order))


@bp.route("/drawdown-orders/<drawdown_id>/complete", methods=["POST"])
def complete_drawdown(drawdown_id):
    guards.authenticate(request, ("EmergencyCoordinator",))
    body = body_dict()
    actual_release_acre_ft = v_num(body, "actual_release_acre_ft", minimum=0)
    order = guards.get_drawdown(drawdown_id)
    guards.check_drawdown_state(order, ("ACTIVE",))
    reach = db.reaches.get(order["river_reach_id"])
    dam = db.dams.get(order["dam_id"])
    order["status"] = "COMPLETED"
    order["completed_at"] = db.clock
    order["actual_release_acre_ft"] = actual_release_acre_ft
    touch(order)
    if reach is not None:
        touch(reach)
    if dam is not None:
        touch(dam)
    return ok(serialize_drawdown(order))


@bp.route("/drawdown-orders/<drawdown_id>/cancel", methods=["POST"])
def cancel_drawdown_order(drawdown_id):
    guards.authenticate(request, ("ProgramAdmin", "EmergencyCoordinator"))
    body = body_dict()
    reason = v_string(body, "reason", min_len=1)
    order = guards.get_drawdown(drawdown_id)
    guards.check_drawdown_state(order, NON_TERMINAL_DRAWDOWN)
    released = services.cancel_drawdown(order, reason)
    if released:
        reach = db.reaches.get(order["river_reach_id"])
        if reach is not None:
            touch(reach)
        dam = db.dams.get(order["dam_id"])
        if dam is not None:
            touch(dam)
    return ok(serialize_drawdown(order))
