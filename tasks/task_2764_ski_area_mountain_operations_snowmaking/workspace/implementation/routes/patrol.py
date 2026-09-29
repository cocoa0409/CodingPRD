"""Ski patrol: roster, duty, avalanche mitigation and incidents (PRD 3.6, 3.7)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import (auth, acting_patroller, ALL_ROLES, GUEST_SERVICES_AGENT,
                        LIFT_OPS_MANAGER, MOUNTAIN_OPS_DIRECTOR, PATROLLER)
from util import dec, rhu_int
from services import calc, cascade, serialize

bp = Blueprint("patrol", __name__)

CERT_LEVELS = ("BASIC", "OEC", "EMT", "PARAMEDIC")
MEDICAL_CERTS = ("EMT", "PARAMEDIC")
METHODS = ("EXPLOSIVE", "SKI_CUT", "GAS_EXPLODER")
HAZARD_RATINGS = ("LOW", "MODERATE", "CONSIDERABLE", "HIGH", "EXTREME")
CLEARING_RATINGS = ("LOW", "MODERATE")
SEVERITIES = ("MINOR", "MODERATE", "SERIOUS", "CRITICAL")
HIGH_SEVERITIES = ("SERIOUS", "CRITICAL")
TRANSPORT_MODES = ("TOBOGGAN", "SNOWMOBILE", "AMBULANCE", "HELICOPTER")
DISPOSITIONS = ("RELEASED_ON_HILL", "TRANSPORTED_TO_CLINIC", "TRANSFERRED_TO_EMS")
BLASTER_METHODS = ("EXPLOSIVE", "GAS_EXPLODER")
CLEARANCE_HOURS = {"EXPLOSIVE": 24, "GAS_EXPLODER": 24, "SKI_CUT": 8}
ROAD_CLOSURE_MINUTES_PER_CHARGE = 20


def _refresh_area(area):
    """Recompute the staffing gate for one area and cascade what it implies."""
    if area is None:
        return
    season = db.season_of_area(area)
    minimum = season["min_patrollers_per_open_area"] if season else 0
    if (area["opening_state"] == "OPEN"
            and calc.assigned_patroller_count(area) < minimum):
        cascade.hold_area(area)
    else:
        cascade.reevaluate_readiness(area)
    if season is not None:
        cascade.refresh_after_terrain_change(season)


@bp.route("/patrollers", methods=["POST"])
def create_patroller():
    auth(MOUNTAIN_OPS_DIRECTOR)
    body = validate.body()
    # Priority 4: season_id then assigned_terrain_area_id, in declaration order.
    season = validate.fk(body, "season_id", db.store.seasons, "ERR_SEASON_NOT_FOUND")
    area = None
    if body.get("assigned_terrain_area_id") is not None:
        area = validate.fk(body, "assigned_terrain_area_id", db.store.areas,
                           "ERR_TERRAIN_AREA_NOT_FOUND")
        if area is not None and area["season_id"] != season["id"]:
            raise ApiError("ERR_CROSS_SEASON_REFERENCE")
    # Priority 5.
    validate.get_str(body, "season_id")
    code = validate.get_str(body, "patroller_code", max_len=32)
    cert_level = validate.get_enum(body, "cert_level", CERT_LEVELS)
    full_name = validate.get_str(body, "full_name", required=False, max_len=120)
    blaster = validate.get_bool(body, "blaster_certified", required=False,
                                default=False)
    on_duty = validate.get_bool(body, "on_duty", required=False, default=False)
    # Priority 10.
    for peer in db.season_patrollers(season["id"]):
        if peer["patroller_code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE")
    # Priority 11.
    cascade.require_season_writable(season)
    row = db.new_row({
        "season_id": season["id"],
        "assigned_terrain_area_id": area["id"] if area is not None else None,
        "patroller_code": code,
        "full_name": full_name,
        "cert_level": cert_level,
        "blaster_certified": blaster,
        "on_duty": on_duty,
        "status": "AVAILABLE" if on_duty else "OFF_DUTY",
    })
    db.store.patrollers[row["id"]] = row
    if area is not None:
        _refresh_area(area)
    return response.object_response(serialize.patroller(row), 201)


@bp.route("/patrollers/<patroller_id>", methods=["GET"])
def get_patroller(patroller_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.patrollers, patroller_id,
                            "ERR_PATROLLER_NOT_FOUND")
    return response.object_response(serialize.patroller(row), 200)


@bp.route("/patrollers", methods=["GET"])
def list_patrollers():
    auth(*ALL_ROLES)
    limit, offset = validate.pagination()
    rows = db.ordered(db.store.patrollers)
    season_id = validate.query_value("season_id")
    area_id = validate.query_value("assigned_terrain_area_id")
    status = validate.query_value("status")
    on_duty = validate.query_value("on_duty")
    cert_level = validate.query_value("cert_level")
    if season_id:
        rows = [r for r in rows if r["season_id"] == season_id]
    if area_id:
        rows = [r for r in rows if r["assigned_terrain_area_id"] == area_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if on_duty is not None and on_duty != "":
        wanted = str(on_duty).lower() in ("true", "1", "yes")
        rows = [r for r in rows if r["on_duty"] is wanted]
    if cert_level:
        rows = [r for r in rows if r["cert_level"] == cert_level]
    return response.list_response(rows, serialize.patroller, limit, offset)


@bp.route("/patrollers/<patroller_id>/duty", methods=["POST"])
def set_duty(patroller_id):
    auth(MOUNTAIN_OPS_DIRECTOR)
    patroller = validate.path_row(db.store.patrollers, patroller_id,
                                 "ERR_PATROLLER_NOT_FOUND")
    body = validate.body()
    on_duty = validate.get_bool(body, "on_duty")
    season = db.store.seasons.get(patroller["season_id"])
    cascade.require_season_writable(season)
    patroller["on_duty"] = on_duty
    if not on_duty:
        patroller["status"] = "OFF_DUTY"
    elif patroller["status"] != "ON_INCIDENT":
        patroller["status"] = "AVAILABLE"
    db.mark(patroller)
    area = db.store.areas.get(patroller["assigned_terrain_area_id"])
    _refresh_area(area)
    return response.object_response(serialize.patroller(patroller), 200)


@bp.route("/mitigation-missions", methods=["POST"])
def create_mission():
    auth(PATROLLER, MOUNTAIN_OPS_DIRECTOR)
    body = validate.body()
    area = validate.fk(body, "terrain_area_id", db.store.areas,
                       "ERR_TERRAIN_AREA_NOT_FOUND")
    validate.get_str(body, "terrain_area_id")
    route_code = validate.get_str(body, "route_code", max_len=24)
    method = validate.get_enum(body, "method", METHODS)
    hazard_pre = validate.get_enum(body, "hazard_rating_pre", HAZARD_RATINGS)
    planned_charges = validate.get_int(body, "planned_charges", required=False,
                                      default=0, minimum=0, maximum=24)
    if method != "EXPLOSIVE" and planned_charges != 0:
        raise ApiError("ERR_INVALID_REQUEST")
    season = db.store.seasons.get(area["season_id"])
    cascade.require_season_writable(season)
    row = db.new_row({
        "terrain_area_id": area["id"],
        "executed_by_patroller_id": None,
        "cleared_by_patroller_id": None,
        "route_code": route_code,
        "method": method,
        "planned_charges": planned_charges,
        "hazard_rating_pre": hazard_pre,
        "hazard_rating_post": None,
        "state": "PLANNED",
        "charges_used": 0,
        "clearance_valid_hours": CLEARANCE_HOURS[method],
        "road_closure_minutes": 0,
        "executed_at": None,
        "cleared_at": None,
    })
    db.store.missions[row["id"]] = row
    return response.object_response(serialize.mission(row), 201)


@bp.route("/mitigation-missions/<mission_id>", methods=["GET"])
def get_mission(mission_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.missions, mission_id, "ERR_MISSION_NOT_FOUND")
    return response.object_response(serialize.mission(row), 200)


@bp.route("/mitigation-missions", methods=["GET"])
def list_missions():
    auth(*ALL_ROLES)
    limit, offset = validate.pagination()
    rows = db.ordered(db.store.missions)
    area_id = validate.query_value("terrain_area_id")
    executed_by = validate.query_value("executed_by_patroller_id")
    cleared_by = validate.query_value("cleared_by_patroller_id")
    method = validate.query_value("method")
    state = validate.query_value("state")
    if area_id:
        rows = [r for r in rows if r["terrain_area_id"] == area_id]
    if executed_by:
        rows = [r for r in rows if r["executed_by_patroller_id"] == executed_by]
    if cleared_by:
        rows = [r for r in rows if r["cleared_by_patroller_id"] == cleared_by]
    if method:
        rows = [r for r in rows if r["method"] == method]
    if state:
        rows = [r for r in rows if r["state"] == state]
    return response.list_response(rows, serialize.mission, limit, offset)


@bp.route("/mitigation-missions/<mission_id>/execute", methods=["POST"])
def execute_mission(mission_id):
    _uid, _role, actor = acting_patroller(PATROLLER)
    mission = validate.path_row(db.store.missions, mission_id,
                                "ERR_MISSION_NOT_FOUND")
    body = validate.body()
    charges_used = validate.get_int(body, "charges_used", minimum=0, maximum=24)
    area = db.store.areas.get(mission["terrain_area_id"])
    season = db.store.seasons.get(area["season_id"]) if area else None
    # Priority 11: mitigation runs in PRESEASON as well as OPERATING.
    cascade.require_season_writable(season)
    # Priority 12: mitigation is never thrown over open terrain.
    if area["opening_state"] == "OPEN":
        raise ApiError("ERR_TERRAIN_STATE_INVALID")
    # Priority 15.
    if mission["state"] != "PLANNED":
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    # Priority 20.
    if not actor["on_duty"]:
        raise ApiError("ERR_PATROLLER_NOT_ON_DUTY")
    # Priority 21.
    if mission["method"] in BLASTER_METHODS and not actor["blaster_certified"]:
        raise ApiError("ERR_BLASTER_CERT_REQUIRED")
    # Priority 22: at least one other on-duty AVAILABLE patroller of the season.
    if mission["method"] == "SKI_CUT":
        partners = [p for p in db.season_patrollers(actor["season_id"])
                    if p["id"] != actor["id"] and p["on_duty"]
                    and p["status"] == "AVAILABLE"]
        if not partners:
            raise ApiError("ERR_SKI_CUT_PARTNER_REQUIRED")
    if mission["method"] != "EXPLOSIVE":
        charges_used = 0
    mission["state"] = "EXECUTED"
    mission["executed_at"] = db.now()
    mission["executed_by_patroller_id"] = actor["id"]
    mission["charges_used"] = charges_used
    mission["road_closure_minutes"] = ROAD_CLOSURE_MINUTES_PER_CHARGE * charges_used
    db.mark(mission)
    return response.object_response(serialize.mission(mission), 200)


@bp.route("/mitigation-missions/<mission_id>/clear", methods=["POST"])
def clear_mission(mission_id):
    _uid, _role, actor = acting_patroller(PATROLLER)
    mission = validate.path_row(db.store.missions, mission_id,
                                "ERR_MISSION_NOT_FOUND")
    body = validate.body()
    hazard_post = validate.get_enum(body, "hazard_rating_post", HAZARD_RATINGS)
    area = db.store.areas.get(mission["terrain_area_id"])
    season = db.store.seasons.get(area["season_id"]) if area else None
    cascade.require_season_writable(season)
    # Priority 15.
    if mission["state"] != "EXECUTED":
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    # Priority 19: the clearer may not be the executor.
    if actor["id"] == mission["executed_by_patroller_id"]:
        raise ApiError("ERR_SOD_VIOLATION")
    # Priority 20.
    if not actor["on_duty"]:
        raise ApiError("ERR_PATROLLER_NOT_ON_DUTY")
    # Priority 23.
    if actor["cert_level"] not in MEDICAL_CERTS:
        raise ApiError("ERR_PATROLLER_CERT_INSUFFICIENT")
    mission["hazard_rating_post"] = hazard_post
    mission["cleared_at"] = db.now()
    mission["cleared_by_patroller_id"] = actor["id"]
    if hazard_post in CLEARING_RATINGS:
        mission["state"] = "CLEARED"
        area["mitigation_clearance_expires_at"] = db.now() + timedelta(
            hours=mission["clearance_valid_hours"])
        db.mark(area)
        cascade.reevaluate_readiness(area)
    else:
        mission["state"] = "HOLD_EXTENDED"
        area["mitigation_clearance_expires_at"] = None
        db.mark(area)
        if area["opening_state"] == "OPEN":
            cascade.hold_area(area)
        else:
            cascade.reevaluate_readiness(area)
    db.mark(mission)
    cascade.refresh_after_terrain_change(season)
    return response.object_response(serialize.mission(mission), 200)


@bp.route("/incidents", methods=["POST"])
def create_incident():
    auth(PATROLLER, GUEST_SERVICES_AGENT, MOUNTAIN_OPS_DIRECTOR, LIFT_OPS_MANAGER)
    body = validate.body()
    area = validate.fk(body, "terrain_area_id", db.store.areas,
                       "ERR_TERRAIN_AREA_NOT_FOUND")
    validate.get_str(body, "terrain_area_id")
    reporter_code = validate.get_str(body, "reporter_code", max_len=32)
    severity = validate.get_enum(body, "severity", SEVERITIES)
    note = validate.get_str(body, "location_note", required=False, max_len=500)
    season = db.store.seasons.get(area["season_id"])
    cascade.require_season_writable(season)
    row = db.new_row({
        "terrain_area_id": area["id"],
        "responder_patroller_id": None,
        "reporter_code": reporter_code,
        "severity": severity,
        "location_note": note,
        "state": "REPORTED",
        "transport_mode": None,
        "disposition": None,
        "reported_at": db.now(),
        "dispatched_at": None,
        "transport_ordered_at": None,
        "closed_at": None,
        "response_minutes": 0,
    })
    db.store.incidents[row["id"]] = row
    return response.object_response(serialize.incident(row), 201)


@bp.route("/incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    auth(*ALL_ROLES)
    row = validate.path_row(db.store.incidents, incident_id,
                            "ERR_INCIDENT_NOT_FOUND")
    return response.object_response(serialize.incident(row), 200)


@bp.route("/incidents", methods=["GET"])
def list_incidents():
    auth(*ALL_ROLES)
    limit, offset = validate.pagination()
    rows = db.ordered(db.store.incidents)
    area_id = validate.query_value("terrain_area_id")
    responder = validate.query_value("responder_patroller_id")
    severity = validate.query_value("severity")
    state = validate.query_value("state")
    if area_id:
        rows = [r for r in rows if r["terrain_area_id"] == area_id]
    if responder:
        rows = [r for r in rows if r["responder_patroller_id"] == responder]
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    if state:
        rows = [r for r in rows if r["state"] == state]
    return response.list_response(rows, serialize.incident, limit, offset)


@bp.route("/incidents/<incident_id>/dispatch", methods=["POST"])
def dispatch_incident(incident_id):
    auth(MOUNTAIN_OPS_DIRECTOR)
    incident = validate.path_row(db.store.incidents, incident_id,
                                 "ERR_INCIDENT_NOT_FOUND")
    body = validate.body()
    # Priority 4: body reference plus the cross-season consistency check.
    responder = validate.fk(body, "patroller_id", db.store.patrollers,
                            "ERR_PATROLLER_NOT_FOUND")
    area = db.store.areas.get(incident["terrain_area_id"])
    if responder is not None and area is not None:
        if responder["season_id"] != area["season_id"]:
            raise ApiError("ERR_CROSS_SEASON_REFERENCE")
    validate.get_str(body, "patroller_id")
    season = db.store.seasons.get(area["season_id"]) if area else None
    cascade.require_season_writable(season)
    # Priority 15.
    if incident["state"] != "REPORTED":
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    # Priority 20, then 23, then 24 - the order matters on a nomination that
    # fails more than one of them.
    if not responder["on_duty"]:
        raise ApiError("ERR_PATROLLER_NOT_ON_DUTY")
    if incident["severity"] in HIGH_SEVERITIES:
        if responder["cert_level"] not in MEDICAL_CERTS:
            raise ApiError("ERR_PATROLLER_CERT_INSUFFICIENT")
    if responder["status"] != "AVAILABLE":
        raise ApiError("ERR_PATROLLER_BUSY")
    incident["state"] = "DISPATCHED"
    incident["dispatched_at"] = db.now()
    incident["responder_patroller_id"] = responder["id"]
    elapsed = db.now() - incident["reported_at"]
    incident["response_minutes"] = rhu_int(
        dec(elapsed.total_seconds()) / Decimal("60"))
    db.mark(incident)
    responder["status"] = "ON_INCIDENT"
    db.mark(responder)
    _refresh_area(db.store.areas.get(responder["assigned_terrain_area_id"]))
    return response.object_response(serialize.incident(incident), 200)


@bp.route("/incidents/<incident_id>/transport", methods=["POST"])
def order_transport(incident_id):
    _uid, _role, actor = acting_patroller(PATROLLER)
    incident = validate.path_row(db.store.incidents, incident_id,
                                 "ERR_INCIDENT_NOT_FOUND")
    if incident["responder_patroller_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    body = validate.body()
    mode = validate.get_enum(body, "transport_mode", TRANSPORT_MODES)
    area = db.store.areas.get(incident["terrain_area_id"])
    season = db.store.seasons.get(area["season_id"]) if area else None
    cascade.require_season_writable(season)
    # Priority 15.
    if incident["state"] != "DISPATCHED":
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    # Priority 36.
    if mode == "HELICOPTER" and incident["severity"] != "CRITICAL":
        raise ApiError("ERR_TRANSPORT_MODE_NOT_ALLOWED")
    if mode == "AMBULANCE" and incident["severity"] not in HIGH_SEVERITIES:
        raise ApiError("ERR_TRANSPORT_MODE_NOT_ALLOWED")
    incident["state"] = "TRANSPORT_ORDERED"
    incident["transport_ordered_at"] = db.now()
    incident["transport_mode"] = mode
    db.mark(incident)
    return response.object_response(serialize.incident(incident), 200)


@bp.route("/incidents/<incident_id>/close", methods=["POST"])
def close_incident(incident_id):
    _uid, _role, actor = acting_patroller(PATROLLER)
    incident = validate.path_row(db.store.incidents, incident_id,
                                 "ERR_INCIDENT_NOT_FOUND")
    if incident["responder_patroller_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED")
    body = validate.body()
    disposition = validate.get_enum(body, "disposition", DISPOSITIONS)
    area = db.store.areas.get(incident["terrain_area_id"])
    season = db.store.seasons.get(area["season_id"]) if area else None
    cascade.require_season_writable(season)
    # Priority 15: the disposition must match the state it is closed from.
    state = incident["state"]
    if state == "TRANSPORT_ORDERED":
        allowed = disposition in ("TRANSPORTED_TO_CLINIC", "TRANSFERRED_TO_EMS")
    elif state == "DISPATCHED":
        allowed = disposition == "RELEASED_ON_HILL"
    else:
        allowed = False
    if not allowed:
        raise ApiError("ERR_WORKFLOW_STATE_INVALID")
    incident["state"] = "CLOSED"
    incident["closed_at"] = db.now()
    incident["disposition"] = disposition
    db.mark(incident)
    responder = db.store.patrollers.get(incident["responder_patroller_id"])
    if responder is not None:
        if responder["on_duty"]:
            responder["status"] = "AVAILABLE"
        else:
            responder["status"] = "OFF_DUTY"
        db.mark(responder)
        _refresh_area(db.store.areas.get(responder["assigned_terrain_area_id"]))
    return response.object_response(serialize.incident(incident), 200)
