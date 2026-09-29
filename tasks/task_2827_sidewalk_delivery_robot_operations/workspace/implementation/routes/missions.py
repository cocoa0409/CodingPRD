"""Dispatch, the merchant handoff and the mission lifecycle."""

from flask import Blueprint

import calc
import cascades
from common import must, serve_list
from db import bump, create_row, db, now_iso, parse_ts, public
from errors import ApiError, bad
from middleware import (
    action_role,
    arg_enum,
    arg_str,
    authorize,
    body,
    check_bool,
    check_enum,
    check_int,
    check_number,
    check_str,
    pagination,
)
from response import object_response

bp = Blueprint("missions", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "FleetDispatcher",
    "RemoteOperator",
    "SafetyOfficer",
    "MerchantOperator",
)
LOAD_ROLES = ("MerchantOperator", "PlatformAdmin")
TRANSITION_ROLES = ("FleetDispatcher", "RemoteOperator")
MISSION_STATES = (
    "PLANNED",
    "LOADED",
    "EN_ROUTE",
    "BLOCKED",
    "HANDOFF_READY",
    "COMPLETED",
    "ABORTED",
)
TERMINAL_STATES = ("COMPLETED", "ABORTED")
MISSION_ACTIONS = ("DEPART", "ARRIVE", "COMPLETE", "ABORT", "REPORT_BLOCKAGE", "RESUME")
ACTION_ROLES = {
    "DEPART": ("FleetDispatcher",),
    "ARRIVE": ("FleetDispatcher",),
    "COMPLETE": ("FleetDispatcher",),
    "ABORT": ("FleetDispatcher",),
    "REPORT_BLOCKAGE": ("RemoteOperator",),
    "RESUME": ("RemoteOperator",),
}
ABORT_REASONS = ("DISPATCH_CANCELLED", "UNRECOVERABLE_BLOCKAGE")


@bp.get("/delivery-missions")
def list_missions():
    authorize(READ_ROLES)
    limit, offset = pagination()
    order_id = arg_str("order_id")
    robot_id = arg_str("robot_id")
    mission_state = arg_enum("mission_state", MISSION_STATES)
    rows = []
    for mission in db.missions.values():
        if order_id is not None and mission["order_id"] != order_id:
            continue
        if robot_id is not None and mission["robot_id"] != robot_id:
            continue
        if mission_state is not None and mission["mission_state"] != mission_state:
            continue
        rows.append(mission)
    return serve_list(rows, limit, offset)


@bp.get("/delivery-missions/<mission_id>")
def get_mission(mission_id):
    authorize(READ_ROLES)
    return object_response(public(must("missions", mission_id)))


@bp.post("/delivery-missions")
def create_mission():
    authorize(("FleetDispatcher",))
    payload = body()
    for name in ("order_id", "robot_id", "expected_delivery_order_version"):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    order_id = check_str(payload, "order_id", 1, None)
    robot_id = check_str(payload, "robot_id", 1, None)
    expected_version = check_int(payload, "expected_delivery_order_version", ge=0)

    robot = must("robots", robot_id)
    order = must("orders", order_id)

    if order["version"] != expected_version:
        raise ApiError("ERR_STALE_ORDER_VERSION")

    if order["order_state"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    zone = db.zones.get(robot["zone_id"])
    if zone is None or zone["permit_state"] != "PERMITTED":
        raise ApiError("ERR_ZONE_NOT_PERMITTED")

    if robot["duty_state"] != "AVAILABLE":
        raise ApiError("ERR_ROBOT_NOT_AVAILABLE")

    if robot["health_state"] in ("IMPAIRED", "QUARANTINED"):
        raise ApiError("ERR_ROBOT_HEALTH_BLOCKED")

    if calc.dec(robot["max_speed_cm_s"]) > calc.dec(zone["ordinance_max_speed_cm_s"]):
        raise ApiError("ERR_ORDINANCE_SPEED_EXCEEDED")

    dropoff = db.segments.get(order["dropoff_segment_id"])
    dropoff_zone_id = dropoff["zone_id"] if dropoff is not None else None
    if robot["zone_id"] != dropoff_zone_id:
        raise ApiError(
            "ERR_ZONE_MISMATCH",
            "The robot does not belong to the zone of the order's dropoff segment.",
        )

    if calc.dec(order["payload_liters"]) > calc.dec(robot["container_capacity_liters"]):
        raise ApiError("ERR_PAYLOAD_CAPACITY_EXCEEDED")

    if calc.dec(robot["battery_pct"]) < calc.MIN_BATTERY_PCT:
        raise ApiError("ERR_NO_ELIGIBLE_ROBOT")
    if robot["rolling_autonomy_index"] < calc.MIN_ROLLING_INDEX:
        raise ApiError("ERR_NO_ELIGIBLE_ROBOT")
    if not calc.eligible_robots(zone):
        raise ApiError("ERR_NO_ELIGIBLE_ROBOT")

    if zone["on_mission_robot_count"] >= zone["max_concurrent_robots"]:
        raise ApiError("ERR_ZONE_ROBOT_CAP_EXCEEDED")

    mission = create_row(
        db.missions,
        {
            "order_id": order["id"],
            "robot_id": robot["id"],
            "mission_state": "PLANNED",
            "lid_access_code": None,
            "actual_payload_liters": None,
            "handoff_late": False,
            "active_route_plan_id": None,
            "blocking_segment_id": None,
            "traveled_distance_m": 0.0,
            "traversed_crossing_count": 0,
            "blocked_minutes": 0,
            "intervention_count": 0,
            "escalation_count": 0,
            "active_minutes": 0,
            "departed_at_utc": None,
            "blocked_at_utc": None,
            "completed_at_utc": None,
            "abort_reason": None,
        },
    )

    order["order_state"] = "DISPATCHED"
    order["dispatch_attempt_count"] += 1
    bump(order)

    robot["duty_state"] = "ON_MISSION"
    robot["active_mission_id"] = mission["id"]
    bump(robot)

    zone["on_mission_robot_count"] += 1
    bump(zone)

    return object_response(public(mission), 201)


@bp.post("/delivery-missions/<mission_id>/load")
def load_mission(mission_id):
    user_id, role = authorize(LOAD_ROLES)
    payload = body()

    mission = must("missions", mission_id)
    order = db.orders.get(mission["order_id"])
    merchant = db.merchants.get(order["merchant_id"]) if order is not None else None

    if role == "MerchantOperator":
        owner = merchant["id"] if merchant is not None else None
        if owner != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")

    for name in ("actual_payload_liters", "lid_seal_confirmed"):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    actual_payload = check_number(payload, "actual_payload_liters", gt=0)
    lid_seal_confirmed = check_bool(payload, "lid_seal_confirmed")
    if lid_seal_confirmed is not True:
        raise bad("Field 'lid_seal_confirmed' must be true to record a handoff.")

    if mission["mission_state"] in TERMINAL_STATES:
        raise ApiError("ERR_MISSION_ALREADY_TERMINAL")
    if mission["mission_state"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    robot = db.robots.get(mission["robot_id"])
    if robot is not None and calc.dec(actual_payload) > calc.dec(
        robot["container_capacity_liters"]
    ):
        raise ApiError("ERR_PAYLOAD_CAPACITY_EXCEEDED")

    zone = db.zones.get(robot["zone_id"]) if robot is not None else None

    mission["mission_state"] = "LOADED"
    mission["actual_payload_liters"] = actual_payload
    if zone is not None:
        zone["lid_code_sequence"] += 1
        mission["lid_access_code"] = "%06d" % (100000 + zone["lid_code_sequence"])
        bump(zone)

    elapsed = (parse_ts(now_iso()) - parse_ts(mission["created_at"])).total_seconds()
    sla = merchant["handoff_sla_seconds"] if merchant is not None else 0
    late = calc.dec(elapsed) > calc.dec(sla)
    mission["handoff_late"] = late
    bump(mission)

    if late and merchant is not None:
        merchant["exception_count"] += 1
        bump(merchant)

    return object_response(public(mission))


def _depart(mission, order, robot, zone):
    if mission["mission_state"] != "LOADED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    plan = db.plans.get(mission["active_route_plan_id"] or "")
    if plan is None or plan["plan_state"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The mission needs an ACTIVE route plan before it can depart.",
        )
    if zone is None or zone["permit_state"] != "PERMITTED":
        raise ApiError("ERR_ZONE_NOT_PERMITTED")
    if robot is None or robot["health_state"] in ("IMPAIRED", "QUARANTINED"):
        raise ApiError("ERR_ROBOT_HEALTH_BLOCKED")

    mission["mission_state"] = "EN_ROUTE"
    mission["departed_at_utc"] = now_iso()
    mission["traveled_distance_m"] = calc.as_float(
        calc.dec(mission["traveled_distance_m"]) + calc.dec(plan["total_length_m"]), 1
    )
    mission["traversed_crossing_count"] += plan["crossing_count"]
    bump(mission)
    if order is not None and order["order_state"] == "DISPATCHED":
        order["order_state"] = "IN_TRANSIT"
        bump(order)


def _arrive(mission):
    if mission["mission_state"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if cascades.open_takeover_exists(mission):
        raise ApiError("ERR_TAKEOVER_REQUIRED")
    mission["mission_state"] = "HANDOFF_READY"
    bump(mission)


def _complete(mission, order, robot, submitted_code):
    if mission["mission_state"] != "HANDOFF_READY":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if cascades.open_takeover_exists(mission):
        raise ApiError("ERR_TAKEOVER_REQUIRED")
    if submitted_code != mission["lid_access_code"]:
        raise ApiError("ERR_LID_CODE_MISMATCH")

    stamp = now_iso()
    mission["mission_state"] = "COMPLETED"
    mission["completed_at_utc"] = stamp
    if mission["departed_at_utc"] is None:
        mission["active_minutes"] = 0
    else:
        mission["active_minutes"] = cascades.whole_minutes_between(
            mission["departed_at_utc"], stamp
        )
    bump(mission)

    merchant = db.merchants.get(order["merchant_id"]) if order is not None else None
    if order is not None:
        grade = merchant["merchant_grade"] if merchant is not None else "STANDARD"
        settled = calc.settlement_at_completion(
            mission, order["payload_tier"], order["urgency_flag"], grade
        )
        order["order_state"] = "DELIVERED"
        order["settled_fee_cents"] = settled
        if parse_ts(stamp) > parse_ts(order["promised_by_utc"]):
            order["exception_reason"] = "LATE"
        bump(order)
        if merchant is not None:
            quoted = order["quoted_fee_cents"]
            merchant["escrowed_fee_cents"] -= quoted
            merchant["recognized_fee_cents"] += quoted
            merchant["settlement_variance_cents"] += settled - quoted
            bump(merchant)

    cascades.absorb_terminal_mission(robot, mission, "AVAILABLE")


def _report_blockage(mission, blocking_segment_id):
    if mission["mission_state"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    plan = db.plans.get(mission["active_route_plan_id"] or "")
    sequence = plan["segment_sequence"] if plan is not None else []
    if blocking_segment_id not in sequence:
        raise bad("Field 'blocking_segment_id' must name a segment of the active route plan.")

    mission["mission_state"] = "BLOCKED"
    mission["blocking_segment_id"] = blocking_segment_id
    mission["blocked_at_utc"] = now_iso()
    mission["active_route_plan_id"] = None
    bump(mission)
    if plan is not None:
        plan["plan_state"] = "SUPERSEDED"
        plan["rejection_reason"] = "SEGMENT_BLOCKED"
        bump(plan)


def _resume(mission, zone):
    if mission["mission_state"] != "BLOCKED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    plan = db.plans.get(mission["active_route_plan_id"] or "")
    if plan is None or plan["plan_state"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The mission needs a replacement ACTIVE route plan before it can resume.",
        )
    if zone is None or zone["permit_state"] != "PERMITTED":
        raise ApiError("ERR_ZONE_NOT_PERMITTED")
    for segment_id in plan["segment_sequence"]:
        segment = db.segments.get(segment_id)
        if segment is not None and segment["status"] == "BLOCKED":
            raise ApiError("ERR_SEGMENT_BLOCKED")

    stamp = now_iso()
    if mission["blocked_at_utc"] is not None:
        mission["blocked_minutes"] += cascades.whole_minutes_between(
            mission["blocked_at_utc"], stamp
        )
    mission["mission_state"] = "EN_ROUTE"
    mission["blocking_segment_id"] = None
    mission["blocked_at_utc"] = None
    mission["traveled_distance_m"] = calc.as_float(
        calc.dec(mission["traveled_distance_m"]) + calc.dec(plan["total_length_m"]), 1
    )
    mission["traversed_crossing_count"] += plan["crossing_count"]
    bump(mission)


@bp.post("/delivery-missions/<mission_id>/transitions")
def mission_transition(mission_id):
    user_id, role = authorize(TRANSITION_ROLES)
    payload = body()
    action = check_enum(payload, "action", MISSION_ACTIONS)
    action_role(role, action, ACTION_ROLES)

    reason_code = None
    lid_access_code = None
    blocking_segment_id = None
    if action == "ABORT":
        reason_code = check_enum(payload, "reason_code", ABORT_REASONS)
    elif action == "COMPLETE":
        lid_access_code = check_str(payload, "lid_access_code", 1, None)
    elif action == "REPORT_BLOCKAGE":
        blocking_segment_id = check_str(payload, "blocking_segment_id", 1, None)

    mission = must("missions", mission_id)
    if mission["mission_state"] in TERMINAL_STATES:
        raise ApiError("ERR_MISSION_ALREADY_TERMINAL")

    order = db.orders.get(mission["order_id"])
    robot = db.robots.get(mission["robot_id"])
    zone = db.zones.get(robot["zone_id"]) if robot is not None else None

    if action == "DEPART":
        _depart(mission, order, robot, zone)
    elif action == "ARRIVE":
        _arrive(mission)
    elif action == "COMPLETE":
        _complete(mission, order, robot, lid_access_code)
    elif action == "ABORT":
        cascades.abort_mission(mission, reason_code, "AVAILABLE")
    elif action == "REPORT_BLOCKAGE":
        _report_blockage(mission, blocking_segment_id)
    else:  # RESUME
        _resume(mission, zone)

    return object_response(public(mission))
